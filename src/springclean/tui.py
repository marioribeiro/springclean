from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, LoadingIndicator, Static
from textual.worker import Worker, WorkerState

from .env import github_token
from .errors import SpringCleanError
from .github import GitHubClient
from .repo_refs import parse_repo_reference
from .reports import DEFAULT_STALE_DAYS, audit_repo

SOURCE_KIND = "source"
GITHUB_REPO_KIND = "github_repo"
BRANCH_KIND = "branch"
PR_KIND = "pr"
BRANCH_SUFFIX = "_branches.csv"
PR_SUFFIX = "_pull_requests.csv"
SUMMARY_SUFFIX = "_summary.md"


@dataclass(frozen=True)
class ReportSource:
    prefix: str
    reports_dir: Path
    branch_path: Path | None
    pr_path: Path | None
    summary_path: Path | None
    modified_at: float


@dataclass(frozen=True)
class ReportData:
    kind: str
    path: Path
    rows: list[dict[str, str]]
    fieldnames: list[str] | None = None


@dataclass(frozen=True)
class AuditResult:
    owner: str
    repo: str
    reports: list[ReportData]


@dataclass(frozen=True)
class ReviewTarget:
    kind: str
    label: str
    report: ReportData
    row: dict[str, str]


def run_browser(reports_dir: Path) -> None:
    SpringCleanBrowser(reports_dir=reports_dir).run()


def load_reports(path: Path) -> list[ReportData]:
    target = path.expanduser()
    if target.is_dir():
        return load_latest_report_bundle(target)
    if target.is_file() and target.name.endswith(SUMMARY_SUFFIX):
        return load_report_bundle(target.parent, target.name[: -len(SUMMARY_SUFFIX)])
    if target.is_file() and target.suffix.lower() == ".csv":
        return [load_csv_report(target)]
    raise SpringCleanError(f"Could not find a report CSV, summary, or directory at {path}.")


def load_latest_report_bundle(reports_dir: Path) -> list[ReportData]:
    sources = report_sources(reports_dir)
    if not sources:
        raise SpringCleanError(f"No Spring Clean CSV reports found in {reports_dir}.")
    return load_report_source(sources[0])


def report_sources(reports_dir: Path) -> list[ReportSource]:
    bundles = report_bundles(reports_dir)
    sources = [
        ReportSource(
            prefix=prefix,
            reports_dir=reports_dir,
            branch_path=paths.get(BRANCH_KIND),
            pr_path=paths.get(PR_KIND),
            summary_path=paths.get("summary"),
            modified_at=max(path.stat().st_mtime for path in paths.values()),
        )
        for prefix, paths in bundles.items()
        if BRANCH_KIND in paths or PR_KIND in paths
    ]
    return sorted(sources, key=lambda source: source.modified_at, reverse=True)


def report_bundles(reports_dir: Path) -> dict[str, dict[str, Path]]:
    bundles: dict[str, dict[str, Path]] = {}
    for path in reports_dir.glob("*"):
        if path.name.endswith(BRANCH_SUFFIX):
            prefix = path.name[: -len(BRANCH_SUFFIX)]
            bundles.setdefault(prefix, {})[BRANCH_KIND] = path
        elif path.name.endswith(PR_SUFFIX):
            prefix = path.name[: -len(PR_SUFFIX)]
            bundles.setdefault(prefix, {})[PR_KIND] = path
        elif path.name.endswith(SUMMARY_SUFFIX):
            prefix = path.name[: -len(SUMMARY_SUFFIX)]
            bundles.setdefault(prefix, {})["summary"] = path
    return bundles


def load_report_source(source: ReportSource) -> list[ReportData]:
    reports = []
    if source.branch_path:
        reports.append(load_csv_report(source.branch_path, BRANCH_KIND))
    if source.pr_path:
        reports.append(load_csv_report(source.pr_path, PR_KIND))
    if not reports:
        raise SpringCleanError(f"No branch or pull request CSV reports found for {source.prefix}.")
    return reports


def delete_report_source(source: ReportSource) -> int:
    deleted = 0
    for path in report_source_paths(source):
        if path.exists():
            path.unlink()
            deleted += 1
    return deleted


def report_source_paths(source: ReportSource) -> list[Path]:
    return [path for path in (source.branch_path, source.pr_path, source.summary_path) if path is not None]


