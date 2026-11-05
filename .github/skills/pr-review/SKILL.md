---
name: pr-review
description: "Review GitHub pull requests by number, apply repository guidelines, run deterministic code checks and an optional AI review, and produce JSON and Markdown reports."
argument-hint: "owner/repository and pull request number"
---

# Pull Request Review

Use this workflow when asked to review a GitHub pull request by number or URL.

1. Confirm the repository as `owner/name` and the pull request number.
2. From the project root, run `python -m src.main --repo owner/name --pr NUMBER --output pr-review-reports`.
3. The CLI reads coding standards from the PR base branch, checks changed file content at the PR head, and writes JSON and Markdown reports. If no recognized standards file exists, it writes starter files under `pr-review-reports/.ai-review/`.
4. The CLI posts or updates inline comments for findings by default; use `--no-comment` to disable them.
5. To run AI checks, configure `PR_REVIEW_AI_ENDPOINT`, `PR_REVIEW_AI_API_KEY`, and `PR_REVIEW_AI_MODEL`, then explicitly pass `--allow-ai-upload`. Review the generated reports and disclose skipped/error checks; do not describe an incomplete review as passing.

See the [CLI documentation](../../../README.md) for rule configuration, privacy, and report semantics.
