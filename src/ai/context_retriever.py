import math
import re
from collections import Counter
from dataclasses import dataclass

from src.analyzers.code_quality_analyzer import redact_secrets
from src.models import ChangedFile

MAX_DIFF_CHUNK_CHARS = 6_000
MAX_GUIDELINES_CHARS = 5_000
MAX_RETRIEVED_CHARS = 2_000
MAX_RETRIEVED_CHUNKS = 2
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z_0-9]{2,}")
IGNORED_TERMS = {
    "async",
    "await",
    "class",
    "const",
    "else",
    "false",
    "function",
    "import",
    "return",
    "self",
    "true",
    "void",
}


@dataclass(frozen=True)
class DiffChunk:
    text: str
    files: frozenset[str]


def _file_chunks(changed_file: ChangedFile) -> list[str]:
    if not changed_file.patch:
        if changed_file.content is None:
            return []
        numbered_lines = [
            f"{line_number:>5} | {line}"
            for line_number, line in enumerate(changed_file.content.splitlines(), start=1)
        ]
        prefix = (
            f"### {changed_file.path} ({changed_file.status}; full content because GitHub "
            "did not provide a diff)\n```text\n"
        )
        suffix = "\n```"
        chunks: list[str] = []
        current: list[str] = []
        for line in numbered_lines:
            candidate = "\n".join([*current, line])
            if current and len(prefix) + len(candidate) + len(suffix) > MAX_DIFF_CHUNK_CHARS:
                chunks.append(prefix + "\n".join(current) + suffix)
                current = []
            current.append(line)
        if current:
            chunks.append(prefix + "\n".join(current) + suffix)
        return chunks
    prefix = f"### {changed_file.path} ({changed_file.status})\n```diff\n"
    suffix = "\n```"
    groups: list[list[str]] = []
    current: list[str] = []
    hunk_header = ""
    for line in changed_file.patch.splitlines():
        if line.startswith("@@"):
            hunk_header = line
            if current:
                groups.append(current)
                current = []
            current.append(line)
            continue
        if not current and hunk_header:
            current.append(hunk_header)
        current.append(line)
        if len(prefix) + sum(len(part) + 1 for part in current) + len(suffix) > MAX_DIFF_CHUNK_CHARS:
            if len(current) > 1:
                overflow = current.pop()
                groups.append(current)
                current = [hunk_header, overflow] if hunk_header else [overflow]
            else:
                groups.append(current)
                current = []
    if current:
        groups.append(current)

    chunks = []
    for lines in groups:
        content = prefix + "\n".join(lines) + suffix
        chunks.append(content)
    return chunks


def _terms(text: str) -> Counter[str]:
    return Counter(
        term.lower()
        for term in TOKEN_PATTERN.findall(text)
        if term.lower() not in IGNORED_TERMS
    )


def _similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    numerator = sum(left[term] * right[term] for term in shared)
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(
        sum(value * value for value in right.values())
    )
    return numerator / denominator if denominator else 0.0


def retrieve_related_chunks(
    chunks: list[DiffChunk],
    target_index: int,
) -> list[DiffChunk]:
    """Return a small lexical-relevance context from other changed diff chunks."""
    target = chunks[target_index]
    target_terms = _terms(target.text)
    candidates = [
        (score, index, chunk)
        for index, chunk in enumerate(chunks)
        if index != target_index
        for score in [_similarity(target_terms, _terms(chunk.text))]
        if score > 0
    ]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected: list[DiffChunk] = []
    seen_files = set(target.files)
    for _, _, chunk in candidates:
        if seen_files.intersection(chunk.files) and len(selected) < MAX_RETRIEVED_CHUNKS:
            selected.append(chunk)
            seen_files.update(chunk.files)
            continue
        if not seen_files.intersection(chunk.files):
            selected.append(chunk)
            seen_files.update(chunk.files)
        if len(selected) >= MAX_RETRIEVED_CHUNKS:
            break
    return selected


def build_review_contexts(
    guidelines: str,
    files: list[ChangedFile],
) -> list[str]:
    """Chunk every available PR diff and retrieve related changed-code context."""
    chunks = [
        DiffChunk(text=chunk, files=frozenset({changed_file.path}))
        for changed_file in files
        for chunk in _file_chunks(changed_file)
    ]
    if not chunks:
        return []

    safe_guidelines = redact_secrets(guidelines[:MAX_GUIDELINES_CHARS])
    contexts = []
    for index, chunk in enumerate(chunks):
        related_chunks = retrieve_related_chunks(chunks, index)
        related_text = "\n\n".join(
            redact_secrets(item.text[: MAX_RETRIEVED_CHARS // MAX_RETRIEVED_CHUNKS])
            for item in related_chunks
        )
        contexts.append(
            "Repository coding standards:\n"
            f"{safe_guidelines}\n\n"
            "Related changed-code context retrieved by identifier and keyword similarity "
            "(context only; review the target diff below):\n"
            f"{related_text or '[No closely related changed code found.]'}\n\n"
            "Target diff chunk:\n"
            f"{redact_secrets(chunk.text)}"
        )
    return contexts


def build_review_context(
    guidelines: str,
    files: list[ChangedFile],
    max_diff_chars: int = 100_000,
) -> str:
    """Build a bounded legacy single-request context for callers and tests."""
    sections: list[str] = []
    remaining = max_diff_chars
    for changed_file in files:
        if not changed_file.patch:
            continue
        patch = redact_secrets(changed_file.patch)
        section = (
            f"### {changed_file.path} ({changed_file.status})\n"
            f"```diff\n{patch}\n```"
        )
        if len(section) > remaining:
            if remaining <= 0:
                break
            section = section[:remaining] + "\n[diff truncated]"
        sections.append(section)
        remaining -= len(section)
    safe_guidelines = redact_secrets(guidelines[:30_000])
    diff_context = "\n\n".join(sections)
    return (
        f"Repository coding standards:\n{safe_guidelines}\n\n"
        f"Pull request diff:\n{diff_context}"
    )
