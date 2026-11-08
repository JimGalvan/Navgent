import os
import runpy
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import call, patch, sentinel

from navgent.browser_agent import browser_agent
from navgent.settings import AgentSettings
from navgent.shared import llm


class ModelSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_default_models_keep_their_reasoning_effort(self) -> None:
        settings = AgentSettings()
        cases = (
            (llm.build_strong_model, settings.strong_model, "none"),
            (llm.build_fast_model, settings.fast_model, "low"),
            (llm.build_evidence_model, settings.evidence_model, "low"),
        )
        for builder, model, effort in cases:
            with self.subTest(model=model):
                with patch.object(llm, "init_chat_model", return_value=sentinel.model) as initialize:
                    self.assertIs(builder(model), sentinel.model)
                    initialize.assert_called_once_with(model, reasoning_effort=effort)

    def test_agent_settings_have_frozen_library_defaults(self) -> None:
        settings = AgentSettings()
        self.assertEqual(settings.strong_model, "openai:gpt-5.6-luna")
        self.assertEqual(settings.fast_model, "openai:gpt-5-nano")
        self.assertEqual(settings.evidence_model, "openai:gpt-5-nano")
        self.assertTrue(settings.headless)
        self.assertIsNone(settings.browser_channel)
        self.assertIsNone(settings.trace_path)
        with self.assertRaises(FrozenInstanceError):
            settings.headless = False

    def test_explicit_models_ignore_environment_settings(self) -> None:
        with patch.dict(os.environ, {"NAVGENT_STRONG_MODEL": "invalid", "NAVGENT_FAST_MODEL": "invalid"}):
            self.assertEqual(AgentSettings(), AgentSettings(strong_model="openai:gpt-5.6-luna"))
            for builder in (llm.build_strong_model, llm.build_fast_model):
                with self.subTest(builder=builder.__name__):
                    with patch.object(llm, "init_chat_model") as initialize:
                        builder("anthropic:explicit-model")
                        initialize.assert_called_once_with("anthropic:explicit-model")

    def test_custom_providers_receive_no_openai_reasoning_option(self) -> None:
        cases = (
            ("strong_model", llm.build_strong_model),
            ("fast_model", llm.build_fast_model),
        )
        for setting, builder in cases:
            with self.subTest(setting=setting):
                with patch.object(llm, "init_chat_model", return_value=sentinel.model) as initialize:
                    self.assertIs(builder("anthropic:some-model"), sentinel.model)
                    initialize.assert_called_once_with("anthropic:some-model")

    def test_custom_openai_models_keep_their_reasoning_effort(self) -> None:
        cases = (
            ("strong_model", llm.build_strong_model, "none"),
            ("fast_model", llm.build_fast_model, "low"),
        )
        for setting, builder, effort in cases:
            with self.subTest(setting=setting):
                with patch.object(llm, "init_chat_model") as initialize:
                    builder("  openai:custom-model  ")
                    initialize.assert_called_once_with("openai:custom-model", reasoning_effort=effort)

    def test_bare_model_ids_fail_before_initializing_a_model(self) -> None:
        cases = (
            ("strong_model", llm.build_strong_model),
            ("fast_model", llm.build_fast_model),
        )
        for setting, builder in cases:
            with self.subTest(setting=setting):
                with patch.object(llm, "init_chat_model") as initialize:
                    with self.assertRaisesRegex(RuntimeError, f"{setting} must use provider:model"):
                        builder("gpt-5-nano")
                    initialize.assert_not_called()

    def test_provider_and_model_must_both_be_present(self) -> None:
        for value in ("", "   ", ":some-model", "openai:", "openai: ", " :some-model"):
            with self.subTest(value=value):
                for builder in (llm.build_strong_model, llm.build_fast_model):
                    with patch.object(llm, "init_chat_model") as initialize:
                        with self.assertRaisesRegex(RuntimeError, "must use provider:model"):
                            builder(value)
                        initialize.assert_not_called()

    def test_importing_model_builders_does_not_load_settings_or_create_models(self) -> None:
        with patch("dotenv.load_dotenv") as load_dotenv:
            with patch("langchain.chat_models.init_chat_model") as initialize:
                runpy.run_path(llm.__file__)
                load_dotenv.assert_not_called()
                initialize.assert_not_called()

    def test_browser_agent_and_page_navigator_use_the_supplied_models(self) -> None:
        settings = AgentSettings(strong_model="openai:browser-model", fast_model="anthropic:navigator-model")
        with patch.dict(os.environ, {"NAVGENT_STRONG_MODEL": "invalid", "NAVGENT_FAST_MODEL": "invalid"}):
            with patch.object(llm, "init_chat_model", side_effect=[sentinel.fast_model, sentinel.strong_model]) as initialize:
                with patch.object(browser_agent, "create_deep_agent", return_value=sentinel.agent) as create:
                    agent = browser_agent.build_browser_agent(sentinel.browser, sentinel.inputs, settings)
        self.assertIs(agent, sentinel.agent)
        self.assertEqual(initialize.call_args_list, [
            call("anthropic:navigator-model"),
            call("openai:browser-model", reasoning_effort="none"),
        ])
        self.assertIs(create.call_args.kwargs["model"], sentinel.strong_model)
        self.assertIs(create.call_args.kwargs["subagents"][0]["model"], sentinel.fast_model)

    def test_vultr_models_use_the_vultr_endpoint_and_key(self) -> None:
        cases = (
            (llm.build_strong_model, "low"),
            (llm.build_fast_model, "minimal"),
            (llm.build_evidence_model, "minimal"),
        )
        with patch.dict(os.environ, {"VULTR_INFERENCE_API_KEY": "test-key"}):
            for builder, effort in cases:
                with self.subTest(builder=builder.__name__):
                    with patch.object(llm, "init_chat_model", return_value=sentinel.model) as initialize:
                        self.assertIs(builder(" vultr:glm-5.3-flash "), sentinel.model)
                        initialize.assert_called_once_with(
                            "openai:glm-5.3-flash",
                            base_url="https://api.vultrinference.com/v1",
                            api_key="test-key",
                            use_responses_api=False,
                            reasoning_effort=effort,
                        )

    def test_vultr_base_url_can_be_overridden(self) -> None:
        environment = {"VULTR_INFERENCE_API_KEY": "test-key", "VULTR_INFERENCE_BASE_URL": "https://example.test/v1"}
        with patch.dict(os.environ, environment):
            with patch.object(llm, "init_chat_model") as initialize:
                llm.build_fast_model("vultr:qwen3.8-flash-next")
        self.assertEqual(initialize.call_args.kwargs["base_url"], "https://example.test/v1")

    def test_vultr_models_need_an_inference_key(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"VULTR_INFERENCE_API_KEY": value}):
                    with patch.object(llm, "init_chat_model") as initialize:
                        with self.assertRaisesRegex(RuntimeError, "evidence_model uses Vultr, so VULTR_INFERENCE_API_KEY"):
                            llm.build_evidence_model("vultr:glm-5.3-flash")
                        initialize.assert_not_called()

    def test_vultr_model_is_a_chat_completions_client_for_vultr(self) -> None:
        with patch.dict(os.environ, {"VULTR_INFERENCE_API_KEY": "test-key"}):
            model = llm.build_strong_model("vultr:glm-5.3")
        self.assertEqual(model.model_name, "glm-5.3")
        self.assertEqual(model.openai_api_base, "https://api.vultrinference.com/v1")
        self.assertEqual(model.openai_api_key.get_secret_value(), "test-key")
        self.assertFalse(model.use_responses_api)
        self.assertEqual(model.reasoning_effort, "low")
