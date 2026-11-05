import unittest
from unittest.mock import patch

from src.ai.llm_client import LLMClientError
from src.ai.solution_generator import generate_potential_solutions
from src.config.settings import Settings
from src.models import ChangedFile, CheckResult, Finding


class SolutionGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            ai_endpoint="https://example.test/chat/completions",
            ai_api_key="test-key",
            ai_model="test-model",
        )
        self.changed_files = [
            ChangedFile(
                "src/example.py",
                "modified",
                content='def badName():\n    token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ"\n',
            )
        ]
        self.check = CheckResult(
            "function_name_convention",
            "naming",
            "fail",
            "One issue found.",
            [
                Finding(
                    "src/example.py",
                    "Function name 'badName' does not follow snake_case.",
                    line=1,
                    reasoning="Function names must use snake_case.",
                )
            ],
        )

    def test_generates_suggestions_without_changing_deterministic_verdict(self):
        with patch(
            "src.ai.solution_generator.LLMClient.review",
            return_value=(
                '{"solutions":[{"finding_id":0,'
                '"potential_solution":"Rename the function to bad_name."}]}'
            ),
        ) as review:
            result = generate_potential_solutions(
                self.settings,
                [self.check],
                self.changed_files,
                "Use snake_case for Python functions.",
                allow_upload=True,
            )

        self.assertEqual(
            self.check.findings[0].potential_solution,
            "Rename the function to bad_name.",
        )
        self.assertEqual(self.check.status, "fail")
        self.assertIn("generated potential solutions", result)
        prompt = review.call_args.args[1]
        self.assertIn("Use snake_case for Python functions.", prompt)
        self.assertIn("[REDACTED_SECRET]", prompt)
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ", prompt)
        self.assertEqual(
            review.call_args.kwargs["response_format"]["json_schema"]["name"],
            "pr_finding_solutions",
        )

    def test_does_not_call_ai_when_upload_is_not_enabled(self):
        with patch("src.ai.solution_generator.LLMClient.review") as review:
            result = generate_potential_solutions(
                self.settings,
                [self.check],
                self.changed_files,
                "Standards",
                allow_upload=False,
            )

        review.assert_not_called()
        self.assertEqual(self.check.findings[0].potential_solution, "")
        self.assertIn("AI uploads were not enabled", result)

    def test_reports_ai_failure_and_preserves_original_findings(self):
        with patch(
            "src.ai.solution_generator.LLMClient.review",
            side_effect=LLMClientError("rate limit"),
        ):
            result = generate_potential_solutions(
                self.settings,
                [self.check],
                self.changed_files,
                "Standards",
                allow_upload=True,
            )

        self.assertEqual(self.check.findings[0].potential_solution, "")
        self.assertEqual(self.check.status, "fail")
        self.assertIn("still lack a potential solution", result)
        self.assertIn("rate limit", result)

    def test_leaves_already_populated_solutions_unchanged(self):
        self.check.findings[0].potential_solution = "Existing recommendation."
        with patch("src.ai.solution_generator.LLMClient.review") as review:
            result = generate_potential_solutions(
                self.settings,
                [self.check],
                self.changed_files,
                "Standards",
                allow_upload=True,
            )

        review.assert_not_called()
        self.assertIsNone(result)
        self.assertEqual(
            self.check.findings[0].potential_solution,
            "Existing recommendation.",
        )


if __name__ == "__main__":
    unittest.main()
