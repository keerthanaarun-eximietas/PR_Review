import json
from pathlib import Path
from typing import Any
from datetime import datetime

from src.models import CheckResult, PullRequest
from src.reporting.markdown_formatter import format_markdown


def overall_status(checks: list[CheckResult]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status in {"error", "skipped"} for check in checks):
        return "incomplete"
    return "pass"


def build_report(
    repo: str,
    pull_request: PullRequest,
    standards_source: str,
    checks: list[CheckResult],
    *,
    standards_generated: bool = False,
    standards_evidence: dict[str, Any] | None = None,
    standards_base_sha: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "repository": repo,
        "pull_request": {
            "number": pull_request.number,
            "title": pull_request.title,
            "url": pull_request.url,
            "base_ref": pull_request.base_ref,
            "head_ref": pull_request.head_ref,
            "head_sha": pull_request.head_sha,
        },
        "standards": {
            "source": standards_source,
            "generated": standards_generated,
            "basis": (
                "base_branch_inference"
                if standards_generated and standards_evidence
                else "generic_defaults"
                if standards_generated
                else "repository_base_branch"
            ),
            "base_sha": standards_base_sha,
            "evidence": standards_evidence,
        },
        "summary": {
            "status": overall_status(checks),
            "checks_total": len(checks),
            "checks_passed": sum(check.status == "pass" for check in checks),
            "checks_failed": sum(check.status == "fail" for check in checks),
            "checks_incomplete": sum(check.status in {"error", "skipped"} for check in checks),
        },
        "checks": [check.to_dict() for check in checks],
    }


def write_reports(
    report: dict[str, Any],
    output_dir: Path,
    pull_request_number: int,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_path = output_dir / f"pr-{pull_request_number}-review-{timestamp}.json"
    markdown_path = output_dir / f"pr-{pull_request_number}-review-{timestamp}.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(format_markdown(report), encoding="utf-8")
    return json_path, markdown_path
