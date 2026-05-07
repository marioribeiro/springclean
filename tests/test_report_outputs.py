from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from springclean.errors import SpringCleanError
from springclean.reports import BRANCH_FIELDS, PR_FIELDS, audit_repo, write_summary

from .helpers import FakeClient


def test_audit_repo_writes_timestamped_reports(tmp_path: Path) -> None:
    audit_repo(
        client=FakeClient(),
        owner="owner",
        repo="repo",
        include_branches=True,
        include_prs=True,
        out_dir=tmp_path,
        stale_days=90,
    )

    branch_files = list(tmp_path.glob("owner_repo_*_branches.csv"))
    pr_files = list(tmp_path.glob("owner_repo_*_pull_requests.csv"))
    summary_files = list(tmp_path.glob("owner_repo_*_summary.md"))

    assert len(branch_files) == 1
    assert len(pr_files) == 1
    assert len(summary_files) == 1

    with branch_files[0].open(newline="", encoding="utf-8") as handle:
        assert csv.DictReader(handle).fieldnames == BRANCH_FIELDS

    with pr_files[0].open(newline="", encoding="utf-8") as handle:
        assert csv.DictReader(handle).fieldnames == PR_FIELDS

    summary = summary_files[0].read_text(encoding="utf-8")
    assert "Repo: owner/repo" in summary
    assert "## Branches" in summary
    assert "## Open Pull Requests" in summary


def test_audit_repo_wraps_repo_access_errors(tmp_path: Path) -> None:
    class BrokenClient:
        def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            raise SpringCleanError("not found")

    with pytest.raises(SpringCleanError, match="Could not access owner/repo"):
        audit_repo(BrokenClient(), "owner", "repo", True, False, tmp_path, 90)


def test_write_summary_allows_partial_reports(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    write_summary(path, "owner/repo", {"default_branch": "main"}, 90, [], None)

    summary = path.read_text(encoding="utf-8")

    assert "## Branches" in summary
    assert "## Open Pull Requests" not in summary
