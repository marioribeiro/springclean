from __future__ import annotations

import io
from contextlib import redirect_stderr

from springclean.reports import (
    associated_pull_requests,
    branch_bucket,
    branch_cleanup_status,
    branch_sort_key,
    collect_branch_rows,
    collect_pr_rows,
    compare_url,
    days_since,
    infer_branch_created_by,
    login_or_name,
    pr_cleanup_status,
    pr_days_open,
    pr_state,
    pr_summary,
    report_basename,
    row_has_pr_state,
    split_values,
)

from .helpers import FailingAssociatedPrClient, FakeClient, github_date


def test_branch_bucket_uses_configured_stale_threshold() -> None:
    assert branch_bucket("main", "main", github_date(500), 90) == "default"
    assert branch_bucket("feature", "main", github_date(89), 90) == "active"
    assert branch_bucket("feature", "main", github_date(91), 90) == "stale"
    assert branch_bucket("feature", "main", None, 90) == "unknown"


def test_branch_cleanup_status_prioritizes_protected_and_open_prs() -> None:
    assert branch_cleanup_status(False, True, "stale", [], 90)[0] == "keep_protected"
    assert branch_cleanup_status(False, False, "stale", ["open"], 90)[0] == "review_stale_open_pr"
    assert branch_cleanup_status(False, False, "stale", [], 90)[0] == "candidate_stale_no_pr"
    assert branch_cleanup_status(True, False, "default", [], 90)[0] == "keep_default"
    assert branch_cleanup_status(False, False, "active", [], 90)[0] == "review_active"
    assert branch_cleanup_status(False, False, "unknown", [], 90)[0] == "review_unknown_activity"
    assert branch_cleanup_status(False, False, "stale", ["merged"], 90)[0] == "candidate_stale_merged_pr"
    assert branch_cleanup_status(False, False, "stale", ["closed"], 90)[0] == "candidate_stale_closed_pr"


def test_pr_cleanup_status_tracks_open_and_draft_activity() -> None:
    assert pr_cleanup_status({"draft": False}, "open", 2, 90)[0] == "open_active"
    assert pr_cleanup_status({"draft": False}, "open", 120, 90)[0] == "open_stale"
    assert pr_cleanup_status({"draft": True}, "open", 120, 90)[0] == "draft_stale"
    assert pr_cleanup_status({"draft": False}, "closed", 120, 90)[0] == "closed_unmerged"
    assert pr_cleanup_status({"draft": False}, "merged", 120, 90)[0] == "merged"


def test_report_fallback_helpers() -> None:
    assert infer_branch_created_by([], "author", "committer") == ("author", "last_commit_author")
    assert infer_branch_created_by([], "", "committer") == ("committer", "last_commit_committer")
    assert infer_branch_created_by([], "", "") == ("", "unknown")
    assert compare_url("owner", "repo", "main", "main") == ""
    assert days_since(None) == ""
    assert pr_days_open({}) == ""
    assert login_or_name(None, {"name": "Commit Author"}) == "Commit Author"
    assert pr_state({"state": "closed", "merged_at": "2026-01-01T00:00:00Z"}) == "merged"
    assert split_values("") == []
    assert not row_has_pr_state({"github_branch_bucket": "active", "associated_pr_states": "open"}, "open")
    assert branch_sort_key({"github_branch_bucket": "default", "days_since_last_commit": 100}) == (0, 0)


def test_associated_pull_requests_failure_returns_empty_list() -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        assert associated_pull_requests(FailingAssociatedPrClient(), "owner", "repo", "branch") == []

    assert "Could not fetch associated PRs" in stderr.getvalue()


def test_collect_pr_rows_fetches_only_open_prs() -> None:
    client = FakeClient()
    rows = collect_pr_rows(client, "owner", "repo", stale_days=90)

    assert rows[0]["created_by"] == "pr-author"
    assert rows[0]["cleanup_status"] == "draft_active"
    assert ("paged", "/repos/owner/repo/pulls", {"state": "open"}) in client.calls


def test_collect_branch_rows_infers_context_owner_from_associated_pr() -> None:
    client = FakeClient()
    rows = collect_branch_rows(client, "owner", "repo", "main", stale_days=90)

    assert rows[0]["branch_created_by"] == "pr-author"
    assert rows[0]["branch_created_by_source"] == "associated_pr_author"
    assert rows[0]["associated_pr_authors"] == "pr-author"
    assert rows[0]["cleanup_status"] == "review_stale_open_pr"


def test_report_basename_is_repo_specific_and_timestamped() -> None:
    value = report_basename("my-org", "springclean")

    assert value.startswith("my-org_springclean_")
    assert value.endswith("Z")


def test_summary_contains_open_pr_counts() -> None:
    rows = [
        {"state": "open", "draft": False, "cleanup_status": "open_active"},
        {"state": "open", "draft": True, "cleanup_status": "draft_stale"},
    ]

    summary = "\n".join(pr_summary(rows))

    assert "- Ready for review: 1" in summary
    assert "- Draft: 1" in summary
    assert "- Draft stale: 1" in summary
