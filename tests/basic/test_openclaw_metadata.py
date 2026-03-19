import json
from pathlib import Path

from aider.models import Model
from aider.models import ModelInfoManager
from aider.openclaw_metadata import OpenClawModelManager


def test_openclaw_manager_uses_gateway_catalog_and_agent_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    def fake_run(self, argv):
        if argv == ["models", "list", "--json"]:
            return {
                "models": [
                    {
                        "key": "zai/glm-4.5-air",
                        "contextWindow": 204800,
                        "tags": ["default"],
                    },
                    {
                        "key": "moonshot/kimi-k2.5",
                        "contextWindow": 256000,
                        "tags": ["alias:Kimi"],
                    },
                ]
            }
        if argv == ["models", "status", "--json", "--agent", "chat"]:
            return {
                "resolvedDefault": "zai/glm-4.5-air",
                "fallbacks": ["moonshot/kimi-k2.5"],
            }
        if argv == ["models", "status", "--json", "--agent", "main"]:
            return {
                "resolvedDefault": "zai/glm-4.5-air",
                "fallbacks": [],
            }
        return None

    monkeypatch.setattr(OpenClawModelManager, "_run_openclaw_json", fake_run)

    manager = OpenClawModelManager()
    info = manager.get_model_info("openclaw:chat")

    assert info["max_input_tokens"] == 204800
    assert info["max_output_tokens"] == 204800
    assert info["openclaw_metadata_source"] == "gateway"
    assert info["openclaw_resolved_model"] == "zai/glm-4.5-air"


def test_openclaw_manager_uses_builtin_alias_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(OpenClawModelManager, "_run_openclaw_json", lambda self, argv: None)

    manager = OpenClawModelManager()
    info = manager.get_model_info("openclaw:kimi")

    assert info["max_input_tokens"] == 256000
    assert info["litellm_provider"] == "openclaw"
    assert info["openclaw_metadata_source"] == "builtin"


def test_openclaw_manager_uses_generic_openclaw_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(OpenClawModelManager, "_run_openclaw_json", lambda self, argv: None)

    manager = OpenClawModelManager()
    info = manager.get_model_info("openclaw:unknown-agent")

    assert info["max_input_tokens"] == 200000
    assert info["openclaw_metadata_source"] == "fallback"


def test_model_info_manager_uses_openclaw_manager(monkeypatch):
    stub_info = {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "gateway",
    }

    monkeypatch.setattr(
        "aider.models.OpenClawModelManager.get_model_info",
        lambda self, model: stub_info if model == "openclaw:chat" else {},
    )

    mim = ModelInfoManager()
    info = mim.get_model_info("openclaw:chat")

    assert info == stub_info


def test_model_info_manager_uses_openclaw_manager_for_gateway_tier(monkeypatch):
    stub_info = {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "gateway",
    }

    monkeypatch.setattr(
        "aider.models.OpenClawModelManager.get_model_info",
        lambda self, model: stub_info if model == "@speed" else {},
    )

    mim = ModelInfoManager()
    info = mim.get_model_info("@speed")

    assert info == stub_info


def test_gateway_tier_model_gets_openclaw_metadata(monkeypatch):
    stub_info = {
        "max_input_tokens": 204800,
        "max_tokens": 204800,
        "max_output_tokens": 204800,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "openclaw",
        "openclaw_metadata_source": "builtin",
    }

    monkeypatch.setattr(
        "aider.models.OpenClawModelManager.get_model_info",
        lambda self, model: stub_info if model == "@speed" else {},
    )

    model = Model("@speed")

    assert model.info["max_input_tokens"] == 204800


def test_openclaw_manager_parses_cli_output_with_plugin_noise(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/openclaw")

    class Result:
        returncode = 0
        stdout = "[plugins] loaded\\n" + json.dumps({"models": []}) + "\\n[plugins] done"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Result())

    manager = OpenClawModelManager()
    payload = manager._run_openclaw_json(["models", "list", "--json"])

    assert payload == {"models": []}
