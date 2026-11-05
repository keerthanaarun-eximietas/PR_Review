import os
import re
from dataclasses import dataclass
from pathlib import Path


_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _read_dotenv(env_file: Path) -> dict[str, str]:
    """Read simple KEY=value entries without printing their values."""
    if not env_file.exists():
        return {}
    if not env_file.is_file():
        raise ValueError(f"Environment file is not a regular file: {env_file}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        env_file.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid environment entry in {env_file} at line {line_number}.")
        name, value = line.split("=", 1)
        name = name.strip()
        if not _ENV_KEY.fullmatch(name):
            raise ValueError(f"Invalid environment variable name in {env_file} at line {line_number}.")

        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise ValueError(f"Unclosed quote in {env_file} at line {line_number}.")
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[name] = value
    return values


@dataclass(frozen=True)
class Settings:
    output_dir: Path = Path("pr-review-reports")
    guidelines_candidates: tuple[str, ...] = (
        ".ai-review/coding-standards.md",
        ".ai-review/coding-standards.json",
        "guidelines.md",
        "GUIDELINES.md",
        "CONTRIBUTING.md",
        "contributing.md",
        ".github/CONTRIBUTING.md",
        "AGENTS.md",
        ".github/AGENTS.md",
    )
    ai_endpoint: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    github_token: str | None = None

    @classmethod
    def from_environment(
        cls,
        output_dir: Path | None = None,
        env_file: Path | None = None,
    ) -> "Settings":
        dotenv_values = _read_dotenv(env_file or Path.cwd() / ".env")

        def get_value(name: str) -> str | None:
            return os.environ.get(name) or dotenv_values.get(name)

        return cls(
            output_dir=output_dir or Path(get_value("PR_REVIEW_OUTPUT") or "pr-review-reports"),
            ai_endpoint=get_value("PR_REVIEW_AI_ENDPOINT"),
            ai_api_key=(
                get_value("GROQ_API_KEY")
                or get_value("AI_GATEWAY_API_KEY")
                or get_value("PR_REVIEW_AI_API_KEY")
            ),
            ai_model=get_value("PR_REVIEW_AI_MODEL"),
            github_token=get_value("GITHUB_TOKEN"),
        )
