from src.analyzers.ast_analyzer import analyze_function_length
from src.analyzers.code_quality_analyzer import analyze_hardcoded_secrets
from src.analyzers.formatting_analyzer import analyze_formatting
from src.analyzers.naming_analyzer import (
    analyze_function_names,
    analyze_naming,
    analyze_variable_names,
)
from src.models import ChangedFile, CheckResult, Finding
from src.standards.standards_parser import CodingStandards


def analyze_files(
    files: list[ChangedFile],
    standards: CodingStandards,
) -> list[CheckResult]:
    """Run all deterministic checks against changed file contents."""
    file_length_findings = []
    for changed_file in files:
        if changed_file.status == "removed" or changed_file.content is None:
            continue
        line_count = len(changed_file.content.splitlines())
        if line_count > standards.max_file_lines:
            file_length_findings.append(
                Finding(
                    file=changed_file.path,
                    message=f"File has {line_count} lines; limit is {standards.max_file_lines}.",
                    severity="medium",
                    reasoning="Large files are harder to navigate and maintain.",
                )
            )
    file_length = CheckResult(
        check_id="file_length",
        category="size",
        status="fail" if file_length_findings else "pass",
        summary=(
            f"{len(file_length_findings)} issue(s) found."
            if file_length_findings
            else "Changed files are within the configured line limit."
        ),
        findings=file_length_findings,
    )
    return [
        analyze_naming(files, standards),
        analyze_function_names(files, standards),
        analyze_variable_names(files, standards),
        file_length,
        analyze_function_length(files, standards),
        analyze_formatting(files, standards),
        analyze_hardcoded_secrets(files),
    ]
