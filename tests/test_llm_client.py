import io
import json
import urllib.error
import unittest
from unittest.mock import patch

from src.ai.ai_reviewer import SYSTEM_PROMPT
from src.ai.llm_client import LLMClient, LLMClientError
from src.config.settings import Settings


class LLMClientTests(unittest.TestCase):
    def test_json_mode_prompt_contains_lowercase_json_keyword(self):
        self.assertIn("json", SYSTEM_PROMPT)

    def test_sends_json_object_mode_and_returns_assistant_content(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return (
                    b'{"choices":[{"message":{"content":"{\\"findings\\":[]}"}}]}'
                )

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(result, '{"findings":[]}')
        self.assertIn(b'"type": "json_schema"', request.data)
        self.assertIn(b"valid json", request.data)
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["reasoning_format"], "hidden")
        self.assertEqual(payload["max_completion_tokens"], 2048)

    def test_retries_json_validation_error_without_json_mode(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"findings\\":[]}"}}]}'

        validation_error = urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(
                b'{"error":{"code":"json_validate_failed","failed_generation":""}}'
            ),
        )
        sent_payloads = []

        def fake_urlopen(request, timeout):
            sent_payloads.append(json.loads(request.data))
            if len(sent_payloads) == 1:
                raise validation_error
            return FakeResponse()

        with patch(
            "urllib.request.urlopen",
            side_effect=fake_urlopen,
        ) as urlopen:
            result = LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")

        self.assertEqual(result, '{"findings":[]}')
        self.assertEqual(urlopen.call_count, 2)
        self.assertIn("response_format", sent_payloads[0])
        self.assertNotIn("response_format", sent_payloads[1])

    def test_uses_custom_json_schema_when_provided(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "suggestions",
                "strict": True,
                "schema": {"type": "object"},
            },
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"solutions\\":[]}"}}]}'

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = LLMClient(settings).review(
                SYSTEM_PROMPT,
                "Suggest fixes.",
                response_format=response_format,
            )

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["response_format"], response_format)
        self.assertEqual(result, '{"solutions":[]}')

    def test_does_not_retry_other_http_400_errors(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )
        error = urllib.error.HTTPError(
            settings.ai_endpoint,
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":{"code":"invalid_model"}}'),
        )
        with patch("urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(LLMClientError):
                LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")
        self.assertEqual(urlopen.call_count, 1)

    def test_waits_for_provider_retry_interval_after_rate_limit(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )
        rate_limit = urllib.error.HTTPError(
            settings.ai_endpoint,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(
                b'{"error":{"message":"try again in 33.0975s",'
                b'"code":"rate_limit_exceeded"}}'
            ),
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"findings\\":[]}"}}]}'

        with (
            patch("urllib.request.urlopen", side_effect=[rate_limit, FakeResponse()]) as urlopen,
            patch("src.ai.llm_client.time.sleep") as sleep,
        ):
            result = LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")

        self.assertEqual(result, '{"findings":[]}')
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(34)

    def test_empty_assistant_content_reports_completion_metadata(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return (
                    b'{"choices":[{"finish_reason":"stop","message":{"content":""}}],'
                    b'"usage":{"completion_tokens":120}}'
                )

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(
                LLMClientError,
                r"no final answer.*finish_reason=stop.*reasoning_present=False.*completion_tokens=120",
            ):
                LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")

    def test_completion_limit_error_is_not_treated_as_an_empty_review(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return (
                    b'{"choices":[{"finish_reason":"length",'
                    b'"message":{"content":"{\\"findings\\":[]}"}}]}'
                )

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(LLMClientError, "completion-token limit"):
                LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")

    def test_empty_assistant_content_reports_response_metadata(self):
        settings = Settings(
            ai_endpoint="https://api.groq.com/openai/v1/chat/completions",
            ai_api_key="test-key",
            ai_model="openai/gpt-oss-20b",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return (
                    b'{"choices":[{"finish_reason":"stop","message":'
                    b'{"content":"","reasoning":"hidden reasoning"}}],'
                    b'"usage":{"completion_tokens":120}}'
                )

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(
                LLMClientError,
                r"no final answer.*finish_reason=stop.*reasoning_present=True.*completion_tokens=120",
            ):
                LLMClient(settings).review(SYSTEM_PROMPT, "Review this diff.")


if __name__ == "__main__":
    unittest.main()
