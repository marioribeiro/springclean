from __future__ import annotations

import asyncio
import csv
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from textual.widgets import Button, DataTable, LoadingIndicator

from springclean.errors import SpringCleanError
from springclean.reports import BRANCH_FIELDS, PR_FIELDS
from springclean.tui import (
    BRANCH_KIND,
    GITHUB_REPO_KIND,
    PR_KIND,
    SOURCE_KIND,
    AuditResult,
    DeleteReportConfirm,
    ReportData,
    ReportSource,
    SpringCleanBrowser,
    audit_github_repository,
    branch_filter_modes,
    delete_report_source,
    delete_report_summary,
    detail_text,
    empty_detail_text,
    filter_modes,
    filtered_rows,
    generated_from_prefix,
    github_repo_detail,
    input_placeholder,
    list_github_repositories,
    load_report_source,
    load_reports,
    pr_filter_modes,
    repo_from_prefix,
    report_source_detail,
    report_source_paths,
    report_source_row,
    report_sources,
    row_cells,
    run_browser,
    status_text,
    table_columns,
    total_count,
    view_name,
)


def test_load_reports_reads_latest_report_bundle(tmp_path: Path) -> None:
    write_report(
        tmp_path / "owner_repo_20260507T120000Z_branches.csv",
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "old-main"}],
    )
    write_report(
        tmp_path / "owner_repo_20260507T130000Z_branches.csv",
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "new-main"}],
    )
    write_report(
        tmp_path / "owner_repo_20260507T130000Z_pull_requests.csv",
        PR_FIELDS,
        [{"repo": "owner/repo", "number": "42", "title": "Review this"}],
    )
    for path in tmp_path.glob("*120000Z*.csv"):
        os.utime(path, (1, 1))
    for path in tmp_path.glob("*130000Z*.csv"):
        os.utime(path, (2, 2))

    reports = load_reports(tmp_path)

    assert [report.kind for report in reports] == [BRANCH_KIND, PR_KIND]
    assert reports[0].rows[0]["branch"] == "new-main"
    assert reports[1].rows[0]["number"] == "42"


def test_report_sources_lists_report_folder_bundles(tmp_path: Path) -> None:
    write_report(
        tmp_path / "owner_repo_20260507T130000Z_branches.csv",
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "main"}],
    )
    write_report(
        tmp_path / "owner_repo_20260507T130000Z_pull_requests.csv",
        PR_FIELDS,
        [{"repo": "owner/repo", "number": "42", "title": "Review this"}],
    )
    (tmp_path / "owner_repo_20260507T130000Z_summary.md").write_text("# Summary", encoding="utf-8")

    sources = report_sources(tmp_path)
    row = report_source_row(sources[0])

    assert len(sources) == 1
    assert sources[0].summary_path is not None
    assert row["repo"] == "owner/repo"
    assert row["generated"] == "2026-05-07 13:00 UTC"
    assert row["reports"] == "branches, pull requests"
    assert row["rows"] == "2"


def test_load_reports_reads_summary_siblings(tmp_path: Path) -> None:
    summary = tmp_path / "owner_repo_20260507T130000Z_summary.md"
    summary.write_text("# Summary", encoding="utf-8")
    write_report(
        tmp_path / "owner_repo_20260507T130000Z_branches.csv",
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "main"}],
    )

    reports = load_reports(summary)

    assert len(reports) == 1
    assert reports[0].kind == BRANCH_KIND
    assert reports[0].rows[0]["branch"] == "main"


def test_load_reports_detects_single_csv_type(tmp_path: Path) -> None:
    branch_path = tmp_path / "branches.csv"
    pr_path = tmp_path / "pull_requests.csv"
    write_report(branch_path, BRANCH_FIELDS, [{"repo": "owner/repo", "branch": "main"}])
    write_report(pr_path, PR_FIELDS, [{"repo": "owner/repo", "number": "42", "title": "Review this"}])

    assert load_reports(branch_path)[0].kind == BRANCH_KIND
    assert load_reports(pr_path)[0].kind == PR_KIND


