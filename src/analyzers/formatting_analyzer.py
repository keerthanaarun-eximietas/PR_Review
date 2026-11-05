from src.models import ChangedFile, CheckResult, Finding
from src.standards.standards_parser import CodingStandards


def analyze_formatting(files: list[ChangedFile], standards: CodingStandards) -> CheckResult:
    findings: list[Finding] = []
    for changed_file in files:
        if changed_file.status == "removed" or changed_file.content is None:
            continue
        source = changed_file.content
        lines = source.splitlines()
        if source and standards.require_final_newline and not source.endswith(("\n", "\r")):
            findings.append(
                Finding(
                    file=changed_file.path,
                    line=len(lines),
                    message="File does not end with a newline.",
                    severity="low",
                    reasoning="A final newline is required by the configured formatting rules.",
                )
            )
        for line_number, line in enumerate(lines, start=1):
            if line.rstrip(" \t") != line:
                findings.append(
                    Finding(
                        file=changed_file.path,
                        line=line_number,
                        message="Line has trailing whitespace.",
                        severity="low",
                        reasoning="Trailing whitespace creates noisy diffs and inconsistent formatting.",
                    )
                )
            if len(line) > standards.max_line_length:
                findings.append(
                    Finding(
                        file=changed_file.path,
                        line=line_number,
                        message=f"Line has {len(line)} characters; limit is {standards.max_line_length}.",
                        severity="low",
                        reasoning="The configured maximum line length improves readability.",
                    )
                )
    return CheckResult(
        check_id="formatting",
        category="formatting",
        status="fail" if findings else "pass",
        summary=f"{len(findings)} issue(s) found." if findings else "Changed files meet the configured basic formatting rules.",
        findings=findings,
    )

