import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_reads_groq_key_from_dotenv(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text("GROQ_API_KEY=groq-key\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_environment(env_file=env_file)

        self.assertEqual(settings.ai_api_key, "groq-key")

    def test_reads_vercel_credentials_from_dotenv(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text(
                'AI_GATEWAY_API_KEY="gateway-key"\n'
                "PR_REVIEW_AI_ENDPOINT=https://ai-gateway.vercel.sh/v1/chat/completions\n"
                "PR_REVIEW_AI_MODEL=moonshotai/kimi-k3\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_environment(env_file=env_file)

        self.assertEqual(settings.ai_api_key, "gateway-key")
        self.assertEqual(
            settings.ai_endpoint,
            "https://ai-gateway.vercel.sh/v1/chat/completions",
        )
        self.assertEqual(settings.ai_model, "moonshotai/kimi-k3")

    def test_process_environment_overrides_dotenv_and_vercel_key_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text(
                "AI_GATEWAY_API_KEY=dotenv-gateway-key\n"
                "PR_REVIEW_AI_API_KEY=legacy-key\n"
                "PR_REVIEW_AI_MODEL=dotenv-model\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "AI_GATEWAY_API_KEY": "process-gateway-key",
                    "PR_REVIEW_AI_MODEL": "process-model",
                },
                clear=True,
            ):
                settings = Settings.from_environment(env_file=env_file)

        self.assertEqual(settings.ai_api_key, "process-gateway-key")
        self.assertEqual(settings.ai_model, "process-model")

    def test_groq_key_takes_precedence_over_other_provider_keys(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text(
                "AI_GATEWAY_API_KEY=vercel-key\n"
                "GROQ_API_KEY=groq-key\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_environment(env_file=env_file)

        self.assertEqual(settings.ai_api_key, "groq-key")

    def test_legacy_api_key_name_remains_supported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text("PR_REVIEW_AI_API_KEY=legacy-key\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_environment(env_file=env_file)

        self.assertEqual(settings.ai_api_key, "legacy-key")

    def test_rejects_malformed_dotenv_without_printing_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text("AI_GATEWAY_API_KEY\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "line 1"):
                    Settings.from_environment(env_file=env_file)


if __name__ == "__main__":
    unittest.main()