def test_load_reports_rejects_unknown_csv(tmp_path: Path) -> None:
    write_report(tmp_path / "unknown.csv", ["thing"], [{"thing": "value"}])

    with pytest.raises(SpringCleanError, match="Could not identify report type"):
        load_reports(tmp_path / "unknown.csv")


def test_load_reports_reports_missing_reports(tmp_path: Path) -> None:
    with pytest.raises(SpringCleanError, match="Could not find a report"):
        load_reports(tmp_path / "missing.csv")

    with pytest.raises(SpringCleanError, match="No Spring Clean CSV reports"):
        load_reports(tmp_path)

    summary = tmp_path / "owner_repo_20260507T130000Z_summary.md"
    summary.write_text("# Summary", encoding="utf-8")
    with pytest.raises(SpringCleanError, match="No branch or pull request CSV reports"):
        load_reports(summary)


def test_load_report_source_rejects_empty_source(tmp_path: Path) -> None:
    source = ReportSource("owner_repo_20260507T130000Z", tmp_path, None, None, None, 1)

    with pytest.raises(SpringCleanError, match="No branch or pull request CSV reports"):
        load_report_source(source)


def test_delete_report_source_removes_only_bundle_files(tmp_path: Path) -> None:
    branch_path = tmp_path / "owner_repo_20260507T130000Z_branches.csv"
    pr_path = tmp_path / "owner_repo_20260507T130000Z_pull_requests.csv"
    summary_path = tmp_path / "owner_repo_20260507T130000Z_summary.md"
    unrelated_path = tmp_path / "keep.csv"
    for path in (branch_path, pr_path, summary_path, unrelated_path):
        path.write_text("content", encoding="utf-8")
    source = ReportSource("owner_repo_20260507T130000Z", tmp_path, branch_path, pr_path, summary_path, 1)

    assert report_source_paths(source) == [branch_path, pr_path, summary_path]
    assert delete_report_source(source) == 3
    assert not branch_path.exists()
    assert not pr_path.exists()
    assert not summary_path.exists()
    assert unrelated_path.exists()


def test_filtered_rows_supports_search_and_cleanup_filters() -> None:
    rows = [
        {
            "branch": "feature/delete-me",
            "github_branch_bucket": "stale",
            "cleanup_status": "candidate_stale_no_pr",
            "associated_pr_numbers": "",
        },
        {
            "branch": "feature/keep-me",
            "github_branch_bucket": "active",
            "cleanup_status": "review_active",
            "associated_pr_numbers": "10",
        },
    ]

    assert [row["branch"] for row in filtered_rows(rows, BRANCH_KIND, "delete", "all")] == ["feature/delete-me"]
    assert [row["branch"] for row in filtered_rows(rows, BRANCH_KIND, "", "candidates")] == ["feature/delete-me"]
    assert [row["branch"] for row in filtered_rows(rows, BRANCH_KIND, "", "no_pr")] == ["feature/delete-me"]


def test_filtered_rows_supports_pr_filters() -> None:
    rows = [
        {"number": "1", "draft": "False", "cleanup_status": "open_stale"},
        {"number": "2", "draft": "True", "cleanup_status": "draft_active"},
        {"number": "3", "draft": "False", "cleanup_status": "open_active"},
    ]

    assert [row["number"] for row in filtered_rows(rows, PR_KIND, "", "stale")] == ["1"]
    assert [row["number"] for row in filtered_rows(rows, PR_KIND, "", "draft")] == ["2"]
    assert [row["number"] for row in filtered_rows(rows, PR_KIND, "3", "unknown")] == ["3"]