def load_report_bundle(reports_dir: Path, prefix: str) -> list[ReportData]:
    source = report_source_for_prefix(reports_dir, prefix)
    if source is None:
        raise SpringCleanError(f"No branch or pull request CSV reports found for {prefix}.")
    return load_report_source(source)


def report_source_for_prefix(reports_dir: Path, prefix: str) -> ReportSource | None:
    for source in report_sources(reports_dir):
        if source.prefix == prefix:
            return source
    return None


def load_csv_report(path: Path, expected_kind: str | None = None) -> ReportData:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]

    fieldnames = reader.fieldnames or []
    kind = expected_kind or detect_report_kind(path, fieldnames)
    return ReportData(kind=kind, path=path, rows=rows, fieldnames=fieldnames)


def detect_report_kind(path: Path, fields: list[str]) -> str:
    field_set = set(fields)
    if {"branch", "github_branch_bucket"}.issubset(field_set):
        return BRANCH_KIND
    if {"number", "title", "head_branch"}.issubset(field_set):
        return PR_KIND
    raise SpringCleanError(f"Could not identify report type for {path}.")


def list_github_repositories(client: GitHubClient) -> list[dict[str, Any]]:
    return client.paged(
        "/user/repos",
        {
            "affiliation": "owner,collaborator,organization_member",
            "sort": "updated",
            "direction": "desc",
        },
    )


def audit_github_repository(owner: str, repo: str, token: str, reports_dir: Path) -> AuditResult:
    audit_repo(
        client=GitHubClient(token=token),
        owner=owner,
        repo=repo,
        include_branches=True,
        include_prs=True,
        out_dir=reports_dir,
        stale_days=DEFAULT_STALE_DAYS,
    )
    return AuditResult(owner=owner, repo=repo, reports=load_latest_report_bundle(reports_dir))


