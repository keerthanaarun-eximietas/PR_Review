import ast
import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from src.github.pr_extractor import GitHubClient, GitHubError
from src.standards.standards_parser import DEFAULT_RULES

MAX_SAMPLE_FILES = 40
MAX_FILE_BYTES = 100_000
MAX_TOTAL_SAMPLE_BYTES = 1_000_000
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
}
EXTENSION_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}
CONFIG_PATHS = (
    ".editorconfig",
    "pyproject.toml",
    "ruff.toml",
    ".ruff.toml",
    ".prettierrc",
    ".prettierrc.json",
    "prettier.config.json",
)

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
CAMEL_CASE = re.compile(r"^[a-z][A-Za-z0-9]*$")
PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _classify_name(name: str) -> str | None:
    if name.startswith("__") and name.endswith("__"):
        return None
    if name.isupper() or name.startswith("_") or not name:
        return None
    if SNAKE_CASE.fullmatch(name):
        return "snake_case"
    if CAMEL_CASE.fullmatch(name):
        return "camelCase"
    if PASCAL_CASE.fullmatch(name):
        return "PascalCase"
    return None


def _classify_filename(stem: str) -> str | None:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", stem):
        return "kebab-case"
    return _classify_name(stem)


def _dominant_convention(counts: Counter[str], minimum: int = 3) -> tuple[str | None, dict[str, Any]]:
    total = sum(counts.values())
    if total < minimum:
        return None, {"observations": total, "counts": dict(counts), "confidence": "low"}
    convention, count = counts.most_common(1)[0]
    ratio = count / total
    confidence = "high" if ratio >= 0.85 else "medium" if ratio >= 0.65 else "low"
    if ratio < 0.60:
        return None, {
            "observations": total,
            "counts": dict(counts),
            "confidence": confidence,
            "reason": "No convention reached the 60% consistency threshold.",
        }
    return convention, {
        "observations": total,
        "counts": dict(counts),
        "confidence": confidence,
    }


