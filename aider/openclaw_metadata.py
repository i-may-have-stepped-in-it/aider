"""
OpenClaw model metadata resolution and caching.

This module resolves metadata for OpenClaw aliases like ``openclaw:chat`` so
that aider can size context windows correctly without falling back to generic
"sane defaults".
"""

import json
import shutil
import subprocess
import time
from pathlib import Path


DEFAULT_OPENCLAW_CONTEXT = 200000


BUILTIN_OPENCLAW_METADATA = {
    "@speed": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "@intel": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "@uncen": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "openclaw:chat",
    },
    "openclaw:chat": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw-chat": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw-main": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw-responses": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw:kimi": {
        "max_input_tokens": 256000,
        "max_tokens": 256000,
        "max_output_tokens": 256000,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "moonshot/kimi-k2.5",
    },
    "openclaw:claude": {
        "max_input_tokens": 200000,
        "max_tokens": 200000,
        "max_output_tokens": 200000,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "anthropic/claude-sonnet-4-6",
    },
    "openclaw-speed": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw-intel": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
    "openclaw-uncen": {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
        "openclaw_resolved_model": "zai/glm-4.5-air",
    },
}


class OpenClawModelManager:
    CACHE_TTL = 60 * 10

    def __init__(self):
        self.cache_dir = Path.home() / ".aider" / "caches"
        self.cache_file = self.cache_dir / "openclaw_models.json"
        self.content = None
        self._cache_loaded = False

    def get_model_info(self, model):
        if not self.supports_model(model):
            return {}

        token = self._extract_token(model)

        self._ensure_content()

        info = self._get_info_from_content(model, token)
        if info:
            return info

        return self._get_builtin_info(model, token)

    def supports_model(self, model):
        return self._is_openclaw_name(model)

    def _is_openclaw_name(self, model):
        return (
            model == "openclaw"
            or model.startswith("@")
            or model.startswith("openclaw:")
            or model.startswith("openclaw-")
        )

    def _extract_token(self, model):
        if model == "openclaw":
            return "chat"
        if model.startswith("@"):
            return model[1:].strip().lower()
        if model.startswith("openclaw:"):
            return model.split(":", 1)[1].strip().lower() or "chat"
        if model.startswith("openclaw-"):
            return model.split("-", 1)[1].strip().lower()
        return "chat"

    def _ensure_content(self):
        self._load_cache()
        if not self.content:
            self._refresh_cache()

    def _load_cache(self):
        if self._cache_loaded:
            return

        self._cache_loaded = True

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if self.cache_file.exists():
                cache_age = time.time() - self.cache_file.stat().st_mtime
                if cache_age < self.CACHE_TTL:
                    self.content = json.loads(self.cache_file.read_text())
        except Exception:
            self.content = None

    def _refresh_cache(self):
        content = {
            "catalog": {},
            "aliases": {},
            "agents": {},
        }

        catalog = self._run_openclaw_json(["models", "list", "--json"])
        if catalog and isinstance(catalog, dict):
            for model_entry in catalog.get("models", []):
                key = model_entry.get("key")
                if not key:
                    continue
                content["catalog"][key] = model_entry
                for tag in model_entry.get("tags") or []:
                    if isinstance(tag, str) and tag.startswith("alias:"):
                        alias = tag.split(":", 1)[1].strip().lower()
                        if alias:
                            content["aliases"][alias] = key

        for agent_id in ("chat", "main"):
            status = self._run_openclaw_json(["models", "status", "--json", "--agent", agent_id])
            if status and isinstance(status, dict):
                content["agents"][agent_id] = {
                    "resolved_default": status.get("resolvedDefault") or status.get("defaultModel"),
                    "fallbacks": status.get("fallbacks") or [],
                }

        self.content = content

        try:
            self.cache_file.write_text(json.dumps(content, indent=2))
        except Exception:
            pass

    def _run_openclaw_json(self, argv):
        if not shutil.which("openclaw"):
            return None

        try:
            result = subprocess.run(
                ["openclaw"] + argv,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except Exception:
            return None

        if result.returncode != 0:
            return None

        text = (result.stdout or "").strip()
        if not text:
            return None

        decoder = json.JSONDecoder()
        starts = [idx for idx, char in enumerate(text) if char in "{["]
        for start in starts:
            try:
                payload, _end = decoder.raw_decode(text[start:])
                return payload
            except Exception:
                continue

        return None

    def _get_info_from_content(self, model, token):
        if not self.content:
            return {}

        resolved_key = None

        if token in self.content.get("agents", {}):
            resolved_key = self.content["agents"][token].get("resolved_default")

        if not resolved_key:
            resolved_key = self.content.get("aliases", {}).get(token)

        if not resolved_key and token == "chat":
            resolved_key = self.content.get("agents", {}).get("chat", {}).get("resolved_default")

        if not resolved_key:
            return {}

        model_entry = self.content.get("catalog", {}).get(resolved_key)
        if not model_entry:
            return {}

        return self._build_info(model_entry, resolved_key, source="gateway")

    def _build_info(self, model_entry, resolved_key, source):
        context_window = model_entry.get("contextWindow") or DEFAULT_OPENCLAW_CONTEXT
        return {
            "max_input_tokens": context_window,
            "max_tokens": context_window,
            "max_output_tokens": context_window,
            "input_cost_per_token": 0.0,
            "output_cost_per_token": 0.0,
            "litellm_provider": "openclaw",
            "openclaw_metadata_source": source,
            "openclaw_resolved_model": resolved_key,
        }

    def _get_builtin_info(self, model, token):
        if model in BUILTIN_OPENCLAW_METADATA:
            return dict(BUILTIN_OPENCLAW_METADATA[model])

        if token in ("chat", "main"):
            return dict(BUILTIN_OPENCLAW_METADATA["openclaw:chat"])

        generic = {
            "max_input_tokens": DEFAULT_OPENCLAW_CONTEXT,
            "max_tokens": DEFAULT_OPENCLAW_CONTEXT,
            "max_output_tokens": DEFAULT_OPENCLAW_CONTEXT,
            "input_cost_per_token": 0.0,
            "output_cost_per_token": 0.0,
            "litellm_provider": "openclaw",
            "openclaw_metadata_source": "fallback",
            "openclaw_resolved_model": model,
        }
        return generic
