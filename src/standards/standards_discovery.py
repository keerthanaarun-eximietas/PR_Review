from pathlib import Path

from src.config.settings import Settings
from src.github.pr_extractor import GitHubClient, GitHubError
from src.standards.standards_generator import generate_standards
from src.standards.standards_inference import infer_base_branch_standards
from src.standards.standards_parser import StandardsDocument, parse_standards


def discover_standards(
    client: GitHubClient,
    repo: str,
    base_ref: str,
    settings: Settings,
    base_sha: str | None = None,
) -> StandardsDocument:
    """Read base-branch standards, otherwise infer them from that branch's source."""
    base_revision = base_sha or base_ref
    candidates = settings.guidelines_candidates
    for path in candidates:
        try:
            text = client.get_file(repo, path, base_revision)
        except GitHubError as error:
            if "HTTP 404" in str(error):
                continue
            raise

        companion_json = None
        source_path = path
        if path.lower().endswith(".md"):
            try:
                companion_json = client.get_file(
                    repo,
                    ".ai-review/coding-standards.json",
                    base_revision,
                )
            except GitHubError as error:
                if "HTTP 404" not in str(error):
                    raise
        elif path.lower().endswith(".json"):
            source_path = path
        return parse_standards(
            text,
            f"{source_path}@{base_ref}",
            json_text=companion_json,
            base_sha=base_sha,
        )

    inferred_rules, evidence = infer_base_branch_standards(
        client,
        repo,
        base_revision,
    )
    evidence["base_ref"] = base_ref
    evidence["base_sha"] = base_sha
    markdown, json_text, source = generate_standards(
        repo,
        base_ref,
        settings.output_dir,
        inferred_rules=inferred_rules,
        evidence=evidence,
        base_sha=base_sha,
    )
    return parse_standards(
        markdown,
        source,
        json_text=json_text,
        generated=True,
        evidence=evidence,
        base_sha=base_sha,
    )
