import json
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_RULES: dict[str, Any] = {
    "filename_convention": "lower_snake_case",
    "function_name_convention": "snake_case",
    "variable_name_convention": "snake_case",
    "max_file_lines": 500,
    "max_function_lines": 80,
    "max_line_length": 120,
    "require_final_newline": True,
    "filename_exemptions": ["README.md", "LICENSE", "CHANGELOG.md"],
    "language_conventions": {},
}


class StandardsError(ValueError):
    """Raised when a coding-standards document is invalid."""


@dataclass(frozen=True)
class CodingStandards:
    filename_convention: str
    function_name_convention: str
    variable_name_convention: str
    max_file_lines: int
    max_function_lines: int
    max_line_length: int
    require_final_newline: bool
    filename_exemptions: list[str]
    language_conventions: dict[str, dict[str, str]]


@dataclass(frozen=True)
class StandardsDocument:
    prose: str
    rules: CodingStandards
    source: str
    generated: bool = False
    evidence: dict[str, Any] | None = None
    base_sha: str | None = None


def _extract_rules(markdown: str) -> dict[str, Any] | None:
    match = re.search(
        r"```json\s+pr-review-rules\s*\r?\n(.*?)```",
        markdown,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise StandardsError(
            f"Invalid pr-review-rules JSON: {error.msg} (line {error.lineno})."
        ) from error
    if not isinstance(payload, dict):
        raise StandardsError("pr-review-rules must contain a JSON object.")
    return payload


def _validate_rules(supplied: dict[str, Any] | None) -> CodingStandards:
    rules = dict(DEFAULT_RULES)
    if supplied is not None:
        unknown = set(supplied) - set(rules)
        if unknown:
            raise StandardsError(f"Unknown rule key(s): {', '.join(sorted(unknown))}.")
        rules.update(supplied)

    convention = rules["filename_convention"]
    if not isinstance(convention, str):
        raise StandardsError("filename_convention must be a string.")
    if convention not in {"lower_snake_case", "kebab-case", "camelCase", "PascalCase", "any"}:
        raise StandardsError(
            "filename_convention must be lower_snake_case, kebab-case, camelCase, PascalCase, or any."
        )
    name_conventions = {"snake_case", "camelCase", "PascalCase", "any"}
    for key in ("function_name_convention", "variable_name_convention"):
        value = rules[key]
        if not isinstance(value, str) or value not in name_conventions:
            raise StandardsError(
                f"{key} must be snake_case, camelCase, PascalCase, or any."
            )
    for key in ("max_file_lines", "max_function_lines", "max_line_length"):
        if type(rules[key]) is not int or rules[key] < 1:
            raise StandardsError(f"{key} must be a positive integer.")
    if type(rules["require_final_newline"]) is not bool:
        raise StandardsError("require_final_newline must be true or false.")
    if not isinstance(rules["filename_exemptions"], list) or not all(
        isinstance(item, str) for item in rules["filename_exemptions"]
    ):
        raise StandardsError("filename_exemptions must be a list of strings.")
    language_conventions = rules["language_conventions"]
    if not isinstance(language_conventions, dict):
        raise StandardsError("language_conventions must be an object.")
    for language, conventions in language_conventions.items():
        if not isinstance(language, str) or not isinstance(conventions, dict):
            raise StandardsError("language_conventions must map language names to objects.")
        unknown = set(conventions) - {
            "function_name_convention",
            "variable_name_convention",
        }
        if unknown:
            raise StandardsError(
                f"Unknown naming rule(s) for {language}: {', '.join(sorted(unknown))}."
            )
        for key, value in conventions.items():
            if not isinstance(value, str) or value not in name_conventions:
                raise StandardsError(
                    f"language_conventions.{language}.{key} must be snake_case, "
                    "camelCase, PascalCase, or any."
                )
    return CodingStandards(**rules)


def parse_standards(
    text: str,
    source: str,
    *,
    json_text: str | None = None,
    generated: bool = False,
    evidence: dict[str, Any] | None = None,
    base_sha: str | None = None,
) -> StandardsDocument:
    """Parse markdown guidelines and an optional companion JSON rule file."""
    extracted = _extract_rules(text)
    if json_text is not None:
        try:
            json_rules = json.loads(json_text)
        except json.JSONDecodeError as error:
            raise StandardsError(
                f"Invalid coding-standards.json: {error.msg} (line {error.lineno})."
            ) from error
        if not isinstance(json_rules, dict):
            raise StandardsError("coding-standards.json must contain a JSON object.")
        if extracted:
            extracted.update(json_rules)
        else:
            extracted = json_rules
    elif source.partition("@")[0].lower().endswith(".json"):
        try:
            json_rules = json.loads(text)
        except json.JSONDecodeError as error:
            raise StandardsError(
                f"Invalid coding standards JSON: {error.msg} (line {error.lineno})."
            ) from error
        if not isinstance(json_rules, dict):
            raise StandardsError("Coding standards JSON must contain an object.")
        extracted = json_rules
    return StandardsDocument(
        prose=text,
        rules=_validate_rules(extracted),
        source=source,
        generated=generated,
        evidence=evidence,
        base_sha=base_sha,
    )