def test_github_repo_filters_and_listing() -> None:
    rows = [
        {"full_name": "owner/private", "private": True, "archived": False},
        {"full_name": "owner/archived", "private": False, "archived": True},
    ]

    assert [row["full_name"] for row in filtered_rows(rows, GITHUB_REPO_KIND, "", "private")] == ["owner/private"]
    assert [row["full_name"] for row in filtered_rows(rows, GITHUB_REPO_KIND, "", "archived")] == ["owner/archived"]

    class FakeRepoClient:
        def paged(self, path: str, params: dict[str, str]) -> list[dict[str, object]]:
            assert path == "/user/repos"
            assert params["sort"] == "updated"
            return rows

    assert list_github_repositories(FakeRepoClient())[0]["full_name"] == "owner/private"


def test_audit_github_repository_runs_audit_and_loads_latest_report(tmp_path: Path) -> None:
    report = ReportData(BRANCH_KIND, tmp_path / "branches.csv", [])

    with (
        patch("springclean.tui.audit_repo") as audit,
        patch("springclean.tui.load_latest_report_bundle", return_value=[report]) as load_latest,
    ):
        result = audit_github_repository("owner", "repo", "token", tmp_path)

    audit.assert_called_once()
    assert audit.call_args.kwargs["owner"] == "owner"
    assert audit.call_args.kwargs["include_branches"] is True
    assert audit.call_args.kwargs["include_prs"] is True
    load_latest.assert_called_once_with(tmp_path)
    assert result == AuditResult(owner="owner", repo="repo", reports=[report])


def test_detail_text_includes_pr_review_context() -> None:
    row = {
        "repo": "owner/repo",
        "number": "42",
        "title": "Clean stale branches",
        "created_by": "mario",
        "cleanup_status": "draft_stale",
        "cleanup_reason": "Draft PR has no updates in more than 90 days.",
        "url": "https://github.com/owner/repo/pull/42",
    }

    detail = detail_text(PR_KIND, row)

    assert "Pull request: #42 Clean stale branches" in detail
    assert "Created by: mario" in detail
    assert "Cleanup status: draft_stale" in detail
    assert "URL: https://github.com/owner/repo/pull/42" in detail


def test_detail_text_includes_branch_review_context() -> None:
    row = {
        "repo": "owner/repo",
        "branch": "feature/delete-me",
        "branch_created_by": "mario",
        "branch_created_by_source": "associated_pr_author",
        "cleanup_status": "candidate_stale_no_pr",
        "cleanup_reason": "Stale branch has no associated PRs.",
        "last_commit_sha": "abc123",
        "last_commit_date": "2026-01-01T00:00:00Z",
        "branch_url": "https://github.com/owner/repo/tree/feature/delete-me",
    }

    detail = detail_text(BRANCH_KIND, row)

    assert "Branch: feature/delete-me" in detail
    assert "Context owner: mario (associated_pr_author)" in detail
    assert "Last commit: abc123 (2026-01-01T00:00:00Z)" in detail


def test_table_helpers_format_source_branch_pr_and_repo_rows() -> None:
    source_row = {
        "repo": "owner/repo",
        "generated": "20260507T130000Z",
        "reports": "branches",
        "rows": "1",
        "report_id": "owner_repo_20260507T130000Z",
    }
    github_row = {
        "full_name": "owner/repo",
        "private": True,
        "archived": False,
        "updated_at": "2026-05-07T13:00:00Z",
        "default_branch": "main",
    }
    branch_row = {
        "branch": "feature/example",
        "days_since_last_commit": "120",
        "github_branch_bucket": "stale",
        "cleanup_status": "candidate_stale_no_pr",
        "branch_created_by": "mario",
        "associated_pr_numbers": "",
        "protected": "False",
    }
    pr_row = {
        "number": "42",
        "title": "Review this",
        "state": "open",
        "draft": "True",
        "days_since_updated": "120",
        "created_by": "mario",
        "cleanup_status": "draft_stale",
    }

    assert table_columns(SOURCE_KIND)[0] == "Repo"
    assert table_columns(GITHUB_REPO_KIND)[0] == "Repository"
    assert table_columns(BRANCH_KIND)[0] == "Branch"
    assert table_columns(PR_KIND)[0] == "PR"
    assert row_cells(SOURCE_KIND, source_row)[0] == "owner/repo"
    assert row_cells(GITHUB_REPO_KIND, github_row)[0] == "owner/repo"
    assert row_cells(BRANCH_KIND, branch_row)[0] == "feature/example"
    assert row_cells(PR_KIND, pr_row)[0] == "#42"
    assert branch_filter_modes() == ["all", "stale", "candidates", "no_pr"]
    assert pr_filter_modes() == ["all", "stale", "draft"]
    assert "filter: no pr" in status_text(BRANCH_KIND, 1, 1, "no_pr")


