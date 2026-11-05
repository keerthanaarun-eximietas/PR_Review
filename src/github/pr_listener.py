import argparse
import json
import os
from pathlib import Path


def _event_pull_request_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read GitHub event payload: {error}") from error
    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict) and isinstance(pull_request.get("number"), int):
        return pull_request["number"]
    number = event.get("number")
    return number if isinstance(number, int) else None


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ai-pr-review",
        description="Review a GitHub pull request and write JSON and Markdown reports.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub repository in owner/name format (defaults to GITHUB_REPOSITORY).",
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=_event_pull_request_number(),
        help="Pull request number (defaults to the GitHub Actions event payload).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("PR_REVIEW_OUTPUT", "pr-review-reports")),
        help="Directory for generated reports.",
    )
    parser.add_argument(
        "--allow-ai-upload",
        action="store_true",
        help="Allow the redacted pull request diff to be sent to the configured AI endpoint.",
    )
    parser.add_argument(
        "--comment",
        action="store_true",
        default=True,
        help="Post or update inline finding comments on the pull request (default).",
    )
    parser.add_argument(
        "--no-comment",
        dest="comment",
        action="store_false",
        help="Generate reports without posting inline comments to the pull request.",
    )
    return parser.parse_args()
