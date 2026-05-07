from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from springclean.errors import SpringCleanError
from springclean.github import GitHubClient


def github_date(days_ago: int = 0) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("get", path, params))
        if path == "/repos/owner/repo":
            return {"default_branch": "main"}
        return {
            "commit": {
                "author": {"name": "Commit Author", "date": github_date(120)},
                "committer": {"name": "Commit Committer", "date": github_date(120)},
            },
            "author": {"login": "commit-author"},
            "committer": {"login": "commit-committer"},
        }

    def paged(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.calls.append(("paged", path, params))
        if path.endswith("/branches"):
            return [
                {
                    "name": "feature/example",
                    "commit": {"sha": "abc123"},
                    "protected": False,
                }
            ]
        if path.endswith("/pulls"):
            return [
                {
                    "number": 42,
                    "title": "Keep cleanup visible",
                    "state": "open",
                    "draft": True,
                    "user": {"login": "pr-author"},
                    "base": {"ref": "main"},
                    "head": {
                        "ref": "feature/example",
                        "repo": {"full_name": "owner/repo"},
                    },
                    "created_at": github_date(10),
                    "updated_at": github_date(2),
                    "closed_at": None,
                    "merged_at": None,
                    "merge_commit_sha": "merge-sha",
                    "html_url": "https://github.com/owner/repo/pull/42",
                }
            ]
        if path.endswith("/commits/feature%2Fexample/pulls"):
            return [
                {
                    "number": 42,
                    "state": "open",
                    "merged_at": None,
                    "html_url": "https://github.com/owner/repo/pull/42",
                    "user": {"login": "pr-author"},
                }
            ]
        return []


class PagedClient(GitHubClient):
    def __init__(self, batches: list[Any]) -> None:
        super().__init__(token="token", api_root="https://example.test")
        self.batches = batches
        self.params_seen: list[dict[str, Any]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if params is None:
            raise AssertionError("Expected pagination params.")
        self.params_seen.append(dict(params))
        page = params["page"]
        return self.batches[page - 1]


class FakeUrlopenResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}

    def __enter__(self) -> FakeUrlopenResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FailingAssociatedPrClient:
    def paged(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        raise SpringCleanError("boom")