class DeleteReportConfirm(ModalScreen[bool]):
    CSS = """
    DeleteReportConfirm {
        align: center middle;
    }

    #delete-dialog {
        width: 72;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        border: thick $error;
        background: $surface;
    }

    #delete-title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    #delete-summary {
        margin-top: 1;
        margin-bottom: 1;
    }

    #delete-actions {
        height: auto;
        align-horizontal: right;
    }

    #delete-actions Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
        ("y", "confirm", "Delete"),
    ]

    def __init__(self, source: ReportSource) -> None:
        super().__init__()
        self.source = source

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog"):
            yield Static("Delete Report?", id="delete-title")
            yield Static(delete_report_summary(self.source), id="delete-summary")
            yield Static("This removes local Spring Clean report files. GitHub is not changed.")
            with Horizontal(id="delete-actions"):
                yield Button("Cancel", id="cancel-delete")
                yield Button("Delete", id="confirm-delete", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel-delete", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class SpringCleanBrowser(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #title {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
        text-style: bold;
    }

    #search {
        height: 3;
        margin: 0 1;
    }

    #loader {
        display: none;
        height: 1;
        margin: 0 1;
        color: $accent;
    }

    #workspace {
        height: 1fr;
    }

    #results {
        width: 3fr;
        height: 1fr;
    }

    #detail {
        width: 2fr;
        height: 1fr;
        padding: 1 2;
        border-left: solid $accent;
        overflow-y: auto;
    }

    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("o", "show_reports", "Reports"),
        ("b", "show_branches", "Branches"),
        ("p", "show_prs", "PRs"),
        ("g", "github_input", "Audit Repo"),
        ("l", "list_repos", "GitHub Repos"),
        ("d", "delete_report", "Delete/Close"),
        ("k", "mark_keep", "Keep"),
        ("r", "mark_review", "Review"),
        ("c", "comment_review", "Comment"),
        ("u", "clear_review", "Clear Tag"),
        ("s", "cycle_filter", "Filter"),
        ("a", "show_all", "All"),
        ("/", "focus_search", "Search"),
        ("enter", "select_row", "Select"),
        ("escape", "clear_search", "Clear"),
    ]

    def __init__(
        self,
        reports_dir: Path = Path("reports"),
        reports: list[ReportData] | None = None,
    ) -> None:
        super().__init__()
        self.reports_dir = reports_dir.expanduser()
        self.sources: list[ReportSource] = []
        self.repo_rows: list[dict[str, Any]] = []
        self.reports = {report.kind: report for report in reports or []}
        self.active_kind = report_start_kind(self.reports) if self.reports else SOURCE_KIND
        self.filter_mode = "all"
        self.search_text = ""
        self.command_mode: str | None = None
        self.visible_rows: list[dict[str, Any]] = []
        self.visible_sources: list[ReportSource] = []
        self.message = ""
        self.loading_message = ""
        self.pending_review_target: ReviewTarget | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="title")
        yield Input(placeholder="Search reports or repositories", id="search")
        yield LoadingIndicator(id="loader")
        with Horizontal(id="workspace"):
            yield DataTable(id="results")
            yield Static("", id="detail")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        if self.reports:
            self.refresh_report()
        else:
            self.refresh_sources()
        table.focus()

    def action_show_reports(self) -> None:
        self.active_kind = SOURCE_KIND
        self.filter_mode = "all"
        self.search_text = ""
        self.reset_input("Search reports by repo, timestamp, report type, or file name")
        self.refresh_sources()

    def action_show_branches(self) -> None:
        if BRANCH_KIND in self.reports:
            self.active_kind = BRANCH_KIND
            self.filter_mode = "all"
            self.reset_input("Search branch rows")
            self.refresh_report()

    def action_show_prs(self) -> None:
        if PR_KIND in self.reports:
            self.active_kind = PR_KIND
            self.filter_mode = "all"
            self.reset_input("Search pull request rows")
            self.refresh_report()

    def action_github_input(self) -> None:
        self.command_mode = "audit_repo"
        command = self.query_one("#search", Input)
        command.value = ""
        command.placeholder = "Enter owner/repo or GitHub URL, then press Enter"
        command.focus()
        self.message = "Audit will write branch and open/draft PR reports, then load the result."
        self.update_status()

    def action_list_repos(self) -> None:
        try:
            token = github_token()
            if not token:
                raise SpringCleanError("Missing GITHUB_TOKEN. Add it to .env or set it in your shell.")
        except SpringCleanError as exc:
            self.message = str(exc)
            self.update_status()
            return

        self.active_kind = GITHUB_REPO_KIND
        self.filter_mode = "all"
        self.search_text = ""
        self.reset_input("Search GitHub repositories")
        self.repo_rows = []
        self.visible_rows = []
        self.render_table(GITHUB_REPO_KIND, [])
        self.update_title("GitHub Repositories")
        self.show_loading("Loading repositories from GitHub. This may take a moment for large orgs.")
        self.run_worker(
            lambda: list_github_repositories(GitHubClient(token=token)),
            name="list_github_repos",
            group="github",
            exclusive=True,
            thread=True,
        )

    def action_delete_report(self) -> None:
        if self.active_kind in {BRANCH_KIND, PR_KIND}:
            self.mark_selected_review(delete_action(self.active_kind))
            return

        if self.active_kind != SOURCE_KIND:
            self.message = "Open reports with o before deleting a report."
            self.update_status()
            return

        source = self.selected_report_source()
        if source is None:
            self.message = "No report selected."
            self.update_status()
            return

        self.push_screen(
            DeleteReportConfirm(source),
            callback=lambda confirmed, source=source: self.delete_report_after_confirmation(source, confirmed),
        )

    def action_mark_keep(self) -> None:
        self.mark_selected_review("keep")

    def action_mark_review(self) -> None:
        self.mark_selected_review("review")

    def action_clear_review(self) -> None:
        target = self.selected_review_target()
        if target is None:
            self.message = "Select a branch or pull request row first."
            self.update_status()
            return

        target.row["review_action"] = ""
        target.row["review_comment"] = ""
        save_csv_report(target.report)
        self.message = f"Cleared review tag for {target.label}."
        self.refresh_report()

    def action_comment_review(self) -> None:
        target = self.selected_review_target()
        if target is None:
            self.message = "Select a branch or pull request row first."
            self.update_status()
            return

        self.pending_review_target = target
        self.command_mode = "review_comment"
        command = self.query_one("#search", Input)
        command.value = target.row.get("review_comment", "")
        command.placeholder = "Enter a review comment, then press Enter"
        command.focus()
        self.message = f"Editing comment for {target.label}."
        self.update_status()

    def action_cycle_filter(self) -> None:
        modes = filter_modes(self.active_kind)
        index = modes.index(self.filter_mode) if self.filter_mode in modes else 0
        self.filter_mode = modes[(index + 1) % len(modes)]
        self.refresh_active_view()

    def action_show_all(self) -> None:
        self.filter_mode = "all"
        self.refresh_active_view()

    def action_focus_search(self) -> None:
        self.command_mode = None
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        self.command_mode = None
        self.pending_review_target = None
        self.search_text = ""
        self.reset_input(input_placeholder(self.active_kind))
        self.refresh_active_view()
        self.query_one("#results", DataTable).focus()

    def action_select_row(self) -> None:
        table = self.query_one("#results", DataTable)
        self.select_index(table.cursor_row)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search" or self.command_mode:
            return
        self.search_text = event.value
        try:
            self.refresh_active_view()
        except NoMatches:
            return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search":
            return
        if self.command_mode == "audit_repo":
            self.command_mode = None
            self.run_audit(event.value)
        elif self.command_mode == "review_comment":
            target = self.pending_review_target
            self.command_mode = None
            self.pending_review_target = None
            self.apply_review_comment(target, event.value)
            self.reset_input(input_placeholder(self.active_kind), self.search_text)
            self.query_one("#results", DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_detail_for_index(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.select_index(event.cursor_row)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "list_github_repos":
            self.handle_repo_list_worker(event)
        elif event.worker.name == "audit_repo":
            self.handle_audit_worker(event)

    def handle_repo_list_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self.hide_loading()
            self.repo_rows = event.worker.result
            self.message = f"Loaded {len(self.repo_rows)} repositories."
            self.refresh_repos()
        elif event.state == WorkerState.ERROR:
            self.hide_loading()
            error = event.worker.error
            if isinstance(error, SpringCleanError):
                self.message = str(error)
            else:
                self.message = f"Could not load repositories: {error}"
            self.update_status()
            self.update_detail_for_index(0)
        elif event.state == WorkerState.CANCELLED:
            self.hide_loading()
            self.message = "Repository loading cancelled."
            self.update_status()

    def handle_audit_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self.hide_loading()
            result = event.worker.result
            self.reports = {report.kind: report for report in result.reports}
            self.active_kind = report_start_kind(self.reports)
            self.filter_mode = "all"
            self.search_text = ""
            self.message = f"Audit complete for {result.owner}/{result.repo}."
            self.reset_input(input_placeholder(self.active_kind))
            self.refresh_report()
        elif event.state == WorkerState.ERROR:
            self.hide_loading()
            error = event.worker.error
            if isinstance(error, SpringCleanError):
                self.message = str(error)
            else:
                self.message = f"Could not audit repository: {error}"
            self.update_status()
            self.update_detail_for_index(0)
        elif event.state == WorkerState.CANCELLED:
            self.hide_loading()
            self.message = "Repository audit cancelled."
            self.update_status()

    def refresh_active_view(self) -> None:
        if self.active_kind == SOURCE_KIND:
            self.refresh_sources()
        elif self.active_kind == GITHUB_REPO_KIND:
            self.refresh_repos()
        else:
            self.refresh_report()

    def refresh_sources(self) -> None:
        self.sources = report_sources(self.reports_dir)
        query = self.search_text.strip().lower()
        self.visible_sources = [
            source for source in self.sources if not query or query in searchable_text(report_source_row(source))
        ]
        self.visible_rows = [report_source_row(source) for source in self.visible_sources]
        self.render_table(SOURCE_KIND, self.visible_rows)
        self.update_title("Reports")
        self.update_status()
        self.update_detail_for_index(0)

    def refresh_repos(self) -> None:
        query = self.search_text.strip().lower()
        self.visible_rows = [
            row
            for row in self.repo_rows
            if row_matches_filter(row, GITHUB_REPO_KIND, self.filter_mode)
            and (not query or query in searchable_text(row))
        ]
        self.render_table(GITHUB_REPO_KIND, self.visible_rows)
        self.update_title("GitHub Repositories")
        self.update_status()
        self.update_detail_for_index(0)

    def refresh_report(self) -> None:
        report = self.reports[self.active_kind]
        self.visible_rows = filtered_rows(report.rows, self.active_kind, self.search_text, self.filter_mode)
        self.render_table(self.active_kind, self.visible_rows)
        self.update_title(title_text(report))
        self.update_status(report)
        self.update_detail_for_index(0)

    def render_table(self, kind: str, rows: list[dict[str, Any]]) -> None:
        table = self.query_one("#results", DataTable)
        table.clear(columns=True)
        for column in table_columns(kind):
            table.add_column(column)
        for index, row in enumerate(rows):
            table.add_row(*row_cells(kind, row), key=str(index))

    def update_title(self, value: str) -> None:
        self.query_one("#title", Static).update(Text(value, style="bold"))

    def update_status(self, report: ReportData | None = None) -> None:
        status = status_text(
            active_kind=self.active_kind,
            visible_count=len(self.visible_rows),
            total_count=total_count(self.active_kind, self.sources, self.repo_rows, report),
            filter_mode=self.filter_mode,
        )
        if self.message:
            status = f"{status} | {self.message}"
        self.query_one("#status", Static).update(status)

    def show_loading(self, message: str) -> None:
        self.loading_message = message
        self.message = message
        self.query_one("#loader", LoadingIndicator).display = True
        self.query_one("#detail", Static).update(f"{message}\n\nResults will appear here when this completes.")
        self.update_status()

    def hide_loading(self) -> None:
        self.loading_message = ""
        self.query_one("#loader", LoadingIndicator).display = False

    def update_detail_for_index(self, index: int) -> None:
        try:
            detail = self.query_one("#detail", Static)
        except NoMatches:
            return
        if self.loading_message:
            detail.update(f"{self.loading_message}\n\nResults will appear here when this completes.")
            return
        if not self.visible_rows:
            detail.update(empty_detail_text(self.active_kind, self.reports_dir))
            return

        bounded_index = min(max(index, 0), len(self.visible_rows) - 1)
        if self.active_kind == SOURCE_KIND:
            detail.update(report_source_detail(self.visible_sources[bounded_index]))
        elif self.active_kind == GITHUB_REPO_KIND:
            detail.update(github_repo_detail(self.visible_rows[bounded_index]))
        else:
            detail.update(detail_text(self.active_kind, self.visible_rows[bounded_index]))

    def select_index(self, index: int) -> None:
        if index < 0 or not self.visible_rows:
            return
        bounded_index = min(index, len(self.visible_rows) - 1)
        if self.active_kind == SOURCE_KIND:
            self.load_source(self.visible_sources[bounded_index])
        elif self.active_kind == GITHUB_REPO_KIND:
            self.run_audit(str(self.visible_rows[bounded_index].get("full_name", "")))
        else:
            self.update_detail_for_index(bounded_index)

    def selected_report_source(self) -> ReportSource | None:
        if self.active_kind != SOURCE_KIND or not self.visible_sources:
            return None
        table = self.query_one("#results", DataTable)
        index = min(max(table.cursor_row, 0), len(self.visible_sources) - 1)
        return self.visible_sources[index]

    def selected_review_target(self) -> ReviewTarget | None:
        if self.active_kind not in {BRANCH_KIND, PR_KIND} or not self.visible_rows:
            return None
        table = self.query_one("#results", DataTable)
        index = min(max(table.cursor_row, 0), len(self.visible_rows) - 1)
        row = self.visible_rows[index]
        report = self.reports[self.active_kind]
        return ReviewTarget(
            kind=self.active_kind,
            label=review_target_label(self.active_kind, row),
            report=report,
            row=row,
        )

    def mark_selected_review(self, action: str) -> None:
        target = self.selected_review_target()
        if target is None:
            self.message = "Select a branch or pull request row first."
            self.update_status()
            return

        target.row["review_action"] = action
        target.row.setdefault("review_comment", "")
        save_csv_report(target.report)
        self.message = f"Marked {target.label} as {action}."
        self.refresh_report()

    def apply_review_comment(self, target: ReviewTarget | None, comment: str) -> None:
        if target is None:
            self.message = "No branch or pull request row selected."
            self.update_status()
            return

        target.row.setdefault("review_action", "")
        target.row["review_comment"] = comment
        save_csv_report(target.report)
        self.message = f"Updated comment for {target.label}."
        self.refresh_report()

    def delete_report_after_confirmation(self, source: ReportSource, confirmed: bool | None) -> None:
        if not confirmed:
            self.message = "Delete cancelled."
            self.update_status()
            return

        deleted = delete_report_source(source)
        self.message = f"Deleted {deleted} report file{'s' if deleted != 1 else ''} for {source.prefix}."
        self.refresh_sources()

    def load_source(self, source: ReportSource) -> None:
        try:
            self.reports = {report.kind: report for report in load_report_source(source)}
        except SpringCleanError as exc:
            self.message = str(exc)
            self.update_status()
            return
        self.active_kind = report_start_kind(self.reports)
        self.filter_mode = "all"
        self.search_text = ""
        self.message = f"Loaded {source.prefix}."
        self.reset_input(input_placeholder(self.active_kind))
        self.refresh_report()

    def run_audit(self, repo_ref: str) -> None:
        try:
            owner, repo = parse_repo_reference(repo_ref)
            token = github_token()
            if not token:
                raise SpringCleanError("Missing GITHUB_TOKEN. Add it to .env or set it in your shell.")
        except SpringCleanError as exc:
            self.message = str(exc)
            self.update_status()
            return

        self.show_loading(f"Auditing {owner}/{repo}. Collecting branches and open/draft pull requests.")
        self.run_worker(
            lambda: audit_github_repository(owner, repo, token, self.reports_dir),
            name="audit_repo",
            group="github",
            exclusive=True,
            thread=True,
        )

    def reset_input(self, placeholder: str, value: str = "") -> None:
        command = self.query_one("#search", Input)
        command.value = value
        command.placeholder = placeholder
        self.command_mode = None


def report_start_kind(reports: dict[str, ReportData]) -> str:
    return BRANCH_KIND if BRANCH_KIND in reports else PR_KIND


def table_columns(kind: str) -> list[str]:
    if kind == SOURCE_KIND:
        return ["Repo", "Generated", "Reports", "Rows", "Report ID"]
    if kind == GITHUB_REPO_KIND:
        return ["Repository", "Private", "Archived", "Updated", "Default"]
    if kind == BRANCH_KIND:
        return ["Branch", "Age", "Bucket", "Status", "Review", "Owner", "PRs", "Protected"]
    return ["PR", "Title", "State", "Draft", "Updated", "Author", "Status", "Review"]


def row_cells(kind: str, row: dict[str, Any]) -> list[str]:
    if kind == SOURCE_KIND:
        return [
            str(row.get("repo", "")),
            str(row.get("generated", "")),
            str(row.get("reports", "")),
            str(row.get("rows", "")),
            str(row.get("report_id", "")),
        ]
    if kind == GITHUB_REPO_KIND:
        return [
            str(row.get("full_name", "")),
            str(row.get("private", "")),
            str(row.get("archived", "")),
            str(row.get("updated_at", "")),
            str(row.get("default_branch", "")),
        ]
    if kind == BRANCH_KIND:
        return [
            str(row.get("branch", "")),
            str(row.get("days_since_last_commit", "")),
            str(row.get("github_branch_bucket", "")),
            str(row.get("cleanup_status", "")),
            str(row.get("review_action", "")),
            str(row.get("branch_created_by", "")),
            str(row.get("associated_pr_numbers", "")),
            str(row.get("protected", "")),
        ]
    return [
        prefixed_pr_number(str(row.get("number", ""))),
        str(row.get("title", "")),
        str(row.get("state", "")),
        str(row.get("draft", "")),
        str(row.get("days_since_updated", "")),
        str(row.get("created_by", "")),
        str(row.get("cleanup_status", "")),
        str(row.get("review_action", "")),
    ]


def save_csv_report(report: ReportData) -> None:
    fields = list(report.fieldnames or csv_fieldnames(report.path))
    for field in ("review_action", "review_comment"):
        if field not in fields:
            fields.append(field)
    for row in report.rows:
        for field in row:
            if field not in fields:
                fields.append(field)

    tmp_path = report.path.with_name(f"{report.path.name}.tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report.rows)
    tmp_path.replace(report.path)


def csv_fieldnames(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return csv.DictReader(handle).fieldnames or []


def delete_action(kind: str) -> str:
    return "close" if kind == PR_KIND else "delete"


def review_target_label(kind: str, row: dict[str, Any]) -> str:
    if kind == BRANCH_KIND:
        return str(row.get("branch", "branch"))
    return prefixed_pr_number(str(row.get("number", ""))) or "pull request"


def report_source_row(source: ReportSource) -> dict[str, str]:
    reports = source_report_names(source)
    return {
        "repo": repo_from_source(source),
        "generated": generated_from_prefix(source.prefix),
        "reports": ", ".join(reports),
        "rows": str(report_source_row_count(source)),
        "report_id": source.prefix,
        "modified": format_timestamp(source.modified_at),
    }


def source_report_names(source: ReportSource) -> list[str]:
    reports = []
    if source.branch_path:
        reports.append("branches")
    if source.pr_path:
        reports.append("pull requests")
    return reports


def report_source_row_count(source: ReportSource) -> int:
    total = 0
    for path in (source.branch_path, source.pr_path):
        if path:
            total += csv_row_count(path)
    return total


def repo_from_source(source: ReportSource) -> str:
    for path in (source.branch_path, source.pr_path):
        if path:
            repo = first_csv_value(path, "repo")
            if repo:
                return repo
    return repo_from_prefix(source.prefix)


def first_csv_value(path: Path, field: str) -> str:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader, None)
        if row:
            return row.get(field, "")
    return ""


def csv_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def repo_from_prefix(prefix: str) -> str:
    parts = prefix.rsplit("_", 1)
    if len(parts) != 2:
        return prefix
    return parts[0].replace("_", "/")


def generated_from_prefix(prefix: str) -> str:
    parts = prefix.rsplit("_", 1)
    if len(parts) != 2:
        return ""
    try:
        generated_at = datetime.strptime(parts[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return parts[1]
    return generated_at.strftime("%Y-%m-%d %H:%M UTC")


def filtered_rows(
    rows: list[dict[str, str]],
    kind: str,
    search_text: str,
    filter_mode: str,
) -> list[dict[str, str]]:
    query = search_text.strip().lower()
    return [
        row
        for row in rows
        if row_matches_filter(row, kind, filter_mode) and (not query or query in searchable_text(row))
    ]


def row_matches_filter(row: dict[str, Any], kind: str, filter_mode: str) -> bool:
    if filter_mode == "all":
        return True
    if kind == BRANCH_KIND:
        if filter_mode == "stale":
            return row.get("github_branch_bucket") == "stale"
        if filter_mode == "candidates":
            return str(row.get("cleanup_status", "")).startswith("candidate_")
        if filter_mode == "no_pr":
            return row.get("github_branch_bucket") == "stale" and not row.get("associated_pr_numbers")
    if kind == PR_KIND:
        if filter_mode == "stale":
            return row.get("cleanup_status") in {"open_stale", "draft_stale"}
        if filter_mode == "draft":
            return is_truthy(str(row.get("draft", "")))
    if kind == GITHUB_REPO_KIND:
        if filter_mode == "private":
            return bool(row.get("private"))
        if filter_mode == "archived":
            return bool(row.get("archived"))
    return True


def searchable_text(row: dict[str, Any]) -> str:
    return " ".join(str(value).lower() for value in row.values())


def detail_text(kind: str, row: dict[str, str]) -> str:
    if kind == BRANCH_KIND:
        values = [
            ("Branch", row.get("branch", "")),
            ("Repo", row.get("repo", "")),
            ("Context owner", source_value(row.get("branch_created_by", ""), row.get("branch_created_by_source", ""))),
            ("Cleanup status", row.get("cleanup_status", "")),
            ("Cleanup reason", row.get("cleanup_reason", "")),
            ("Bucket", row.get("github_branch_bucket", "")),
            ("Last commit", source_value(row.get("last_commit_sha", ""), row.get("last_commit_date", ""))),
            ("Last author", row.get("last_author", "")),
            ("Last committer", row.get("last_committer", "")),
            ("Days since commit", row.get("days_since_last_commit", "")),
            ("Default branch", row.get("is_default", "")),
            ("Protected", row.get("protected", "")),
            ("Associated PRs", row.get("associated_pr_numbers", "")),
            ("Associated PR authors", row.get("associated_pr_authors", "")),
            ("Associated PR states", row.get("associated_pr_states", "")),
            ("Review action", row.get("review_action", "")),
            ("Review comment", row.get("review_comment", "")),
            ("Branch URL", row.get("branch_url", "")),
            ("Compare URL", row.get("compare_url", "")),
            ("PR URLs", row.get("associated_pr_urls", "")),
        ]
    else:
        values = [
            ("Pull request", f"{prefixed_pr_number(row.get('number', ''))} {row.get('title', '')}".strip()),
            ("Repo", row.get("repo", "")),
            ("Created by", row.get("created_by", "")),
            ("Cleanup status", row.get("cleanup_status", "")),
            ("Cleanup reason", row.get("cleanup_reason", "")),
            ("State", row.get("state", "")),
            ("Draft", row.get("draft", "")),
            ("Base branch", row.get("base_branch", "")),
            ("Head branch", row.get("head_branch", "")),
            ("Head repo", row.get("head_repo", "")),
            ("Created at", row.get("created_at", "")),
            ("Updated at", row.get("updated_at", "")),
            ("Days since created", row.get("days_since_created", "")),
            ("Days since updated", row.get("days_since_updated", "")),
            ("Days open", row.get("days_open", "")),
            ("Review action", row.get("review_action", "")),
            ("Review comment", row.get("review_comment", "")),
            ("URL", row.get("url", "")),
        ]
    return "\n".join(format_detail_line(label, value) for label, value in values if value not in (None, ""))


def report_source_detail(source: ReportSource) -> str:
    values = [
        ("Repo", repo_from_source(source)),
        ("Generated", generated_from_prefix(source.prefix)),
        ("Reports", ", ".join(source_report_names(source))),
        ("Rows", str(report_source_row_count(source))),
        ("Modified", format_timestamp(source.modified_at)),
        ("Summary", str(source.summary_path or "")),
        ("Branches CSV", str(source.branch_path or "")),
        ("Pull Requests CSV", str(source.pr_path or "")),
    ]
    return "\n".join(format_detail_line(label, value) for label, value in values if value)


def delete_report_summary(source: ReportSource) -> str:
    values = [
        ("Repo", repo_from_source(source)),
        ("Generated", generated_from_prefix(source.prefix)),
    ]
    return "\n".join(format_detail_line(label, value) for label, value in values if value)


def github_repo_detail(row: dict[str, Any]) -> str:
    values = [
        ("Repository", row.get("full_name", "")),
        ("Private", str(row.get("private", ""))),
        ("Archived", str(row.get("archived", ""))),
        ("Default branch", row.get("default_branch", "")),
        ("Updated at", row.get("updated_at", "")),
        ("Description", row.get("description", "")),
        ("URL", row.get("html_url", "")),
    ]
    return "\n".join(format_detail_line(label, str(value)) for label, value in values if value not in (None, ""))


def empty_detail_text(kind: str, reports_dir: Path) -> str:
    if kind == SOURCE_KIND:
        return (
            f"No Spring Clean reports found in {reports_dir}.\nPress g to audit a repository or l to list GitHub repos."
        )
    if kind == GITHUB_REPO_KIND:
        return "No repositories match the current search or filter."
    return "No rows match the current search or filter."


def title_text(report: ReportData) -> str:
    name = "Branches" if report.kind == BRANCH_KIND else "Open Pull Requests"
    return f"{name} - {report.path.name}"


def status_text(active_kind: str, visible_count: int, total_count: int, filter_mode: str) -> str:
    mode = filter_mode.replace("_", " ")
    shortcuts = "o reports | g audit | l repos | b branches | p PRs | / search | s filter | q quit"
    if active_kind in {BRANCH_KIND, PR_KIND}:
        shortcuts = f"d {delete_action(active_kind)} | k keep | r review | c comment | u clear | {shortcuts}"
    return f"{visible_count}/{total_count} rows | view: {view_name(active_kind)} | filter: {mode} | {shortcuts}"


def total_count(
    active_kind: str,
    sources: list[ReportSource],
    repo_rows: list[dict[str, Any]],
    report: ReportData | None,
) -> int:
    if active_kind == SOURCE_KIND:
        return len(sources)
    if active_kind == GITHUB_REPO_KIND:
        return len(repo_rows)
    return len(report.rows) if report else 0


def filter_modes(kind: str) -> list[str]:
    if kind == BRANCH_KIND:
        return ["all", "stale", "candidates", "no_pr"]
    if kind == PR_KIND:
        return ["all", "stale", "draft"]
    if kind == GITHUB_REPO_KIND:
        return ["all", "private", "archived"]
    return ["all"]


def branch_filter_modes() -> list[str]:
    return filter_modes(BRANCH_KIND)


def pr_filter_modes() -> list[str]:
    return filter_modes(PR_KIND)


def input_placeholder(kind: str) -> str:
    if kind == SOURCE_KIND:
        return "Search reports by repo, timestamp, report type, or file name"
    if kind == GITHUB_REPO_KIND:
        return "Search GitHub repositories"
    if kind == BRANCH_KIND:
        return "Search branch rows"
    return "Search pull request rows"


def view_name(kind: str) -> str:
    if kind == SOURCE_KIND:
        return "reports"
    if kind == GITHUB_REPO_KIND:
        return "github repos"
    if kind == BRANCH_KIND:
        return "branches"
    return "pull requests"


def format_detail_line(label: str, value: str) -> str:
    return f"{label}: {value}"


def source_value(value: str, source: str) -> str:
    if value and source:
        return f"{value} ({source})"
    return value or source


def prefixed_pr_number(value: str) -> str:
    return f"#{value}" if value else ""


def is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
