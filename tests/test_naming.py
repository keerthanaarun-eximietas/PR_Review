import unittest

from src.analyzers.code_quality_analyzer import analyze_hardcoded_secrets, redact_secrets
from src.analyzers.naming_analyzer import (
    analyze_function_names,
    analyze_naming,
    analyze_variable_names,
)
from src.models import ChangedFile
from src.standards.standards_parser import DEFAULT_RULES, CodingStandards


class NamingAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.standards = CodingStandards(**DEFAULT_RULES)

    def test_accepts_lower_snake_case_and_exempt_names(self):
        files = [
            ChangedFile("src/good_name.py", "added"),
            ChangedFile("README.md", "modified"),
        ]
        result = analyze_naming(files, self.standards)
        self.assertEqual(result.status, "pass")

    def test_reports_names_outside_convention(self):
        result = analyze_naming([ChangedFile("src/Bad-Name.py", "added")], self.standards)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.findings[0].file, "src/Bad-Name.py")

    def test_checks_python_function_and_variable_names(self):
        source = (
            "def BadFunction(badArgument):\n"
            "    badVariable = badArgument\n"
            "    return badVariable\n"
        )
        changed_file = ChangedFile("src/sample.py", "modified", content=source)
        function_result = analyze_function_names([changed_file], self.standards)
        variable_result = analyze_variable_names([changed_file], self.standards)
        self.assertEqual(function_result.status, "fail")
        self.assertIn("BadFunction", function_result.findings[0].message)
        self.assertEqual(variable_result.status, "fail")
        self.assertEqual(
            {finding.message.split("'")[1] for finding in variable_result.findings},
            {"badArgument", "badVariable"},
        )

    def test_checks_javascript_function_and_variable_declarations(self):
        changed_file = ChangedFile(
            "src/example.js",
            "modified",
            content="function BadFunction() {}\nconst badVariable = () => {};\n",
        )
        function_result = analyze_function_names([changed_file], self.standards)
        variable_result = analyze_variable_names([changed_file], self.standards)
        self.assertEqual(function_result.status, "fail")
        self.assertEqual(variable_result.status, "fail")

    def test_uses_language_specific_inferred_name_conventions(self):
        rules = dict(DEFAULT_RULES)
        rules["language_conventions"] = {
            "python": {
                "function_name_convention": "camelCase",
                "variable_name_convention": "camelCase",
            }
        }
        standards = CodingStandards(**rules)
        changed_file = ChangedFile(
            "src/example.py",
            "modified",
            content="def fetchUser():\n    userName = 1\n    return userName\n",
        )
        self.assertEqual(analyze_function_names([changed_file], standards).status, "pass")
        self.assertEqual(analyze_variable_names([changed_file], standards).status, "pass")

    def test_secret_check_reports_without_disclosing_value(self):
        result = analyze_hardcoded_secrets(
            [ChangedFile("settings.py", "modified", content="password = 'very-secret-value'")]
        )
        self.assertEqual(result.status, "fail")
        self.assertNotIn("very-secret-value", result.findings[0].message)
        self.assertNotIn("private-material", redact_secrets(
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----"
        ))

    def test_detects_camel_case_git_token_without_exposing_value(self):
        source = 'gitToken = "git_0123456789abcdef0123456789abcdef"'
        result = analyze_hardcoded_secrets(
            [ChangedFile("settings.py", "modified", content=source)]
        )
        self.assertEqual(result.status, "fail")
        self.assertEqual(len(result.findings), 1)
        self.assertNotIn("0123456789", result.findings[0].message)
        self.assertNotIn("0123456789", redact_secrets(source))


if __name__ == "__main__":
    unittest.main()
