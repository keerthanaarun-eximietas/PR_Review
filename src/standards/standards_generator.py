import json
from pathlib import Path
from typing import Any

from src.standards.standards_parser import DEFAULT_RULES, StandardsError


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StandardsError(f"Could not read generated standards file {path}: {error}") from error
    if not isinstance(value, dict):
        raise StandardsError(f"Generated standards file must contain a JSON object: {path}")
    return value


def _user_overrides(
    current: dict[str, Any],
    previous_generated: dict[str, Any],
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in current.items():
        previous = previous_generated.get(key)
        if isinstance(value, dict) and isinstance(previous, dict):
            nested = _user_overrides(value, previous)
            if nested:
                overrides[key] = nested
        elif key not in previous_generated or value != previous:
            overrides[key] = value
    return overrides


def _merge_rules(inferred: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(inferred)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_rules(merged[key], value)
        else:
            merged[key] = value
    return merged


def generate_standards(
    repo: str,
    base_ref: str,
    output_dir: Path,
    *,
    inferred_rules: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    base_sha: str | None = None,
) -> tuple[str, str, str]:
    """Persist inferred rules and provenance without replacing user-edited rules."""
    standards_dir = output_dir / ".ai-review"
    standards_dir.mkdir(parents=True, exist_ok=True)
    json_path = standards_dir / "coding-standards.json"
    markdown_path = standards_dir / "coding-standards.md"
    metadata_path = standards_dir / "standards-metadata.json"
    inferred = dict(inferred_rules or DEFAULT_RULES)

    metadata = _read_json(metadata_path) if metadata_path.exists() else {}
    current_rules = _read_json(json_path) if json_path.exists() else {}
    previous_generated = metadata.get("generated_rules")
    if not isinstance(previous_generated, dict):
        previous_generated = DEFAULT_RULES
    overrides = _user_overrides(current_rules, previous_generated)
    effective_rules = _merge_rules(inferred, overrides)
    rules_text = json.dumps(effective_rules, indent=2)
    language_rules = effective_rules.get("language_conventions", {})
    language_summary = "\n".join(
        f"- {language}: functions `{rules.get('function_name_convention', effective_rules['function_name_convention'])}`, "
        f"variables `{rules.get('variable_name_convention', effective_rules['variable_name_convention'])}`"
        for language, rules in sorted(language_rules.items())
    )
    if not language_summary:
        language_summary = (
            f"- Functions: `{effective_rules['function_name_convention']}`\n"
            f"- Variables: `{effective_rules['variable_name_convention']}`"
        )

    markdown = f"""# Generated PR Review Guidelines - Base-Branch Inference

These guidelines were generated for `{repo}` from base branch `{base_ref}` because no recognized
standards document was found. Rules are inferred from repository configuration and a bounded sample
of source files; evidence and confidence are recorded in `standards-metadata.json`.
Rules with insufficient evidence retain safe defaults. Review these inferred rules before treating
them as repository policy.

## Review expectations

- Keep changes focused and follow existing project conventions.
- Prefer small, clear functions and avoid duplicating existing logic.
- Handle errors consistently and avoid exposing credentials or sensitive data.
- Keep formatting clean and document behavior changes where appropriate.

## Automated rules

The exact effective rule configuration is stored in the adjacent `coding-standards.json` file.

### Effective automated rules

- Filenames: `{effective_rules['filename_convention']}`
- Maximum file length: {effective_rules['max_file_lines']} lines
- Maximum function length: {effective_rules['max_function_lines']} lines
- Maximum line length: {effective_rules['max_line_length']} characters
- Final newline required: `{effective_rules['require_final_newline']}`
{language_summary}
"""
    markdown_exists = markdown_path.exists()
    existing_markdown = markdown_path.read_text(encoding="utf-8") if markdown_exists else None
    previous_generated_markdown = metadata.get("generated_markdown")
    legacy_generated_markdown = (
        metadata.get("generation_method") == "generic_defaults"
        and existing_markdown is not None
        and "does not inspect source files to infer repository-specific naming patterns"
        in existing_markdown
    )
    if not markdown_exists or legacy_generated_markdown or (
        isinstance(previous_generated_markdown, str)
        and existing_markdown == previous_generated_markdown
    ):
        existing_markdown = markdown
        markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(rules_text + "\n", encoding="utf-8")

    metadata.update(
        {
            "schema_version": "1.0",
            "source": "generated",
            "generated": True,
            "generation_method": "base_branch_inference" if evidence else "generic_defaults",
            "repository_conventions_inferred": bool(evidence),
            "repository": repo,
            "base_ref": base_ref,
            "base_sha": base_sha,
            "generated_rules": inferred,
            "evidence": evidence or {},
        }
    )
    if not markdown_exists or isinstance(previous_generated_markdown, str):
        metadata["generated_markdown"] = markdown
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return existing_markdown or markdown, rules_text, str(markdown_path)
