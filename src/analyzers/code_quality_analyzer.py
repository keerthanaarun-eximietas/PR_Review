import re

from src.models import ChangedFile, CheckResult, Finding

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"""(?i)\b(?:[A-Za-z_][A-Za-z0-9_]*(?:token|secret|password|passwd|"""
        r"""(?:api|access)[_-]?key|credential|private[_-]?key)|"""
        r"""token|secret|password|passwd|(?:api|access)[_-]?key|credential|private[_-]?key)\b"""
        r"""\s*[:=]\s*(['"])(?!['"])([^'"]{8,})\1"""
    ),
    re.compile(r"\b(?:git|gh[pousr]|github_pat)_[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
]
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    flags=re.DOTALL,
)
PLACEHOLDER_VALUES = ("example", "sample", "placeholder", "changeme", "your_", "dummy", "redacted")


def redact_secrets(source: str) -> str:
    redacted = PRIVATE_KEY_BLOCK.sub("[REDACTED_PRIVATE_KEY]", source)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def analyze_hardcoded_secrets(files: list[ChangedFile]) -> CheckResult:
    findings: list[Finding] = []
    for changed_file in files:
        if changed_file.status == "removed" or changed_file.content is None:
            continue
        for line_number, line in enumerate(changed_file.content.splitlines(), start=1):
            match = None
            for pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    break
            if match is None:
                continue
            if any(value in match.group(0).lower() for value in PLACEHOLDER_VALUES):
                continue
            findings.append(
                Finding(
                    file=changed_file.path,
                    line=line_number,
                    message="Potential hardcoded credential or private key detected; value omitted.",
                    severity="high",
                    reasoning="Credentials should be supplied through a secret manager or environment configuration.",
                )
            )
    return CheckResult(
        check_id="hardcoded_secrets",
        category="security",
        status="fail" if findings else "pass",
        summary=f"{len(findings)} issue(s) found." if findings else "No likely hardcoded credentials were detected.",
        findings=findings,
    )