def test_detail_and_status_helpers_cover_all_views(tmp_path: Path) -> None:
    branch_path = tmp_path / "owner_repo_20260507T130000Z_branches.csv"
    write_report(branch_path, BRANCH_FIELDS, [{"repo": "", "branch": "main"}])
    source = ReportSource("owner_repo_20260507T130000Z", tmp_path, branch_path, None, None, 1)
    repo_row = {
        "full_name": "owner/repo",
        "private": True,
        "archived": False,
        "default_branch": "main",
        "updated_at": "2026-05-07T13:00:00Z",
        "description": "Example",
        "html_url": "https://github.com/owner/repo",
    }

    assert "Repo: owner/repo" in report_source_detail(source)
    assert "Generated: 2026-05-07 13:00 UTC" in report_source_detail(source)
    assert delete_report_summary(source) == "Repo: owner/repo\nGenerated: 2026-05-07 13:00 UTC"
    assert "Repository: owner/repo" in github_repo_detail(repo_row)
    assert "No Spring Clean reports" in empty_detail_text(SOURCE_KIND, tmp_path)
    assert "No repositories match" in empty_detail_text(GITHUB_REPO_KIND, tmp_path)
    assert "No rows match" in empty_detail_text(BRANCH_KIND, tmp_path)
    assert total_count(SOURCE_KIND, [source], [], None) == 1
    assert total_count(GITHUB_REPO_KIND, [], [repo_row], None) == 1
    assert total_count(BRANCH_KIND, [], [], ReportData(BRANCH_KIND, branch_path, [{}])) == 1
    assert filter_modes(SOURCE_KIND) == ["all"]
    assert input_placeholder(SOURCE_KIND).startswith("Search reports")
    assert input_placeholder(GITHUB_REPO_KIND) == "Search GitHub repositories"
    assert input_placeholder(BRANCH_KIND) == "Search branch rows"
    assert input_placeholder(PR_KIND) == "Search pull request rows"
    assert view_name(SOURCE_KIND) == "reports"
    assert view_name(GITHUB_REPO_KIND) == "github repos"
    assert view_name(BRANCH_KIND) == "branches"
    assert view_name(PR_KIND) == "pull requests"
    assert repo_from_prefix("plain") == "plain"
    assert generated_from_prefix("plain") == ""
    assert generated_from_prefix("owner_repo_not-a-date") == "not-a-date"


def test_run_browser_starts_app_with_reports_dir() -> None:
    with patch("springclean.tui.SpringCleanBrowser.run") as run:
        run_browser(Path("reports"))

    run.assert_called_once_with()


def test_browser_starts_on_report_sources_and_loads_selected_source(tmp_path: Path) -> None:
    write_report(
        tmp_path / "owner_repo_20260507T130000Z_branches.csv",
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "main", "github_branch_bucket": "default", "cleanup_status": "keep_default"}],
    )
    app = SpringCleanBrowser(reports_dir=tmp_path)

    async def run_app() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.active_kind == SOURCE_KIND
            assert len(app.visible_sources) == 1

            app.search_text = "owner/repo"
            app.refresh_active_view()
            assert len(app.visible_rows) == 1

            app.action_select_row()
            assert app.active_kind == BRANCH_KIND
            assert app.reports[BRANCH_KIND].rows[0]["branch"] == "main"

            app.action_show_reports()
            assert app.active_kind == SOURCE_KIND
            app.select_index(-1)

    asyncio.run(run_app())


