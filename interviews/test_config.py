"""Reading and checking `interviews.toml`."""

import os
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from interviews import config
from interviews.providers import ADAPTERS

GOOD = """\
[providers.anthropic]
key_env = "TEST_ANTHROPIC_KEY"

[interviews.new-mod]
provider = "anthropic"
model = "claude-opus-5-5"
effort = "high"
max_tokens = 32000
"""


class ConfigTest(SimpleTestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "interviews.toml"
            path.write_text(text)
            return config.load(path)

    def refused(self, text):
        with self.assertRaises(config.ConfigError) as caught:
            self.load(text)
        return str(caught.exception)


class ReadingTheConfig(ConfigTest):
    def test_the_committed_file_is_valid_and_sets_up_a_new_mod_interview(self):
        loaded = config.load(Path(settings.BASE_DIR) / "interviews.toml")

        interview = loaded.interviews["new-mod"]
        self.assertEqual(interview.provider, "anthropic")
        self.assertEqual(interview.model, "claude-opus-5-5")
        self.assertEqual(loaded.providers["anthropic"].key_env, "ANTHROPIC_API_KEY")

    def test_an_entry_is_read_as_written(self):
        interview = self.load(GOOD).interviews["new-mod"]

        self.assertEqual((interview.kind, interview.provider, interview.model, interview.effort,
                          interview.max_tokens),
                         ("new-mod", "anthropic", "claude-opus-5-5", "high", 32000))

    def test_effort_and_max_tokens_may_be_left_out(self):
        interview = self.load(GOOD.replace('effort = "high"\n', "")
                              .replace("max_tokens = 32000\n", "")).interviews["new-mod"]

        self.assertIsNone(interview.effort)
        self.assertGreater(interview.max_tokens, 0)

    def test_no_file_at_the_default_place_means_no_interviews(self):
        with tempfile.TemporaryDirectory() as folder:
            loaded = config.load(Path(folder) / "interviews.toml", required=False)

        self.assertEqual(loaded.interviews, {})

    def test_a_file_named_by_the_environment_must_be_there(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "elsewhere.toml"
            with self.assertRaises(config.ConfigError) as caught:
                config.load(missing)

        self.assertIn(str(missing), str(caught.exception))


class RefusingABadConfig(ConfigTest):
    def test_an_unknown_provider_is_named(self):
        message = self.refused(GOOD.replace('provider = "anthropic"', 'provider = "acme"'))

        self.assertIn("interviews.new-mod.provider", message)
        self.assertIn("acme", message)

    def test_an_unknown_provider_table_is_named(self):
        message = self.refused(GOOD + '\n[providers.acme]\nkey_env = "ACME_KEY"\n')

        self.assertIn("providers.acme", message)

    def test_a_missing_model_is_named(self):
        message = self.refused(GOOD.replace('model = "claude-opus-5-5"\n', ""))

        self.assertIn("interviews.new-mod.model", message)

    def test_an_effort_the_provider_rejects_is_named(self):
        message = self.refused(GOOD.replace('effort = "high"', 'effort = "extreme"'))

        self.assertIn("interviews.new-mod.effort", message)
        self.assertIn("extreme", message)

    def test_an_unknown_key_is_named(self):
        message = self.refused(GOOD.replace("max_tokens", "max_tokenz"))

        self.assertIn("interviews.new-mod.max_tokenz", message)

    def test_an_unknown_top_level_key_is_named(self):
        self.assertIn("budget", self.refused(GOOD + "\n[budget]\nturns = 3\n"))

    def test_an_unknown_limit_is_named(self):
        self.assertIn("limits.turns", self.refused(GOOD + "\n[limits]\nturns = 3\n"))

    def test_a_limit_that_is_not_a_positive_number_is_named(self):
        message = self.refused(GOOD + "\n[limits]\nturns_per_person_per_day = 0\n")

        self.assertIn("limits.turns_per_person_per_day", message)

    def test_an_unknown_kind_of_interview_is_named(self):
        self.assertIn("interviews.new-report",
                      self.refused(GOOD.replace("[interviews.new-mod]",
                                                "[interviews.new-report]")))

    def test_a_provider_with_no_table_is_named(self):
        message = self.refused(GOOD.replace('[providers.anthropic]\nkey_env = '
                                            '"TEST_ANTHROPIC_KEY"\n', ""))

        self.assertIn("providers.anthropic", message)

    def test_a_max_tokens_that_is_not_a_positive_number_is_named(self):
        self.assertIn("interviews.new-mod.max_tokens",
                      self.refused(GOOD.replace("32000", '"lots"')))

    def test_a_file_that_is_not_toml_says_so(self):
        self.assertIn("interviews.toml", self.refused("[interviews.new-mod\n"))

    def test_a_max_fix_attempts_that_is_not_a_whole_number_of_zero_or_more_is_named(self):
        for bad in ("-1", '"three"', "1.5", "true"):
            with self.subTest(bad):
                self.assertIn("interviews.new-mod.max_fix_attempts",
                              self.refused(GOOD + f"max_fix_attempts = {bad}\n"))


class FixAttempts(ConfigTest):
    def test_max_fix_attempts_is_three_unless_set(self):
        self.assertEqual(self.load(GOOD).interviews["new-mod"].max_fix_attempts, 3)

    def test_max_fix_attempts_may_be_set_and_may_be_zero(self):
        for value in (0, 5):
            with self.subTest(value):
                loaded = self.load(GOOD + f"max_fix_attempts = {value}\n")
                self.assertEqual(loaded.interviews["new-mod"].max_fix_attempts, value)

    def test_the_committed_file_sets_three(self):
        loaded = config.load(Path(settings.BASE_DIR) / "interviews.toml")

        self.assertEqual(loaded.interviews["new-mod"].max_fix_attempts, 3)


class ReadingTheLimits(ConfigTest):
    def test_both_limits_are_read_as_written(self):
        limits = self.load(GOOD + "\n[limits]\nturns_per_person_per_day = 40\n"
                                  "tokens_per_organization_per_month = 5000000\n").limits

        self.assertEqual((limits.turns_per_person_per_day,
                          limits.tokens_per_organization_per_month), (40, 5000000))

    def test_a_missing_limit_means_no_limit(self):
        limits = self.load(GOOD + "\n[limits]\nturns_per_person_per_day = 40\n").limits

        self.assertIsNone(limits.tokens_per_organization_per_month)
        self.assertIsNone(self.load(GOOD).limits.turns_per_person_per_day)


class WhetherAnInterviewIsOn(ConfigTest):
    def test_it_is_on_with_an_entry_and_its_providers_key(self):
        loaded = self.load(GOOD)

        with mock.patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "sk-test"}):
            llm = config.llm_for("new-mod", loaded)

        self.assertIsNotNone(llm)
        self.assertEqual(llm.settings.model, "claude-opus-5-5")

    def test_it_is_off_without_the_key(self):
        loaded = self.load(GOOD)

        with mock.patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": ""}):
            self.assertIsNone(config.llm_for("new-mod", loaded))

    def test_it_is_off_without_an_entry(self):
        loaded = self.load(GOOD.split("[interviews.new-mod]")[0])

        with mock.patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "sk-test"}):
            self.assertIsNone(config.llm_for("new-mod", loaded))


