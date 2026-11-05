import json
import tempfile
import unittest
from pathlib import Path

from src.models import CheckResult, Finding, PullRequest
from src.reporting.report_generator import build_report, overall_status, write_reports


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.pull_request = PullRequest(
            number=17,
            title="Improve validation",
            url="https://github.com/acme/example/pull/17",
            base_ref="main",
            base_sha="base123",
            head_ref="feature",
            head_sha="head456",
            comments_url="https://api.github.com/repos/acme/example/issues/17/comments",
        )

    def test_reports_verdict_and_finding_reasoning(self):
        checks = [
            CheckResult(
                "formatting",
                "formatting",
                "fail",
                "One issue found.",
                [
                    Finding(
                        "src/module.py",
                        "Line too long",
                        4,
                        "low",
                        "The limit is 120 characters.",
                        "Wrap the expression across multiple lines.",
                    )
                ],
            )
        ]
        report = build_report("acme/example", self.pull_request, "guidelines.md@main", checks)
        self.assertEqual(report["summary"]["status"], "fail")
        self.assertEqual(report["checks"][0]["findings"][0]["reasoning"], "The limit is 120 characters.")
        self.assertEqual(
            report["checks"][0]["findings"][0]["potential_solution"],
            "Wrap the expression across multiple lines.",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            _, markdown_path = write_reports(report, Path(temporary_directory), 17)
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("Potential solution: Wrap the expression across multiple lines.", markdown)

    def test_skipped_check_makes_result_incomplete(self):
        self.assertEqual(
            overall_status([CheckResult("ai_review", "ai", "skipped", "Not enabled.")]),
            "incomplete",
        )

    def test_writes_json_and_markdown(self):
        report = build_report(
            "acme/example",
            self.pull_request,
            "coding-standards.md@main",
            [CheckResult("naming", "naming", "pass", "No findings.")],
            standards_generated=True,
        )
        self.assertEqual(report["standards"]["basis"], "generic_defaults")
        self.assertTrue(report["standards"]["generated"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            json_path, markdown_path = write_reports(report, Path(temporary_directory), 17)
            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8"))["summary"]["status"],
                "pass",
            )
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("PR Review: acme/example#17", markdown)
            self.assertIn("**PASS**", markdown)

    def test_inferred_standards_provenance_is_reported(self):
        evidence = {
            "base_sha": "base123",
            "files_sampled": ["src/one.py", "src/two.py"],
        }
        report = build_report(
            "acme/example",
            self.pull_request,
            "pr-review-reports/.ai-review/coding-standards.md",
            [CheckResult("naming", "naming", "pass", "No findings.")],
            standards_generated=True,
            standards_evidence=evidence,
            standards_base_sha="base123",
        )
        self.assertEqual(report["standards"]["basis"], "base_branch_inference")
        self.assertEqual(report["standards"]["evidence"]["files_sampled"], evidence["files_sampled"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            _, markdown_path = write_reports(report, Path(temporary_directory), 17)
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("Standards inference", markdown)
        self.assertIn("Source files sampled: 2.", markdown)


if __name__ == "__main__":
    unittest.main()