def test_browser_delete_report_requires_confirmation(tmp_path: Path) -> None:
    branch_path = tmp_path / "owner_repo_20260507T130000Z_branches.csv"
    summary_path = tmp_path / "owner_repo_20260507T130000Z_summary.md"
    write_report(
        branch_path,
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "main", "github_branch_bucket": "default", "cleanup_status": "keep_default"}],
    )
    summary_path.write_text("# Summary", encoding="utf-8")
    app = SpringCleanBrowser(reports_dir=tmp_path)

    async def run_app() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            source = app.visible_sources[0]

            app.delete_report_after_confirmation(source, False)
            assert branch_path.exists()
            assert summary_path.exists()
            assert app.message == "Delete cancelled."

            app.delete_report_after_confirmation(source, True)
            assert not branch_path.exists()
            assert not summary_path.exists()
            assert app.visible_sources == []

    asyncio.run(run_app())


def test_browser_delete_report_modal_requires_confirmation(tmp_path: Path) -> None:
    branch_path = tmp_path / "owner_repo_20260507T130000Z_branches.csv"
    write_report(
        branch_path,
        BRANCH_FIELDS,
        [{"repo": "owner/repo", "branch": "main", "github_branch_bucket": "default", "cleanup_status": "keep_default"}],
    )
    app = SpringCleanBrowser(reports_dir=tmp_path)

    async def run_app() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_delete_report()
            await pilot.pause()
            assert isinstance(app.screen, DeleteReportConfirm)
            assert app.screen.query_one("#cancel-delete", Button).has_focus
            await pilot.press("escape")
            await pilot.pause()
            assert branch_path.exists()
            assert app.message == "Delete cancelled."

            app.action_delete_report()
            await pilot.pause()
            assert isinstance(app.screen, DeleteReportConfirm)
            assert app.screen.query_one("#cancel-delete", Button).has_focus
            await pilot.press("y")
            await pilot.pause()
            assert not branch_path.exists()
            assert app.visible_sources == []

    asyncio.run(run_app())


def test_delete_report_confirm_button_paths(tmp_path: Path) -> None:
    source = ReportSource("owner_repo_20260507T130000Z", tmp_path, tmp_path / "branches.csv", None, None, 1)
    screen = DeleteReportConfirm(source)

    with patch.object(screen, "dismiss") as dismiss:
        screen.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="confirm-delete")))
        screen.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="cancel-delete")))
        screen.action_confirm()
        screen.action_cancel()

    assert [call.args[0] for call in dismiss.call_args_list] == [True, False, True, False]


def test_browser_mounts_and_handles_actions() -> None:
    app = SpringCleanBrowser(
        reports=[
            ReportData(
                kind=BRANCH_KIND,
                path=Path("branches.csv"),
                rows=[
                    {
                        "repo": "owner/repo",
                        "branch": "feature/example",
                        "github_branch_bucket": "stale",
                        "cleanup_status": "candidate_stale_no_pr",
                        "associated_pr_numbers": "",
                    }
                ],
            ),
            ReportData(
                kind=PR_KIND,
                path=Path("pull_requests.csv"),
                rows=[
                    {
                        "repo": "owner/repo",
                        "number": "42",
                        "title": "Review this",
                        "draft": "True",
                        "cleanup_status": "draft_stale",
                    }
                ],
            ),
        ],
    )

    async def run_app() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.visible_rows) == 1
            assert app.query_one("#results", DataTable).cursor_type == "row"

            app.action_show_prs()
            assert app.active_kind == PR_KIND
            app.action_delete_report()
            assert "Open reports" in app.message
            app.action_cycle_filter()
            assert app.filter_mode == "stale"

            app.action_show_branches()
            assert app.active_kind == BRANCH_KIND
            app.action_cycle_filter()
            assert app.filter_mode == "stale"

            app.on_input_changed(SimpleNamespace(input=SimpleNamespace(id="search"), value="missing"))
            assert app.visible_rows == []
            app.update_detail_for_index(10)

            app.action_show_all()
            assert app.filter_mode == "all"
            app.action_focus_search()

            app.action_clear_search()
            assert app.search_text == ""

            app.on_data_table_row_highlighted(SimpleNamespace(cursor_row=0))
            app.on_data_table_row_selected(SimpleNamespace(cursor_row=0))
            app.on_input_changed(SimpleNamespace(input=SimpleNamespace(id="other"), value="ignored"))
            app.on_input_submitted(SimpleNamespace(input=SimpleNamespace(id="other"), value="ignored"))

    asyncio.run(run_app())


