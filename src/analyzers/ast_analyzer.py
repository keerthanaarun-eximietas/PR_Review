import ast
import re

from src.models import ChangedFile, CheckResult, Finding
from src.standards.standards_parser import CodingStandards

FUNCTION_START = re.compile(
    r"^\s*(?:(?:export|default|public|private|protected|static|async|override|final|virtual|pub|crate)\s+)*"
    r"(?:function\s+[\w$]+|func\s+(?:\([^)]*\)\s*)?[\w$]+|fn\s+[\w$]+|"
    r"[\w<>\[\],*&~]+\s+[\w~]+\s*\([^;]*\)\s*\{)"
)
ARROW_START = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+[\w$]+\s*=.*=>")
SUPPORTED_EXTENSIONS = {
    "js", "jsx", "mjs", "cjs", "ts", "tsx", "java", "kt", "kts", "cs", "c",
    "cpp", "cc", "cxx", "h", "hpp", "go", "rs",
}
UNSUPPORTED_CODE_EXTENSIONS = {
    "rb", "php", "swift", "scala", "dart", "lua", "r", "sh", "pl", "ex", "exs",
    "erl", "hs", "clj", "cljs", "groovy",
}


def _python_function_spans(source: str) -> list[tuple[str, int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            spans.append((node.name, start, getattr(node, "end_lineno", node.lineno)))
    return spans


def _brace_function_spans(source: str) -> list[tuple[str, int, int]]:
    lines = source.splitlines()
    spans: list[tuple[str, int, int]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        is_arrow_function = bool(ARROW_START.search(line))
        if not (FUNCTION_START.search(line) or is_arrow_function):
            index += 1
            continue
        if is_arrow_function and "{" not in line:
            index += 1
            continue
        start = index + 1
        if not is_arrow_function and not any("{" in candidate for candidate in lines[index:index + 5]):
            index += 1
            continue
        depth = 0
        opened = False
        end = start
        for cursor in range(index, len(lines)):
            depth += lines[cursor].count("{") - lines[cursor].count("}")
            opened = opened or "{" in lines[cursor]
            if opened and depth <= 0:
                end = cursor + 1
                break
        if end == start:
            end = len(lines)
        name_match = re.search(
            r"(?:function|func|fn)\s+([\w$]+)|(?:const|let|var)\s+([\w$]+)",
            line,
        )
        name = next((part for part in name_match.groups() if part), "function") if name_match else "function"
        spans.append((name, start, end))
        index += 1
    return spans


def _function_spans(path: str, source: str) -> tuple[list[tuple[str, int, int]], bool]:
    extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if extension == "py":
        return _python_function_spans(source), True
    if extension in SUPPORTED_EXTENSIONS:
        return _brace_function_spans(source), True
    return [], False


def analyze_function_length(
    files: list[ChangedFile],
    standards: CodingStandards,
) -> CheckResult:
    findings: list[Finding] = []
    unsupported_files: list[str] = []
    for changed_file in files:
        if changed_file.status == "removed" or changed_file.content is None:
            continue
        extension = changed_file.path.rsplit(".", 1)[-1].lower() if "." in changed_file.path else ""
        if extension not in SUPPORTED_EXTENSIONS | UNSUPPORTED_CODE_EXTENSIONS | {"py"}:
            continue
        spans, supported = _function_spans(changed_file.path, changed_file.content)
        if not supported:
            unsupported_files.append(changed_file.path)
        for name, start, end in spans:
            length = end - start + 1
            if length > standards.max_function_lines:
                findings.append(
                    Finding(
                        file=changed_file.path,
                        line=start,
                        message=f"Function {name} has {length} lines; limit is {standards.max_function_lines}.",
                        severity="medium",
                        reasoning="Long functions are harder to understand, test, and change safely.",
                    )
                )

    details = None
    if unsupported_files:
        details = (
            "Function-length scanning supports Python, JavaScript/TypeScript, Java, Kotlin, "
            "C#, C/C++, Go, and Rust; unsupported files were not scanned: "
            + ", ".join(sorted(set(unsupported_files)))
        )
    status = "fail" if findings else ("skipped" if unsupported_files else "pass")
    return CheckResult(
        check_id="function_length",
        category="size",
        status=status,
        summary=(
            f"{len(findings)} issue(s) found."
            if findings
            else "Detected functions are within the configured line limit."
            if not unsupported_files
            else "Some source files could not be checked for function length."
        ),
        findings=findings,
        details=details,
    )
