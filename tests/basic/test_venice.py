import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from aider import themes, venice
from aider.models import MODEL_ALIASES, Model


class TestVenice(TestCase):
    def setUp(self):
        self._runtime = dict(venice.runtime)
        venice._catalog = {
            "fetched_at": 0,
            "models": {
                "deepseek-v4-pro-0813": {
                    "availableContextTokens": 262144,
                    "capabilities": {"supportsFunctionCalling": True, "optimizedForCode": True},
                    "pricing": {"input": {"usd": 0.75}, "output": {"usd": 3.0}},
                    "traits": ["default_code"],
                }
            },
            "traits": dict(venice.FALLBACK_TRAITS),
        }

    def tearDown(self):
        venice.runtime.clear()
        venice.runtime.update(self._runtime)
        venice._catalog = None

    def test_aliases_point_at_venice(self):
        self.assertEqual(MODEL_ALIASES["venice"], "venice/default_code")
        self.assertTrue(venice.is_venice_model("venice/llama-3.3-70b"))
        self.assertFalse(venice.is_venice_model("gpt-4o"))

    def test_trait_and_character_parsing(self):
        self.assertEqual(
            venice.model_id("venice/default_code@my-agent"), "deepseek-v4-pro-0813"
        )
        self.assertEqual(
            venice.split_character("venice/llama-3.3-70b@my-agent"),
            ("venice/llama-3.3-70b", "my-agent"),
        )
        self.assertEqual(venice.split_character("venice/llama-3.3-70b"), ("venice/llama-3.3-70b", None))

    def test_model_info_from_catalog(self):
        info = venice.model_info("venice/default_code")
        self.assertEqual(info["max_input_tokens"], 262144)
        self.assertAlmostEqual(info["input_cost_per_token"], 0.75 / 1_000_000)
        self.assertTrue(info["supports_function_calling"])
        self.assertEqual(info["litellm_provider"], "venice")

    def test_model_uses_venice_settings(self):
        model = Model("venice")
        self.assertEqual(model.name, "venice/default_code")
        self.assertEqual(model.info["max_input_tokens"], 262144)
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertEqual(model.weak_model.name, "venice/fastest")

    def test_validate_environment(self):
        model = Model("venice")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VENICE_API_KEY", None)
            self.assertEqual(model.validate_environment()["missing_keys"], ["VENICE_API_KEY"])
        with patch.dict(os.environ, {"VENICE_API_KEY": "k"}):
            self.assertTrue(model.validate_environment()["keys_in_environment"])

    def test_apply_to_kwargs_routes_to_venice(self):
        venice.runtime["web_search"] = "on"
        with patch.dict(os.environ, {"VENICE_API_KEY": "secret"}):
            kwargs = venice.apply_to_kwargs("venice/default_code@pirate", {"model": "x"})
        self.assertEqual(kwargs["model"], "openai/deepseek-v4-pro-0813")
        self.assertEqual(kwargs["api_base"], venice.VENICE_API_BASE)
        self.assertEqual(kwargs["api_key"], "secret")
        params = kwargs["extra_body"]["venice_parameters"]
        self.assertEqual(params["character_slug"], "pirate")
        self.assertEqual(params["enable_web_search"], "on")
        self.assertTrue(params["include_venice_system_prompt"])

    def test_send_completion_uses_venice(self):
        model = Model("venice")
        with (
            patch.dict(os.environ, {"VENICE_API_KEY": "secret"}),
            patch("aider.models.litellm.completion") as completion,
        ):
            completion.return_value = SimpleNamespace(choices=[])
            model.send_completion([{"role": "user", "content": "hi"}], None, False)
        kwargs = completion.call_args.kwargs
        self.assertEqual(kwargs["model"], "openai/deepseek-v4-pro-0813")
        self.assertEqual(kwargs["api_base"], venice.VENICE_API_BASE)
        self.assertNotIn("character_slug", kwargs["extra_body"]["venice_parameters"])

    def test_catalog_skips_network_without_key(self):
        venice._catalog = None
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(venice, "_read_cache", return_value=None),
            patch.object(venice, "_get") as get,
        ):
            os.environ.pop("VENICE_API_KEY", None)
            cat = venice.catalog()
        get.assert_not_called()
        self.assertEqual(cat["traits"]["fastest"], venice.FALLBACK_TRAITS["fastest"])


class TestThemes(TestCase):
    def test_theme_fills_only_default_colors(self):
        from aider.args import get_parser

        parser = get_parser([], None)
        args = parser.parse_args(["--theme", "gemini", "--tool-error-color", "#123456"])
        themes.apply_to_args(args, parser)
        self.assertEqual(args.user_input_color, themes.THEMES["gemini"].user_input_color)
        self.assertEqual(args.tool_error_color, "#123456")
        self.assertEqual(args.code_theme, "monokai")

    def test_classic_keeps_original_colors(self):
        from aider.args import get_parser

        parser = get_parser([], None)
        args = parser.parse_args(["--theme", "classic"])
        themes.apply_to_args(args, parser)
        self.assertEqual(args.user_input_color, "#00cc00")
        self.assertEqual(args.assistant_output_color, "#0088ff")

    def test_context_meter(self):
        self.assertEqual(themes.context_meter(0, 0), "")
        self.assertEqual(themes.context_meter(50, 100, width=4), "▰▰▱▱ 50%")
        self.assertTrue(themes.context_meter(500, 100).endswith("100%"))

    def test_gradient_and_welcome_render(self):
        from rich.console import Console

        console = Console(record=True, width=100, color_system="truecolor")
        console.print(
            themes.welcome_panel(themes.get("aurora"), "9.9", "venice/default_code", "/tmp")
        )
        text = console.export_text()
        self.assertIn("aider v9.9", text)
        self.assertIn("venice/default_code", text)
        self.assertIn("/venice", text)


class TestVeniceAliases(TestCase):
    def test_character_suffix_on_alias(self):
        from aider.models import resolve_model_alias

        self.assertEqual(resolve_model_alias("venice@pirate"), "venice/default_code@pirate")
        self.assertEqual(resolve_model_alias("venice-smart"), "venice/most_intelligent")
        self.assertEqual(resolve_model_alias("@intel"), "@intel")
        self.assertEqual(resolve_model_alias("gpt-4o"), "gpt-4o")
