import hashlib
import json
import re
from typing import Any

from src.github.pr_extractor import GitHubClient, GitHubError, _decode_json
from src.models import CheckResult, ChangedFile, Finding, PullRequest

FINDING_MARKER_PREFIX = "<!-- ai-pr-standardization-finding:"
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _diff_right_side_lines(patch: str) -> set[int]:
    """Return new-file line numbers represented in a unified diff."""
    right_side_lines: set[int] = set()
    new_line: int | None = None
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = HUNK_HEADER.match(line)
            new_line = int(match.group(1)) if match else None
            continue
        if new_line is None or line.startswith("\\"):
            continue
        if line.startswith("+"):
            right_side_lines.add(new_line)
            new_line += 1
        elif line.startswith(" "):
            right_side_lines.add(new_line)
            new_line += 1
    return right_side_lines


def _finding_marker(check_id: str, finding: Finding) -> str:
    identity = json.dumps(
        [check_id, finding.file, finding.line, finding.message],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{FINDING_MARKER_PREFIX}{digest} -->"


def _finding_comment_body(check_id: str, finding: Finding) -> str:
    sections = [
        _finding_marker(check_id, finding),
        f"**{finding.severity.upper()} — {check_id}**",
        finding.message,
    ]
    if finding.reasoning:
        sections.extend(["**Reasoning:**", finding.reasoning])
    if finding.potential_solution:
        sections.extend(["**Potential solution:**", finding.potential_solution])
    return "\n\n".join(sections)


def post_inline_finding_comments(
    client: GitHubClient,
    pull_request: PullRequest,
    checks: list[CheckResult],
    changed_files: list[ChangedFile],
) -> tuple[int, int]:
    """Post or update one resolvable PR review thread per diff-anchored finding.

    Returns the number of inline comments created/updated and findings that could not be
    anchored to a line represented in the PR diff.
    """
    diff_lines = {
        changed_file.path: _diff_right_side_lines(changed_file.patch)
        for changed_file in changed_files
        if changed_file.status != "removed" and changed_file.patch
    }
    inline_findings = [
        (check.check_id, finding)
        for check in checks
        for finding in check.findings
        if finding.line is not None
        and finding.line in diff_lines.get(finding.file, set())
    ]
    total_findings = sum(len(check.findings) for check in checks)
    skipped = total_findings - len(inline_findings)
    if not inline_findings:
        return 0, skipped

    comments_url = pull_request.review_comments_url
    if not comments_url:
        raise GitHubError("GitHub did not provide the pull request review-comments URL.")
    comments: list[dict[str, Any]] = []
    url = comments_url + "?per_page=100"
    while url:
        response = client.request(url)
        payload = _decode_json(response.body)
        if not isinstance(payload, list):
            raise GitHubError("GitHub returned an invalid pull request review comments response.")
        comments.extend(payload)
        link_header = response.headers.get("Link", "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        url = match.group(1) if match else ""

    existing_by_marker = {
        marker.group(0): comment
        for comment in comments
        if isinstance(comment, dict) and isinstance(comment.get("body"), str)
        for marker in [
            re.search(
                rf"{re.escape(FINDING_MARKER_PREFIX)}[0-9a-f]+ -->",
                comment["body"],
            )
        ]
        if marker is not None
    }

    for check_id, finding in inline_findings:
        marker = _finding_marker(check_id, finding)
        body = _finding_comment_body(check_id, finding)
        existing = existing_by_marker.get(marker)
        if existing is None:
            client.request(
                comments_url,
                method="POST",
                payload={
                    "body": body,
                    "commit_id": pull_request.head_sha,
                    "path": finding.file,
                    "line": finding.line,
                    "side": "RIGHT",
                },
            )
        else:
            client.request(
                existing["url"],
                method="PATCH",
                payload={"body": body},
            )
    return len(inline_findings), skipped
