import unittest
from unittest.mock import patch

from src.ai.ai_reviewer import (
    SYSTEM_PROMPT,
    _is_deterministic_check_finding,
    _parse_findings,
    review_with_ai,
)
from src.ai.llm_client import LLMClientError
from src.config.settings import Settings
from src.models import ChangedFile, CheckResult, Finding


class AIReviewerTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            ai_endpoint="https://example.test/chat/completions",
            ai_api_key="test-key",
            ai_model="test-model",
        )

    def test_parser_accepts_json_fence_and_surrounding_text(self):
        response = (
            "The review result is:\n```json\n"
            '{"findings":[]}\n'
            "```\n"
        )

        self.assertEqual(_parse_findings(response), [])

    def test_parser_reads_potential_solution(self):
        response = (
            '{"findings":[{"file":"src/service.py","line":12,"severity":"medium",'
            '"message":"Controller duplicates service behavior",'
            '"reasoning":"Existing architecture keeps this logic in services.",'
            '"potential_solution":"Move the operation into the service and call it from the controller."}]}'
        )

        findings = _parse_findings(response)

        self.assertEqual(
            findings[0].potential_solution,
            "Move the operation into the service and call it from the controller.",
        )

    def test_ai_prompt_restricts_review_to_contextual_concerns(self):
        self.assertIn("Do NOT report names, filename conventions", SYSTEM_PROMPT)
        self.assertIn("duplication against existing/retrieved code", SYSTEM_PROMPT)
        self.assertIn("unnecessary complexity", SYSTEM_PROMPT)

    def test_classifies_deterministic_findings_for_suppression(self):
        duplicate = Finding(
            file="README.md",
            line=48,
            message="Line exceeds maximum length of 120 characters",
            reasoning="Violating max_line_length.",
        )
        contextual = Finding(
            file="src/controller.py",
            line=20,
            message="Controller duplicates business logic from the service layer.",
            reasoning="The project architecture keeps business logic in services.",
        )

        self.assertTrue(_is_deterministic_check_finding(duplicate))
        self.assertFalse(_is_deterministic_check_finding(contextual))

    def test_reviews_each_chunk_and_aggregates_findings(self):
        files = [
            ChangedFile(
                "src/search.py",
                "modified",
                patch="@@ -0,0 +1 @@\n+def search_one():\n+    return 1",
            ),
            ChangedFile(
                "src/other.py",
                "modified",
                patch="@@ -0,0 +1 @@\n+def search_two():\n+    return 2",
            ),
        ]
        responses = [
            '{"findings":[{"file":"src/search.py","line":1,"severity":"low",'
            '"message":"Issue one","reasoning":"Reason one"}]}',
            '{"findings":[]}',
        ]
        with patch("src.ai.ai_reviewer.LLMClient.review", side_effect=responses) as review:
            result = review_with_ai(
                self.settings,
                "Standards",
                files,
                allow_upload=True,
            )

        self.assertEqual(review.call_count, 2)
        self.assertEqual(result.status, "fail")
        self.assertEqual(len(result.findings), 1)
        self.assertIn("2 diff chunks", result.summary)

    def test_suppresses_ai_findings_repeating_deterministic_checks(self):
        file = ChangedFile(
            "src/example.py",
            "modified",
            patch="@@ -0,0 +1,2 @@\n+def badName():\n+    return 1",
        )
        responses = [
            '{"findings":['
            '{"file":"src/example.py","line":1,"severity":"medium",'
            '"message":"Function name badName violates snake_case convention",'
            '"reasoning":"Function names must use snake_case."},'
            '{"file":"src/example.py","line":2,"severity":"high",'
            '"message":"This controller duplicates the service logic",'
            '"reasoning":"Existing architecture keeps this logic in the service layer."}'
            ']}'
        ]
        deterministic_checks = [
            CheckResult(
                "function_name_convention",
                "naming",
                "fail",
                "One naming issue.",
                [
                    Finding(
                        file="src/example.py",
                        line=1,
                        message="Function name badName does not follow snake_case.",
                    )
                ],
            )
        ]
        with patch(
            "src.ai.ai_reviewer.LLMClient.review",
            side_effect=responses,
        ) as review:
            result = review_with_ai(
                self.settings,
                "Standards",
                [file],
                allow_upload=True,
                deterministic_checks=deterministic_checks,
            )

        self.assertIn("Deterministic checks already run", review.call_args.args[1])
        self.assertIn("Function name badName", review.call_args.args[1])
        self.assertEqual(result.status, "fail")
        self.assertEqual(len(result.findings), 1)
        self.assertIn("duplicates the service logic", result.findings[0].message)
        self.assertIn("Suppressed 1 AI finding", result.details)

    def test_reports_partial_progress_when_a_chunk_fails(self):
        files = [
            ChangedFile(
                f"src/file_{index}.py",
                "modified",
                patch=f"@@ -0,0 +1 @@\n+def search_{index}():\n+    return {index}",
            )
            for index in range(2)
        ]
        with patch(
            "src.ai.ai_reviewer.LLMClient.review",
            side_effect=[
                '{"findings":[]}',
                LLMClientError("rate limit"),
            ],
        ):
            result = review_with_ai(
                self.settings,
                "Standards",
                files,
                allow_upload=True,
            )

        self.assertEqual(result.status, "error")
        self.assertIn("1/2 diff chunks", result.summary)
        self.assertIn("Partial findings collected: 0", result.details)

    def test_repairs_malformed_json_response_once(self):
        files = [
            ChangedFile(
                "src/search.py",
                "modified",
                patch="@@ -0,0 +1 @@\n+def search():\n+    return 1",
            )
        ]
        with patch(
            "src.ai.ai_reviewer.LLMClient.review",
            side_effect=[
                "Here is the result: {findings: []}",
                '{"findings":[]}',
            ],
        ) as review:
            result = review_with_ai(
                self.settings,
                "Standards",
                files,
                allow_upload=True,
            )

        self.assertEqual(result.status, "pass")
        self.assertEqual(review.call_count, 2)

    def test_unrecoverable_json_does_not_become_a_passing_empty_review(self):
        files = [
            ChangedFile(
                "src/search.py",
                "modified",
                patch="@@ -0,0 +1 @@\n+def search():\n+    return 1",
            )
        ]
        with patch(
            "src.ai.ai_reviewer.LLMClient.review",
            side_effect=[
                "not parseable model output",
                '{"findings":[],"recovery":"unrecoverable"}',
            ],
        ):
            result = review_with_ai(
                self.settings,
                "Standards",
                files,
                allow_upload=True,
            )

        self.assertEqual(result.status, "error")
        self.assertIn("could not recover a complete findings object", result.details)
        self.assertIn("Initial response preview", result.details)


if __name__ == "__main__":
    unittest.main()
