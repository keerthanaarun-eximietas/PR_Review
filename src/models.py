from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Finding:
    file: str
    message: str
    line: int | None = None
    severity: str = "medium"
    reasoning: str = ""
    potential_solution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckResult:
    check_id: str
    category: str
    status: str
    summary: str
    findings: list[Finding] = field(default_factory=list)
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass
class ChangedFile:
    path: str
    status: str
    patch: str = ""
    content: str | None = None


@dataclass
class PullRequest:
    number: int
    title: str
    url: str
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    comments_url: str
    review_comments_url: str = ""
