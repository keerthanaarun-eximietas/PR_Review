import re
import ast

from src.models import ChangedFile, CheckResult, Finding
from src.standards.standards_parser import CodingStandards

SUPPORTED_NAME_EXTENSIONS = {"py", "js", "jsx", "mjs", "cjs", "ts", "tsx"}
OTHER_CODE_EXTENSIONS = {
    "java", "kt", "kts", "cs", "c", "cpp", "cc", "cxx", "h", "hpp", "go", "rs",
    "rb", "php", "swift", "scala",
}
IDENTIFIER_PATTERNS = {
    "snake_case": re.compile(r"_*[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z"),
    "camelCase": re.compile(r"_*[a-z][A-Za-z0-9]*\Z"),
    "PascalCase": re.compile(r"[A-Z][A-Za-z0-9]*\Z"),
}
JS_FUNCTION = re.compile(
    r"^\s*(?:(?:export|default)\s+)*(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)"
)
JS_VARIABLE = re.compile(
    r"^\s*(?:(?:export|default)\s+)*(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
)
JS_ARROW = re.compile(
    r"^\s*(?:(?:export|default)\s+)*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=.*=>"
)

def _conforms(filename: str, convention: str) -> bool:
    if convention == "any":
        return True
    if convention == "lower_snake_case" and filename == "__init__.py":
        return True
    pattern = {
        "lower_snake_case": r"[a-z0-9]+(?:_[a-z0-9]+)*(?:\.[A-Za-z0-9]+)*",
        "kebab-case": r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[A-Za-z0-9]+)*",
        "camelCase": r"[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*",
        "PascalCase": r"[A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*",
    }[convention]
    return bool(re.fullmatch(pattern, filename))


def _identifier_conforms(name: str, convention: str) -> bool:
    if convention == "any" or name.isupper():
        return True
    if name.startswith("__") and name.endswith("__"):
        return True
    if convention == "snake_case":
        name = name.lstrip("_")
    elif convention == "camelCase":
        name = name.lstrip("_")
    if not name:
        return True
    return bool(IDENTIFIER_PATTERNS[convention].fullmatch(name))


def _python_identifiers(source: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]]] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    functions: list[tuple[str, int]] = []
    variables: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append((node.name, node.lineno))
            variables.extend((argument.arg, argument.lineno) for argument in node.args.args)
            variables.extend((argument.arg, argument.lineno) for argument in node.args.posonlyargs)
            variables.extend((argument.arg, argument.lineno) for argument in node.args.kwonlyargs)
            if node.args.vararg:
                variables.append((node.args.vararg.arg, node.args.vararg.lineno))
            if node.args.kwarg:
                variables.append((node.args.kwarg.arg, node.args.kwarg.lineno))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            variables.append((node.id, node.lineno))
    return functions, variables