OPENROUTER = """\
[providers.openrouter]
kind = "openai-compatible"
base_url = "https://openrouter.ai/api/v1"
key_env = "TEST_OPENROUTER_KEY"

[interviews.new-mod]
provider = "openrouter"
model = "some/model"
effort = "high"
"""


class AnOpenAICompatibleProvider(ConfigTest):
    def test_a_new_mod_interview_runs_on_it_with_its_endpoint_and_key(self):
        loaded = self.load(OPENROUTER)

        with mock.patch.dict(os.environ, {"TEST_OPENROUTER_KEY": "sk-or"}):
            llm = config.llm_for("new-mod", loaded)

        self.assertIsInstance(llm.provider, ADAPTERS["openai-compatible"])
        self.assertEqual(llm.provider.base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(llm.provider.api_key, "sk-or")
        self.assertEqual(llm.settings.model, "some/model")

    def test_it_is_off_without_its_key(self):
        loaded = self.load(OPENROUTER)

        with mock.patch.dict(os.environ, {"TEST_OPENROUTER_KEY": ""}):
            self.assertIsNone(config.llm_for("new-mod", loaded))

    def test_a_local_endpoint_needs_no_key(self):
        loaded = self.load(OPENROUTER.replace('key_env = "TEST_OPENROUTER_KEY"\n', ""))

        llm = config.llm_for("new-mod", loaded)

        self.assertIsNotNone(llm)
        self.assertIsNone(llm.provider.api_key)

    def test_a_missing_base_url_is_named(self):
        message = self.refused(OPENROUTER.replace(
            'base_url = "https://openrouter.ai/api/v1"\n', ""))

        self.assertIn("providers.openrouter.base_url", message)

    def test_an_unknown_kind_is_named(self):
        message = self.refused(OPENROUTER.replace('"openai-compatible"', '"litellm"'))

        self.assertIn("providers.openrouter.kind", message)
        self.assertIn("litellm", message)

    def test_a_base_url_on_a_provider_that_takes_none_is_named(self):
        message = self.refused(GOOD.replace(
            'key_env = "TEST_ANTHROPIC_KEY"\n',
            'key_env = "TEST_ANTHROPIC_KEY"\nbase_url = "https://example.com"\n'))

        self.assertIn("providers.anthropic.base_url", message)

    def test_an_interview_naming_a_provider_with_no_table_is_named(self):
        message = self.refused(OPENROUTER.replace("[providers.openrouter]",
                                                  "[providers.elsewhere]"))

        self.assertIn("interviews.new-mod.provider", message)
        self.assertIn("openrouter", message)

    def test_an_effort_it_does_not_take_is_named(self):
        message = self.refused(OPENROUTER.replace('effort = "high"', 'effort = "extreme"'))

        self.assertIn("interviews.new-mod.effort", message)


class StartingUp(ConfigTest):
    def tearDown(self):
        config.configure()

    def test_a_bad_config_stops_the_app_naming_the_key(self):
        from django.apps import apps
        from django.core.exceptions import ImproperlyConfigured

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "interviews.toml"
            path.write_text(GOOD.replace('provider = "anthropic"', 'provider = "acme"'))
            with self.settings(INTERVIEWS_CONFIG=path), \
                    self.assertRaisesMessage(ImproperlyConfigured,
                                             "interviews.new-mod.provider"):
                apps.get_app_config("interviews").ready()
