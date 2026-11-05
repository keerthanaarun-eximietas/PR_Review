import json
import tempfile
import unittest
from pathlib import Path

from src.ai.context_retriever import build_review_context
from src.ai.ai_reviewer import AIReviewError, _parse_findings
from src.config.settings import Settings
from src.github.pr_extractor import GitHubError
from src.models import ChangedFile
from src.standards.standards_discovery import discover_standards
from src.standards.standards_generator import generate_standards
from src.standards.standards_parser import (
    DEFAULT_RULES,
    StandardsError,
    parse_standards,
)


class StandardsTests(unittest.TestCase):
    def test_parses_markdown_and_companion_json(self):
        document = parse_standards(
            "# Review\nPrefer small functions.",
            ".ai-review/coding-standards.md@main",
            json_text='{"max_file_lines": 250}',
        )
        self.assertIn("Prefer small functions", document.prose)
        self.assertEqual(document.rules.max_file_lines, 250)

    def test_json_standards_source_with_base_ref_preserves_false(self):
        document = parse_standards(
            '{"require_final_newline": false}',
            ".ai-review/coding-standards.json@main",
        )
        self.assertFalse(document.rules.require_final_newline)

    def test_rejects_invalid_json_rule_values(self):
        with self.assertRaises(StandardsError):
            parse_standards(
                "Guidelines",
                "guidelines.md",
                json_text='{"max_file_lines": 0}',
            )

    def test_generates_machine_readable_starter_standards(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            markdown, rules, source = generate_standards(
                "owner/repository",
                "main",
                Path(temporary_directory),
            )
            self.assertIn("Generated PR Review Guidelines", markdown)
            parsed_rules = json.loads(rules)
            self.assertEqual(parsed_rules["max_file_lines"], DEFAULT_RULES["max_file_lines"])
            self.assertEqual(parsed_rules["function_name_convention"], "snake_case")
            self.assertEqual(parsed_rules["variable_name_convention"], "snake_case")
            self.assertTrue(Path(source).exists())
            metadata = json.loads(
                (Path(temporary_directory) / ".ai-review" / "standards-metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(metadata["repository_conventions_inferred"])

    def test_generated_standards_preserve_existing_user_changes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            standards_dir = Path(temporary_directory) / ".ai-review"
            standards_dir.mkdir()
            json_path = standards_dir / "coding-standards.json"
            json_path.write_text('{"require_final_newline": false}\n', encoding="utf-8")

            _, rules_text, _ = generate_standards(
                "owner/repository",
                "main",
                Path(temporary_directory),
            )

        self.assertFalse(json.loads(rules_text)["require_final_newline"])

    def test_review_context_redacts_secret_like_values(self):
        context = build_review_context(
            "# Standards",
            [
                ChangedFile(
                    "settings.py",
                    "modified",
                    patch="+password = 'not-a-placeholder-secret'",
                )
            ],
        )
        self.assertNotIn("not-a-placeholder-secret", context)
        self.assertIn("[REDACTED_SECRET]", context)

    def test_review_context_redacts_camel_case_git_token(self):
        context = build_review_context(
            "# Standards",
            [
                ChangedFile(
                    "settings.py",
                    "modified",
                    patch='+gitToken = "git_0123456789abcdef0123456789abcdef"',
                )
            ],
        )
        self.assertNotIn("0123456789", context)
        self.assertIn("[REDACTED_SECRET]", context)

    def test_ai_response_requires_findings_array(self):
        with self.assertRaises(AIReviewError):
            _parse_findings("[]")

    def test_ai_response_parses_valid_finding(self):
        findings = _parse_findings(
            '{"findings":[{"file":"src/main.py","line":3,"severity":"medium",'
            '"message":"Repeated logic","reasoning":"Standards require shared helpers."}]}'
        )
        self.assertEqual(findings[0].line, 3)
        self.assertEqual(findings[0].severity, "medium")

    def test_ai_response_keeps_finding_but_omits_invalid_line_reference(self):
        findings = _parse_findings(
            '{"findings":[{"file":"src/main.py","line":0,"severity":"medium",'
            '"message":"Repeated logic","reasoning":"Consider extracting a helper."}]}'
        )
        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].line)
        self.assertIn("invalid line reference", findings[0].reasoning)

    def test_ai_response_keeps_finding_but_omits_string_line_reference(self):
        findings = _parse_findings(
            '{"findings":[{"file":"src/main.py","line":"3","severity":"medium",'
            '"message":"Repeated logic","reasoning":"Consider extracting a helper."}]}'
        )
        self.assertIsNone(findings[0].line)
        self.assertIn("invalid line reference", findings[0].reasoning)

    def test_discovery_uses_base_branch_standards_and_companion_json(self):
        class FakeGitHubClient:
            def __init__(self):
                self.requested = []

            def get_file(self, repo, path, ref):
                self.requested.append((path, ref))
                if path == ".ai-review/coding-standards.md":
                    return "# Base standards\nPrefer small functions."
                if path == ".ai-review/coding-standards.json":
                    return '{"max_file_lines": 250}'
                raise GitHubError("GitHub API returned HTTP 404: not found")

        with tempfile.TemporaryDirectory() as temporary_directory:
            client = FakeGitHubClient()
            standards = discover_standards(
                client,
                "owner/repository",
                "main",
                Settings(output_dir=Path(temporary_directory)),
            )
        self.assertEqual(standards.rules.max_file_lines, 250)
        self.assertFalse(standards.generated)
        self.assertIn("main", [ref for _, ref in client.requested])
        self.assertEqual(client.requested[0][0], ".ai-review/coding-standards.md")

    def test_discovery_parses_json_only_standards_from_base_branch(self):
        class JsonStandardsClient:
            def get_file(self, repo, path, ref):
                if path == ".ai-review/coding-standards.md":
                    raise GitHubError("GitHub API returned HTTP 404: not found")
                if path == ".ai-review/coding-standards.json":
                    return '{"require_final_newline": false}'
                raise AssertionError(f"Unexpected standards lookup: {path}")

        with tempfile.TemporaryDirectory() as temporary_directory:
            standards = discover_standards(
                JsonStandardsClient(),
                "owner/repository",
                "main",
                Settings(output_dir=Path(temporary_directory)),
            )
        self.assertFalse(standards.generated)
        self.assertFalse(standards.rules.require_final_newline)

    def test_missing_repository_standards_are_inferred_from_the_base_branch(self):
        class MissingStandardsClient:
            samples = {
                "src/one_file.py": "def fetchUser():\n    userName = 1\n    return userName\n",
                "src/two_file.py": "def fetchUser():\n    userName = 1\n    return userName\n",
                "src/three_file.py": "def fetchUser():\n    userName = 1\n    return userName\n",
                "pyproject.toml": "[tool.ruff]\nline-length = 99\n",
            }

            def get_file(self, repo, path, ref):
                if path in self.samples:
                    return self.samples[path]
                raise GitHubError("GitHub API returned HTTP 404: not found")

            def list_repository_files(self, repo, ref):
                return [
                    {"type": "blob", "path": path, "size": len(content)}
                    for path, content in self.samples.items()
                ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            standards = discover_standards(
                MissingStandardsClient(),
                "owner/repository",
                "main",
                Settings(output_dir=Path(temporary_directory)),
                base_sha="base-commit",
            )
        self.assertTrue(standards.generated)
        self.assertEqual(
            standards.rules.language_conventions["python"]["function_name_convention"],
            "camelCase",
        )
        self.assertEqual(
            standards.rules.language_conventions["python"]["variable_name_convention"],
            "camelCase",
        )
        self.assertEqual(standards.rules.max_line_length, 99)
        self.assertEqual(standards.base_sha, "base-commit")
        self.assertEqual(len(standards.evidence["files_sampled"]), 3)

    def test_reinference_updates_generated_rules_but_preserves_user_overrides(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generate_standards(
                "owner/repository",
                "main",
                output_dir,
                inferred_rules=DEFAULT_RULES,
                evidence={"files_sampled": []},
                base_sha="old-base",
            )
            json_path = output_dir / ".ai-review" / "coding-standards.json"
            edited_rules = json.loads(json_path.read_text(encoding="utf-8"))
            edited_rules["require_final_newline"] = False
            json_path.write_text(json.dumps(edited_rules), encoding="utf-8")

            updated_rules = dict(DEFAULT_RULES)
            updated_rules["function_name_convention"] = "camelCase"
            _, rules_text, _ = generate_standards(
                "owner/repository",
                "main",
                output_dir,
                inferred_rules=updated_rules,
                evidence={"files_sampled": ["src/example.py"]},
                base_sha="new-base",
            )

        rules = json.loads(rules_text)
        self.assertFalse(rules["require_final_newline"])
        self.assertEqual(rules["function_name_convention"], "camelCase")


if __name__ == "__main__":
    unittest.main()
