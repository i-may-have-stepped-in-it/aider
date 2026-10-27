"""
Venice.ai provider support.

Venice exposes an OpenAI-compatible API at https://api.venice.ai/api/v1, so
requests are routed through litellm's ``openai/`` provider with Venice's base
URL and key. On top of plain chat models, Venice offers:

* model *traits* (``default_code``, ``fastest``, ``most_uncensored`` ...) that
  always point at Venice's current best model for that job;
* *characters*, Venice-hosted personas/agents selected with
  ``venice_parameters.character_slug``;
* built-in web search (``venice_parameters.enable_web_search``).

Model names look like ``venice/<model-id>`` or ``venice/<trait>``, optionally
with a character attached: ``venice/<model-id>@<character-slug>``.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

VENICE_API_BASE = "https://api.venice.ai/api/v1"
VENICE_KEY_ENV = "VENICE_API_KEY"
PREFIX = "venice/"

CACHE_TTL = 60 * 60 * 24
CACHE_DIR = Path.home() / ".aider" / "caches"
MODELS_CACHE = CACHE_DIR / "venice_models.json"

# Trait -> model id used when the live trait table can't be fetched
# (snapshot of GET /models/traits, October 2026).
FALLBACK_TRAITS = {
    "default": "zai-org-glm-5-2",
    "default_code": "deepseek-v4-pro-0813",
    "default_reasoning": "kimi-k3",
    "default_vision": "qwen-3-8-27b",
    "function_calling_default": "zai-org-glm-5-2",
    "most_intelligent": "grok-4-7",
    "most_uncensored": "venice-uncensored-1-2",
    # Not a Venice trait: computed from the catalog as the cheapest capable model.
    "fastest": "openai-gpt-oss-120b",
}

# Minimum context for a model to be picked as the "fastest" helper model.
FASTEST_MIN_CONTEXT = 128_000

DEFAULT_CONTEXT = 128_000

# Settings that a user can toggle at runtime with /venice.
runtime = {
    "web_search": os.environ.get("VENICE_WEB_SEARCH", "auto"),
    "character": os.environ.get("VENICE_CHARACTER") or None,
}


def is_venice_model(name: Optional[str]) -> bool:
    return bool(name) and name.lower().startswith(PREFIX)


def api_base() -> str:
    return os.environ.get("VENICE_API_BASE", VENICE_API_BASE).rstrip("/")


def api_key() -> Optional[str]:
    return os.environ.get(VENICE_KEY_ENV)


def split_character(name: str) -> tuple[str, Optional[str]]:
    """Split ``venice/model@character`` into ``("venice/model", "character")``."""
    if "@" in name[len(PREFIX) :]:
        model, character = name.rsplit("@", 1)
        return model, character or None
    return name, None


def model_id(name: str) -> str:
    """Strip the ``venice/`` prefix and any ``@character`` suffix, resolving traits."""
    base, _ = split_character(name)
    mid = base[len(PREFIX) :] if is_venice_model(base) else base
    return resolve_trait(mid)


# --------------------------------------------------------------------------- #
# HTTP + cache
# --------------------------------------------------------------------------- #


def _get(path: str, timeout: float = 10.0) -> dict:
    import requests

    headers = {"Accept": "application/json"}
    key = api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    res = requests.get(f"{api_base()}{path}", headers=headers, timeout=timeout)
    res.raise_for_status()
    return res.json()


def _read_cache() -> Optional[dict]:
    try:
        data = json.loads(MODELS_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - data.get("fetched_at", 0) > CACHE_TTL:
        return None
    return data


def _write_cache(data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


_catalog: Optional[dict] = None


def catalog(refresh: bool = False) -> dict:
    """
    Return ``{"models": {id: spec}, "traits": {trait: id}}``.

    Reads from a 24h disk cache so startup stays fast; fetches from the Venice
    API when the cache is stale. Network failures fall back to built-in traits.
    """
    global _catalog
    if _catalog is not None and not refresh:
        return _catalog

    data = None if refresh else _read_cache()
    # Don't block startup on the network unless the user is actually set up for Venice.
    if data is None and (refresh or api_key()):
        try:
            models = _get("/models?type=text").get("data", [])
            try:
                traits = _get("/models/traits?type=text").get("data", {})
            except Exception:
                traits = {}
            data = {
                "fetched_at": time.time(),
                "models": {m["id"]: m.get("model_spec", {}) for m in models if "id" in m},
                "traits": traits,
            }
            _write_cache(data)
        except Exception:
            data = None
    if data is None:
        data = {"fetched_at": 0, "models": {}, "traits": {}}

    data.setdefault("traits", {})
    for trait, mid in FALLBACK_TRAITS.items():
        data["traits"].setdefault(trait, mid)
    _catalog = data
    return data


def _cheapest_capable(models: dict) -> Optional[str]:
    best = None
    for mid, spec in models.items():
        caps = spec.get("capabilities", {}) or {}
        price = ((spec.get("pricing") or {}).get("input") or {}).get("usd")
        if (
            spec.get("offline")
            or mid.startswith("e2ee-")
            or not caps.get("supportsFunctionCalling")
            or (spec.get("availableContextTokens") or 0) < FASTEST_MIN_CONTEXT
            or price is None
        ):
            continue
        if best is None or price < best[0]:
            best = (price, mid)
    return best[1] if best else None


# Small, fast, well-known models to use as the helper ("weak") model, best first.
FASTEST_PREFERENCE = ("claude-haiku-5-5", "openai-gpt-6-luna", "openai-gpt-oss-120b")


def resolve_trait(mid: str) -> str:
    if mid not in FALLBACK_TRAITS:
        return mid
    cat = catalog()
    if mid == "fastest" and cat["models"]:
        for preferred in FASTEST_PREFERENCE:
            spec = cat["models"].get(preferred)
            if spec is not None and not spec.get("offline"):
                return preferred
        cheapest = _cheapest_capable(cat["models"])
        if cheapest:
            return cheapest
    return cat["traits"].get(mid, FALLBACK_TRAITS[mid])


def model_info(name: str) -> dict:
    """Build a litellm-style model info dict from Venice's model spec."""
    mid = model_id(name)
    spec = catalog()["models"].get(mid, {})
    caps = spec.get("capabilities", {}) or {}
    pricing = spec.get("pricing", {}) or {}
    context = spec.get("availableContextTokens") or DEFAULT_CONTEXT

    def per_token(kind):
        usd = (pricing.get(kind) or {}).get("usd")
        return usd / 1_000_000 if usd else 0.0

    return {
        "max_input_tokens": context,
        "max_tokens": context,
        "max_output_tokens": spec.get("maxCompletionTokens") or min(context, 32_768),
        "input_cost_per_token": per_token("input"),
        "output_cost_per_token": per_token("output"),
        "litellm_provider": "venice",
        "mode": "chat",
        "supports_function_calling": bool(caps.get("supportsFunctionCalling")),
        "supports_vision": bool(caps.get("supportsVision")),
        "supports_reasoning": bool(caps.get("supportsReasoning")),
        "supports_reasoning_effort": bool(caps.get("supportsReasoningEffort")),
        "venice_model_id": mid,
        "venice_traits": spec.get("traits", []),
    }


def list_characters() -> list[dict]:
    try:
        return _get("/characters").get("data", [])
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Request building
# --------------------------------------------------------------------------- #


def venice_parameters(name: str) -> dict:
    _, character = split_character(name)
    character = character or runtime["character"]
    params = {
        "include_venice_system_prompt": False,
        "enable_web_search": runtime["web_search"],
    }
    if character:
        params["character_slug"] = character
        # Characters carry their own persona prompt; let Venice inject it.
        params["include_venice_system_prompt"] = True
    return params


def apply_to_kwargs(name: str, kwargs: dict) -> dict:
    """Rewrite litellm completion kwargs so the request goes to Venice."""
    kwargs["model"] = f"openai/{model_id(name)}"
    kwargs.setdefault("api_base", api_base())
    kwargs.setdefault("api_key", api_key())
    extra_body = dict(kwargs.get("extra_body") or {})
    params = venice_parameters(name)
    params.update(extra_body.get("venice_parameters") or {})
    extra_body["venice_parameters"] = params
    kwargs["extra_body"] = extra_body
    return kwargs
