import unittest

from src.analyzers.ast_analyzer import _function_spans, analyze_function_length
from src.analyzers.file_analyzer import analyze_files
from src.models import ChangedFile
from src.standards.standards_parser import CodingStandards, DEFAULT_RULES


class FileAnalyzerTests(unittest.TestCase):
    def setUp(self):
        rules = dict(DEFAULT_RULES)
        rules.update(max_file_lines=3, max_function_lines=2, max_line_length=20)
        self.standards = CodingStandards(**rules)

    def test_reports_file_and_function_length(self):
        content = "def long_function():\n    first = 1\n    second = 2\n    return first + second\n"
        results = {
            result.check_id: result
            for result in analyze_files(
                [ChangedFile("sample.py", "modified", content=content)],
                self.standards,
            )
        }
        self.assertEqual(results["file_length"].status, "fail")
        self.assertEqual(results["function_length"].status, "fail")

    def test_function_scan_marks_unsupported_languages_skipped(self):
        result = analyze_function_length(
            [ChangedFile("script.rb", "modified", content="def example\n  1\nend\n")],
            self.standards,
        )
        self.assertEqual(result.status, "skipped")
        self.assertIn("script.rb", result.details)

    def test_function_scan_ignores_non_source_changed_files(self):
        result = analyze_function_length(
            [
                ChangedFile(".gitignore", "modified", content="*.pyc\n"),
                ChangedFile("README.md", "modified", content="# Project\n"),
                ChangedFile("sample.py", "modified", content="def example():\n    return 1\n"),
            ],
            self.standards,
        )
        self.assertEqual(result.status, "pass")
        self.assertIsNone(result.details)

    def test_arrow_expression_does_not_consume_later_function(self):
        source = "const value = (input) => input;\nfunction later() {\n  return 1;\n}\n"
        spans, supported = _function_spans("example.js", source)
        self.assertTrue(supported)
        self.assertEqual(spans, [("later", 2, 4)])


if __name__ == "__main__":
    unittest.main()
