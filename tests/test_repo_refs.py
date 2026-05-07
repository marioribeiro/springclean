from __future__ import annotations

import pytest

from springclean.errors import SpringCleanError
from springclean.repo_refs import parse_repo_reference


def test_parse_repo_reference_accepts_common_github_forms() -> None:
    assert parse_repo_reference("owner/repo") == ("owner", "repo")
    assert parse_repo_reference("https://github.com/owner/repo/pull/1") == ("owner", "repo")
    assert parse_repo_reference("git@github.com:owner/repo.git") == ("owner", "repo")


def test_parse_repo_reference_rejects_invalid_values() -> None:
    with pytest.raises(SpringCleanError, match="Repository must be in owner/name format"):
        parse_repo_reference("")

    with pytest.raises(SpringCleanError, match="GitHub URL must use github.com"):
        parse_repo_reference("https://example.com/owner/repo")
