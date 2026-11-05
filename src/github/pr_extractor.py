import base64
import binascii
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.config.settings import Settings
from src.models import ChangedFile, PullRequest


class GitHubError(RuntimeError):
    """Raised when the GitHub REST API cannot provide required review data."""


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise GitHubError("GitHub API returned invalid JSON.") from error


@dataclass
class ApiResponse:
    body: bytes
    headers: Any


def _token_from_gh_cli() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    return token or None


class GitHubClient:
    def __init__(self, settings: Settings, timeout: int = 30) -> None:
        self.token = settings.github_token or _token_from_gh_cli()
        self.timeout = timeout

    @staticmethod
    def _api_url(repo: str, suffix: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise GitHubError("Repository must be in owner/name format.")
        return f"https://api.github.com/repos/{repo}/{suffix.lstrip('/')}"

    def request(
        self,
        url: str,
        *,
        accept: str = "application/vnd.github+json",
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> ApiResponse:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-pr-standardization",
        }
        data = None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return ApiResponse(response.read(), response.headers)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                message = body
            raise GitHubError(f"GitHub API returned HTTP {error.code}: {message}") from error
        except urllib.error.URLError as error:
            raise GitHubError(f"Could not reach GitHub: {error.reason}") from error

    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        payload = _decode_json(self.request(self._api_url(repo, f"pulls/{number}")).body)
        try:
            return PullRequest(
                number=number,
                title=str(payload["title"]),
                url=str(payload["html_url"]),
                base_ref=str(payload["base"]["ref"]),
                base_sha=str(payload["base"]["sha"]),
                head_ref=str(payload["head"]["ref"]),
                head_sha=str(payload["head"]["sha"]),
                comments_url=str(payload["comments_url"]),
                review_comments_url=str(payload.get("review_comments_url", "")),
            )
        except (KeyError, TypeError) as error:
            raise GitHubError("GitHub returned incomplete pull request metadata.") from error

    def list_pull_request_files(self, repo: str, number: int) -> list[dict[str, Any]]:
        url = self._api_url(repo, f"pulls/{number}/files?per_page=100")
        files: list[dict[str, Any]] = []
        while url:
            response = self.request(url)
            files.extend(_decode_json(response.body))
            link_header = response.headers.get("Link", "")
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            url = match.group(1) if match else ""
        return files

    def get_file(self, repo: str, path: str, ref: str) -> str:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(ref, safe="")
        url = self._api_url(repo, f"contents/{encoded_path}?ref={encoded_ref}")
        response = self.request(url, accept="application/vnd.github.raw+json")
        if "application/json" not in response.headers.get("Content-Type", ""):
            return response.body.decode("utf-8", errors="replace")
        payload = _decode_json(response.body)
        if payload.get("encoding") != "base64" or "content" not in payload:
            raise GitHubError(f"GitHub did not return file content for {path!r}.")
        try:
            return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError) as error:
            raise GitHubError(f"GitHub returned invalid base64 content for {path!r}.") from error

    def list_repository_files(
        self,
        repo: str,
        ref: str,
    ) -> list[dict[str, Any]]:
        encoded_ref = urllib.parse.quote(ref, safe="")
        commit_payload = _decode_json(
            self.request(self._api_url(repo, f"commits/{encoded_ref}")).body
        )
        try:
            tree_sha = str(commit_payload["commit"]["tree"]["sha"])
        except (KeyError, TypeError) as error:
            raise GitHubError("GitHub returned incomplete base-branch commit metadata.") from error
        url = self._api_url(
            repo,
            f"git/trees/{urllib.parse.quote(tree_sha, safe='')}?recursive=1",
        )
        payload = _decode_json(self.request(url).body)
        if payload.get("truncated"):
            raise GitHubError(
                "GitHub truncated the base-branch file tree; cannot reliably infer standards."
            )
        tree = payload.get("tree")
        if not isinstance(tree, list):
            raise GitHubError("GitHub returned an invalid base-branch file tree.")
        return [
            item
            for item in tree
            if isinstance(item, dict) and item.get("type") == "blob"
        ]

    def get_changed_files(self, repo: str, pull_request: PullRequest) -> list[ChangedFile]:
        files: list[ChangedFile] = []
        for item in self.list_pull_request_files(repo, pull_request.number):
            path = str(item["filename"])
            status = str(item["status"])
            content = None
            if status != "removed":
                content = self.get_file(repo, path, pull_request.head_sha)
            files.append(
                ChangedFile(
                    path=path,
                    status=status,
                    patch=str(item.get("patch", "")),
                    content=content,
                )
            )
        return files
