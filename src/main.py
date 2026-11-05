import json
import sys
from dataclasses import asdict

from src.ai.ai_reviewer import review_with_ai
from src.ai.solution_generator import generate_potential_solutions
from src.config.settings import Settings
from src.github.pr_commenter import post_inline_finding_comments
from src.github.pr_extractor import GitHubClient, GitHubError
from src.github.pr_listener import parse_arguments
from src.reporting.report_generator import build_report, overall_status, write_reports
from src.standards.standards_discovery import discover_standards
from src.standards.standards_parser import StandardsError
from src.analyzers.file_analyzer import analyze_files


def run() -> int:
    try:
        arguments = parse_arguments()
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    if not arguments.repo:
        print("Error: provide --repo or set GITHUB_REPOSITORY.", file=sys.stderr)
        return 2
    if not arguments.pr or arguments.pr < 1:
        print("Error: provide a positive --pr number or a pull_request event payload.", file=sys.stderr)
        return 2

    try:
        settings = Settings.from_environment(arguments.output)
    except (OSError, ValueError) as error:
        print(f"Error loading environment settings: {error}", file=sys.stderr)
        return 2
    client = GitHubClient(settings)
    try:
        pull_request = client.get_pull_request(arguments.repo, arguments.pr)
        standards = discover_standards(
            client,
            arguments.repo,
            pull_request.base_ref,
            settings,
            base_sha=pull_request.base_sha,
        )
        changed_files = client.get_changed_files(arguments.repo, pull_request)
    except (GitHubError, StandardsError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    checks = analyze_files(changed_files, standards.rules)
    standards_context = (
        standards.prose
        + "\n\nMachine-readable standards applied by deterministic checks:\n"
        + json.dumps(asdict(standards.rules), indent=2)
    )
    ai_check = review_with_ai(
        settings,
        standards_context,
        changed_files,
        allow_upload=arguments.allow_ai_upload,
        deterministic_checks=checks,
    )
    checks.append(ai_check)
    solution_status = generate_potential_solutions(
        settings,
        checks,
        changed_files,
        standards_context,
        allow_upload=arguments.allow_ai_upload,
    )
    if solution_status:
        ai_check.details = (
            f"{ai_check.details}\n\n{solution_status}" if ai_check.details else solution_status
        )
    report = build_report(
        arguments.repo,
        pull_request,
        standards.source,
        checks,
        standards_generated=standards.generated,
        standards_evidence=standards.evidence,
        standards_base_sha=standards.base_sha,
    )
    try:
        json_path, markdown_path = write_reports(
            report,
            settings.output_dir,
            pull_request.number,
        )
    except OSError as error:
        print(f"Error writing reports: {error}", file=sys.stderr)
        return 2

    if arguments.comment:
        try:
            inline_count, unanchored_count = post_inline_finding_comments(
                client,
                pull_request,
                checks,
                changed_files,
            )
        except GitHubError as error:
            print(f"Error posting pull request comment: {error}", file=sys.stderr)
            return 2
        print(
            f"Inline finding comments: {inline_count} created or updated; "
            f"{unanchored_count} finding(s) were not posted inline because "
            "they do not map to a line in the PR diff."
        )

    print(f"Review result: {overall_status(checks).upper()}")
    print(f"JSON report: {json_path.resolve()}")
    print(f"Markdown report: {markdown_path.resolve()}")
    if standards.source.endswith("coding-standards.md"):
        print(f"Standards source: {standards.source}")
    return 0 if overall_status(checks) == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