def test_browser_lists_github_repos_and_runs_selected_audit(tmp_path: Path) -> None:
    report = ReportData(
        kind=BRANCH_KIND,
        path=tmp_path / "branches.csv",
        rows=[
            {
                "repo": "owner/repo",
                "branch": "main",
                "github_branch_bucket": "default",
                "cleanup_status": "keep_default",
            }
        ],
    )
    app = SpringCleanBrowser(reports_dir=tmp_path)
    audit_started = Event()
    release_audit = Event()

    def audit_result(owner: str, repo: str, token: str, reports_dir: Path) -> AuditResult:
        audit_started.set()
        release_audit.wait(1)
        return AuditResult(owner=owner, repo=repo, reports=[report])

    async def run_app() -> None:
        with (
            patch("springclean.tui.github_token", return_value="token"),
            patch(
                "springclean.tui.list_github_repositories",
                return_value=[
                    {
                        "full_name": "owner/repo",
                        "private": True,
                        "archived": False,
                        "updated_at": "2026-05-07T13:00:00Z",
                        "default_branch": "main",
                    }
                ],
            ),
            patch("springclean.tui.audit_github_repository", side_effect=audit_result) as audit,
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                app.action_list_repos()
                assert app.active_kind == GITHUB_REPO_KIND
                assert app.query_one("#loader", LoadingIndicator).display is True
                assert "Loading repositories" in app.message
                await pilot.pause(0.1)
                assert app.query_one("#loader", LoadingIndicator).display is False
                assert app.visible_rows[0]["full_name"] == "owner/repo"

                app.action_cycle_filter()
                assert app.filter_mode == "private"
                app.action_show_all()
                app.select_index(0)
                assert app.query_one("#loader", LoadingIndicator).display is True
                assert "Auditing owner/repo" in app.message

                for _ in range(20):
                    if audit_started.is_set():
                        break
                    await pilot.pause(0.05)
                assert audit_started.is_set()

                release_audit.set()
                await pilot.pause(0.1)
                assert app.query_one("#loader", LoadingIndicator).display is False
                assert app.active_kind == BRANCH_KIND

        audit.assert_called_once()
        assert audit.call_args.args[:2] == ("owner", "repo")

    asyncio.run(run_app())


def test_browser_handles_github_input_and_errors(tmp_path: Path) -> None:
    app = SpringCleanBrowser(reports_dir=tmp_path)

    async def run_app() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_github_input()
            assert app.command_mode == "audit_repo"

            with patch.object(app, "run_audit") as run_audit:
                app.on_input_submitted(SimpleNamespace(input=SimpleNamespace(id="search"), value="owner/repo"))
            run_audit.assert_called_once_with("owner/repo")

            with patch("springclean.tui.github_token", return_value=None):
                app.action_list_repos()
            assert "Missing GITHUB_TOKEN" in app.message

            app.run_audit("not-a-repo")
            assert "Repository must be in owner/name format" in app.message

            with patch("springclean.tui.github_token", return_value=None):
                app.run_audit("owner/repo")
            assert "Missing GITHUB_TOKEN" in app.message

    asyncio.run(run_app())


def write_report(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
