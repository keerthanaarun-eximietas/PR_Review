from typing import Any


def format_markdown(report: dict[str, Any]) -> str:
    pull_request = report["pull_request"]
    summary = report["summary"]
    lines = [
        f"# PR Review: {report['repository']}#{pull_request['number']}",
        "",
        f"**Result: {summary['status'].upper()}**",
        "",
        f"- **Pull request:** [{pull_request['title']}]({pull_request['url']})",
        f"- **Base:** `{pull_request['base_ref']}`",
        f"- **Head:** `{pull_request['head_ref']}` (`{pull_request['head_sha'][:12]}`)",
        f"- **Standards:** `{report['standards']['source']}`",
        f"- **Checks:** {summary['checks_passed']} passed, {summary['checks_failed']} failed, "
        f"{summary['checks_incomplete']} incomplete",
        "",
        "## Validation results",
        "",
        "| Check | Category | Result | Summary |",
        "|---|---|---|---|",
    ]
    if report["standards"].get("basis") == "base_branch_inference":
        evidence = report["standards"].get("evidence") or {}
        sampled_files = evidence.get("files_sampled", [])
        standards_summary = [
            "Standards were inferred from the PR base branch because no recognized guidelines "
            "file was found.",
            f"Base commit: `{report['standards'].get('base_sha') or evidence.get('base_sha') or 'unknown'}`.",
            f"Source files sampled: {len(sampled_files)}.",
        ]
        if evidence.get("warnings"):
            standards_summary.append("Inference notes: " + " ".join(evidence["warnings"]))
        index = lines.index("## Validation results")
        lines[index:index] = [
            "## Standards inference",
            "",
            *standards_summary,
            "",
        ]
    for check in report["checks"]:
        safe_summary = check["summary"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['category']} | **{check['status'].upper()}** "
            f"| {safe_summary} |"
        )
    for check in report["checks"]:
        lines.extend(["", f"### {check['check_id']}", "", check["summary"]])
        if check.get("details"):
            lines.extend(["", check["details"]])
        if check["findings"]:
            for finding in check["findings"]:
                location = f"`{finding['file']}`"
                if finding.get("line") is not None:
                    location += f":{finding['line']}"
                lines.extend(
                    [
                        "",
                        f"- **{finding['severity'].upper()}** — {location}: {finding['message']}",
                        f"  - Reasoning: {finding['reasoning'] or 'No additional reasoning provided.'}",
                    ]
                )
                if finding.get("potential_solution"):
                    lines.append(f"  - Potential solution: {finding['potential_solution']}")
        elif check["status"] == "pass":
            lines.extend(["", "No findings."])
    lines.append("")
    return "\n".join(lines)