def _javascript_identifiers(
    source: str,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    functions: list[tuple[str, int]] = []
    variables: list[tuple[str, int]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        function_match = JS_FUNCTION.search(line)
        variable_match = JS_VARIABLE.search(line)
        arrow_match = JS_ARROW.search(line)
        if function_match:
            functions.append((function_match.group(1), line_number))
        if variable_match:
            variables.append((variable_match.group(1), line_number))
        if arrow_match:
            functions.append((arrow_match.group(1), line_number))
    return functions, variables


def _analyze_identifier_names(
    files: list[ChangedFile],
    *,
    name_kind: str,
    convention: str,
) -> CheckResult:
    findings: list[Finding] = []
    unsupported_files: list[str] = []
    for changed_file in files:
        if changed_file.status == "removed" or changed_file.content is None:
            continue
        extension = changed_file.path.rsplit(".", 1)[-1].lower() if "." in changed_file.path else ""
        if extension == "py":
            identifiers = _python_identifiers(changed_file.content)
            if identifiers is None:
                unsupported_files.append(changed_file.path)
                continue
            names = identifiers[0 if name_kind == "function" else 1]
        elif extension in {"js", "jsx", "mjs", "cjs", "ts", "tsx"}:
            identifiers = _javascript_identifiers(changed_file.content)
            names = identifiers[0 if name_kind == "function" else 1]
        elif extension in OTHER_CODE_EXTENSIONS:
            unsupported_files.append(changed_file.path)
            continue
        else:
            continue

        for name, line_number in names:
            if not _identifier_conforms(name, convention):
                findings.append(
                    Finding(
                        file=changed_file.path,
                        line=line_number,
                        message=f"{name_kind.title()} name {name!r} does not follow {convention}.",
                        severity="medium",
                        reasoning=f"The {name_kind} naming convention is configured in the base-branch standards.",
                    )
                )

    details = None
    if unsupported_files:
        details = (
            "Name checks support Python and JavaScript/TypeScript declarations. "
            "These source files were not checked: " + ", ".join(sorted(set(unsupported_files)))
        )
    status = "fail" if findings else ("skipped" if unsupported_files else "pass")
    check_id = f"{name_kind}_name_convention"
    success = f"Detected {name_kind} names follow the configured convention."
    return CheckResult(
        check_id=check_id,
        category="naming",
        status=status,
        summary=f"{len(findings)} issue(s) found." if findings else success,
        findings=findings,
        details=details,
    )


def analyze_naming(files: list[ChangedFile], standards: CodingStandards) -> CheckResult:
    findings: list[Finding] = []
    for changed_file in files:
        if changed_file.status == "removed":
            continue
        filename = changed_file.path.rsplit("/", 1)[-1]
        if filename in standards.filename_exemptions:
            continue
        if not _conforms(filename, standards.filename_convention):
            findings.append(
                Finding(
                    file=changed_file.path,
                    message=f"Filename does not follow {standards.filename_convention}.",
                    severity="medium",
                    reasoning="The filename convention is configured in the base-branch standards.",
                )
            )
    return CheckResult(
        check_id="filename_convention",
        category="naming",
        status="fail" if findings else "pass",
        summary=f"{len(findings)} issue(s) found." if findings else "Changed filenames follow the configured convention.",
        findings=findings,
    )


def analyze_function_names(
    files: list[ChangedFile],
    standards: CodingStandards,
) -> CheckResult:
    return _analyze_identifier_names_by_language(
        files,
        standards,
        name_kind="function",
        default_convention=standards.function_name_convention,
    )


def analyze_variable_names(
    files: list[ChangedFile],
    standards: CodingStandards,
) -> CheckResult:
    return _analyze_identifier_names_by_language(
        files,
        standards,
        name_kind="variable",
        default_convention=standards.variable_name_convention,
    )


def _analyze_identifier_names_by_language(
    files: list[ChangedFile],
    standards: CodingStandards,
    *,
    name_kind: str,
    default_convention: str,
) -> CheckResult:
    language_by_extension = {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "mjs": "javascript",
        "cjs": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
    }
    results: list[CheckResult] = []
    for language in ("python", "javascript", "typescript"):
        language_files = [
            changed_file
            for changed_file in files
            if changed_file.path.rsplit(".", 1)[-1].lower() in language_by_extension
            and language_by_extension[changed_file.path.rsplit(".", 1)[-1].lower()]
            == language
        ]
        if not language_files:
            continue
        convention = standards.language_conventions.get(language, {}).get(
            f"{name_kind}_name_convention",
            default_convention,
        )
        results.append(
            _analyze_identifier_names(
                language_files,
                name_kind=name_kind,
                convention=convention,
            )
        )
    unsupported_files = [
        changed_file
        for changed_file in files
        if changed_file.path.rsplit(".", 1)[-1].lower() in OTHER_CODE_EXTENSIONS
    ]
    if unsupported_files:
        results.append(
            _analyze_identifier_names(
                unsupported_files,
                name_kind=name_kind,
                convention=default_convention,
            )
        )

    findings = [finding for result in results for finding in result.findings]
    details = sorted({result.details for result in results if result.details})
    unsupported_status = any(result.status == "skipped" for result in results)
    return CheckResult(
        check_id=f"{name_kind}_name_convention",
        category="naming",
        status="fail" if findings else ("skipped" if unsupported_status else "pass"),
        summary=(
            f"{len(findings)} issue(s) found."
            if findings
            else f"Detected {name_kind} names follow the configured convention."
        ),
        findings=findings,
        details="\n".join(details) if details else None,
    )