def _python_names(source: str) -> tuple[list[str], list[str], list[int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], [], []
    functions: list[str] = []
    variables: list[str] = []
    function_lengths: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            variables.extend(argument.arg for argument in node.args.args)
            variables.extend(argument.arg for argument in node.args.posonlyargs)
            variables.extend(argument.arg for argument in node.args.kwonlyargs)
            if node.args.vararg:
                variables.append(node.args.vararg.arg)
            if node.args.kwarg:
                variables.append(node.args.kwarg.arg)
            if hasattr(node, "end_lineno"):
                function_lengths.append(node.end_lineno - node.lineno + 1)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            variables.append(node.id)
    return functions, variables, function_lengths


JS_FUNCTION = re.compile(
    r"^\s*(?:(?:export|default)\s+)*(?:async\s+)?function\s*\*?\s+([\w$]+)"
)
JS_DECLARATION = re.compile(
    r"^\s*(?:(?:export|default)\s+)*(?:const|let|var)\s+([\w$]+)"
)
JS_ARROW = re.compile(
    r"^\s*(?:(?:export|default)\s+)*(?:const|let|var)\s+([\w$]+)\s*=.*=>"
)


def _javascript_names(source: str) -> tuple[list[str], list[str]]:
    functions: list[str] = []
    variables: list[str] = []
    for line in source.splitlines():
        function_match = JS_FUNCTION.search(line)
        declaration_match = JS_DECLARATION.search(line)
        arrow_match = JS_ARROW.search(line)
        if function_match:
            functions.append(function_match.group(1))
        if declaration_match:
            variables.append(declaration_match.group(1))
        if arrow_match:
            functions.append(arrow_match.group(1))
    return functions, variables


def _infer_line_length(configs: dict[str, str]) -> tuple[int, dict[str, Any] | None]:
    editor_config = configs.get(".editorconfig", "")
    match = re.search(r"(?mi)^\s*max_line_length\s*=\s*(\d+)\s*$", editor_config)
    if match:
        return int(match.group(1)), {
            "source": ".editorconfig",
            "value": int(match.group(1)),
            "confidence": "high",
        }

    for path in ("pyproject.toml", "ruff.toml", ".ruff.toml"):
        text = configs.get(path)
        if not text:
            continue
        section = ""
        for line in text.splitlines():
            section_match = re.match(r"\s*\[([^\]]+)\]\s*$", line)
            if section_match:
                section = section_match.group(1).strip()
                continue
            if path == "pyproject.toml" and section not in {
                "tool.ruff",
                "tool.black",
            }:
                continue
            match = re.match(r"\s*line-length\s*=\s*(\d+)\s*(?:#.*)?$", line)
            if match:
                return int(match.group(1)), {
                    "source": path,
                    "value": int(match.group(1)),
                    "confidence": "high",
                }
    for path in (".prettierrc", ".prettierrc.json", "prettier.config.json"):
        text = configs.get(path, "")
        match = re.search(r"""["']?printWidth["']?\s*:\s*(\d+)""", text)
        if match:
            return int(match.group(1)), {
                "source": path,
                "value": int(match.group(1)),
                "confidence": "high",
            }
    return int(DEFAULT_RULES["max_line_length"]), None


def _rounded_limit(values: list[int], fallback: int, multiplier: float) -> int:
    if len(values) < 3:
        return fallback
    values.sort()
    percentile_index = min(len(values) - 1, int(0.9 * (len(values) - 1)))
    estimated = max(1, round(values[percentile_index] * multiplier))
    rounded = max(10, int(round(estimated / 10) * 10))
    return max(fallback, rounded)


def infer_base_branch_standards(
    client: GitHubClient,
    repo: str,
    base_ref: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Infer conservative standards from bounded source samples and repo tool config."""
    tree = client.list_repository_files(repo, base_ref)
    paths = [str(item.get("path", "")) for item in tree]
    path_sizes = {
        str(item["path"]): item.get("size")
        for item in tree
        if isinstance(item.get("path"), str)
    }
    configs: dict[str, str] = {}
    for path in CONFIG_PATHS:
        if path not in paths:
            continue
        configs[path] = client.get_file(repo, path, base_ref)

    source_paths: list[str] = []
    for path in paths:
        candidate = PurePosixPath(path)
        if any(part.lower() in EXCLUDED_PARTS for part in candidate.parts):
            continue
        if candidate.suffix.lower() not in EXTENSION_LANGUAGE:
            continue
        size = path_sizes.get(path)
        if type(size) is int and size > MAX_FILE_BYTES:
            continue
        source_paths.append(path)
    source_paths.sort()

    selected: list[str] = []
    language_counts: Counter[str] = Counter()
    for path in source_paths:
        language = EXTENSION_LANGUAGE[PurePosixPath(path).suffix.lower()]
        if language_counts[language] >= 15:
            continue
        selected.append(path)
        language_counts[language] += 1
        if len(selected) >= MAX_SAMPLE_FILES:
            break

    defaults = dict(DEFAULT_RULES)
    evidence: dict[str, Any] = {
        "method": "bounded deterministic sample of base-branch source files and tool configuration",
        "base_ref": base_ref,
        "files_available": len(source_paths),
        "files_sampled": [],
        "sample_limits": {
            "max_files": MAX_SAMPLE_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_SAMPLE_BYTES,
        },
        "rules": {},
        "warnings": [],
    }
    language_observations: dict[str, dict[str, Counter[str] | list[int]]] = {}
    file_name_counts: Counter[str] = Counter()
    line_lengths: list[int] = []
    file_lengths: list[int] = []
    total_bytes = 0

    for path in selected:
        if total_bytes >= MAX_TOTAL_SAMPLE_BYTES:
            break
        try:
            source = client.get_file(repo, path, base_ref)
        except GitHubError:
            evidence["warnings"].append(f"Could not read sample file {path}; excluded.")
            continue
        source_bytes = len(source.encode("utf-8"))
        if source_bytes > MAX_FILE_BYTES or total_bytes + source_bytes > MAX_TOTAL_SAMPLE_BYTES:
            evidence["warnings"].append(f"Sample file {path} exceeded the size limit; excluded.")
            continue
        total_bytes += source_bytes
        evidence["files_sampled"].append(path)
        file_lengths.append(len(source.splitlines()))
        language = EXTENSION_LANGUAGE[PurePosixPath(path).suffix.lower()]
        bucket = language_observations.setdefault(
            language,
            {"functions": Counter(), "variables": Counter(), "function_lengths": []},
        )
        stem = PurePosixPath(path).stem
        file_convention = _classify_filename(stem)
        if file_convention:
            file_name_counts[file_convention] += 1

        if language == "python":
            functions, variables, function_lengths = _python_names(source)
            bucket["function_lengths"].extend(function_lengths)
        else:
            functions, variables = _javascript_names(source)
        for name in functions:
            convention = _classify_name(name)
            if convention:
                bucket["functions"][convention] += 1
        for name in variables:
            convention = _classify_name(name)
            if convention:
                bucket["variables"][convention] += 1
        line_lengths.extend(len(line.rstrip()) for line in source.splitlines() if line.strip())

    inferred: dict[str, Any] = defaults
    language_rules: dict[str, dict[str, str]] = {}
    for language, observations in language_observations.items():
        function_convention, function_evidence = _dominant_convention(observations["functions"])
        variable_convention, variable_evidence = _dominant_convention(observations["variables"])
        rule: dict[str, str] = {}
        if function_convention:
            rule["function_name_convention"] = function_convention
        if variable_convention:
            rule["variable_name_convention"] = variable_convention
        if rule:
            language_rules[language] = rule
        evidence["rules"][language] = {
            "function_name_convention": function_evidence,
            "variable_name_convention": variable_evidence,
        }

    if language_rules:
        inferred["language_conventions"] = language_rules
    filename_convention, filename_evidence = _dominant_convention(file_name_counts, minimum=3)
    if filename_convention in {"snake_case", "kebab-case", "camelCase", "PascalCase"}:
        inferred["filename_convention"] = (
            "lower_snake_case" if filename_convention == "snake_case" else filename_convention
        )
    evidence["rules"]["filename_convention"] = filename_evidence

    inferred["max_line_length"], line_config_evidence = _infer_line_length(configs)
    if line_config_evidence:
        evidence["rules"]["max_line_length"] = line_config_evidence
    elif line_lengths:
        evidence["rules"]["observed_line_length"] = {
            "non_empty_lines": len(line_lengths),
            "sampled_90th_percentile": sorted(line_lengths)[int(0.9 * (len(line_lengths) - 1))],
            "confidence": "low",
            "note": "No linter/editor setting found; default limit retained.",
        }

    function_lengths = [
        length
        for observations in language_observations.values()
        for length in observations["function_lengths"]
    ]
    inferred["max_function_lines"] = _rounded_limit(
        function_lengths,
        int(DEFAULT_RULES["max_function_lines"]),
        1.5,
    )
    evidence["rules"]["max_function_lines"] = {
        "python_functions_observed": len(function_lengths),
        "inferred_limit": inferred["max_function_lines"],
        "confidence": "medium" if len(function_lengths) >= 3 else "low",
    }
    inferred["max_file_lines"] = _rounded_limit(
        file_lengths,
        int(DEFAULT_RULES["max_file_lines"]),
        1.5,
    )
    evidence["rules"]["max_file_lines"] = {
        "files_sampled": len(evidence["files_sampled"]),
        "inferred_limit": inferred["max_file_lines"],
        "confidence": "medium" if len(file_lengths) >= 3 else "low",
        "note": (
            "Estimated as 1.5 times the sampled 90th percentile, never stricter than the "
            "default; this is a heuristic."
        ),
    }
    return inferred, evidence
