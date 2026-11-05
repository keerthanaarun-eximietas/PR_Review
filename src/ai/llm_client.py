
import math
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from src.config.settings import Settings


FINDINGS_JSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "pr_review_findings",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "line": {
                                "anyOf": [
                                    {"type": "integer", "minimum": 1},
                                    {"type": "null"},
                                ]
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"],
                            },
                            "message": {"type": "string"},
                            "reasoning": {"type": "string"},
                            "potential_solution": {"type": "string"},
                        },
                        "required": [
                            "file",
                            "line",
                            "severity",
                            "message",
                            "reasoning",
                            "potential_solution",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["findings"],
            "additionalProperties": False,
        },
    },
}


class LLMClientError(RuntimeError):
    """Raised when the configured AI endpoint cannot complete a review."""


class LLMClient:
    def __init__(self, settings: Settings, timeout: int = 90) -> None:
        self.settings = settings
        self.timeout = timeout

    def review(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not (
            self.settings.ai_endpoint
            and self.settings.ai_api_key
            and self.settings.ai_model
        ):
            raise LLMClientError(
                "Set PR_REVIEW_AI_ENDPOINT, GROQ_API_KEY "
                "(or PR_REVIEW_AI_API_KEY), and PR_REVIEW_AI_MODEL."
            )

        is_gpt_oss = self.settings.ai_model in {
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
        }
        payload: dict[str, Any] = {
            "model": self.settings.ai_model,
            "temperature": 0,
            "max_completion_tokens": 2_048,
            "response_format": response_format
            or (
                FINDINGS_JSON_SCHEMA
                if self.settings.ai_model == "openai/gpt-oss-20b"
                else {"type": "json_object"}
            ),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if is_gpt_oss:
            payload["reasoning_effort"] = "low"
            payload["reasoning_format"] = "hidden"

        request = urllib.request.Request(
            self.settings.ai_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.ai_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PR-Review/1.0",
            },
            method="POST",
        )

        try:
            try:
                body = self._send_with_rate_limit_retries(request)
            except LLMClientError as error:
                if "json_validate_failed" not in str(error):
                    raise

                payload.pop("response_format")
                request.data = json.dumps(payload).encode("utf-8")
                body = self._send_with_rate_limit_retries(request)

            result = json.loads(body)
            choice = result["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
            if not isinstance(content, str) or not content.strip():
                finish_reason = choice.get("finish_reason", "unknown")
                refusal_present = bool(message.get("refusal"))
                reasoning_present = bool(message.get("reasoning"))
                usage = result.get("usage")
                completion_tokens = (
                    usage.get("completion_tokens", "unknown")
                    if isinstance(usage, dict)
                    else "unknown"
                )
                raise LLMClientError(
                    "AI endpoint returned no final answer "
                    f"(finish_reason={finish_reason}, "
                    f"refusal_present={refusal_present}, "
                    f"reasoning_present={reasoning_present}, "
                    f"completion_tokens={completion_tokens})."
                )
            if choice.get("finish_reason") == "length":
                raise LLMClientError(
                    "AI endpoint stopped at the completion-token limit before returning a "
                    "complete review."
                )
            return content
        except LLMClientError:
            raise
        except urllib.error.URLError as error:
            raise LLMClientError(
                f"Could not reach AI endpoint: {error.reason}"
            ) from error

        except (
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            raise LLMClientError(
                "AI endpoint returned an invalid Chat Completions response."
            ) from error

    def _send(self, request: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _send_with_rate_limit_retries(self, request: urllib.request.Request) -> bytes:
        for attempt in range(3):
            try:
                return self._send(request)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:1000]
                retry_delay = self._rate_limit_delay(error, detail)
                status = error.code
                error.close()
                if retry_delay is None or attempt == 2:
                    raise self._http_error(status, detail) from error
                time.sleep(retry_delay)
        raise LLMClientError("AI endpoint retry limit was exceeded.")

    @staticmethod
    def _rate_limit_delay(
        error: urllib.error.HTTPError,
        detail: str,
    ) -> int | None:
        if error.code != 429:
            return None
        retry_after = error.headers.get("Retry-After") if error.headers else None
        if retry_after:
            try:
                delay = math.ceil(float(retry_after))
            except ValueError:
                delay = 0
        else:
            match = re.search(r"try again in\s+([\d.]+)\s*s", detail, re.IGNORECASE)
            delay = math.ceil(float(match.group(1))) if match else 0
        return delay if 0 < delay <= 120 else None

    @staticmethod
    def _http_error(status: int, detail: str) -> LLMClientError:
        if status == 401:
            message = "Groq authentication failed. Check your API key."
        elif status == 403:
            message = (
                "Groq denied the request. Check the response details "
                "for Cloudflare, account, or permission restrictions."
            )
        elif status == 429:
            message = "Groq rate limit or usage limit exceeded."
        else:
            message = f"AI endpoint returned HTTP {status}."
        return LLMClientError(f"{message} Details: {detail}")
