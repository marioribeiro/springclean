from __future__ import annotations

import csv
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .errors import SpringCleanError

DEFAULT_STALE_DAYS = 90

Row = dict[str, Any]
RowPredicate = Callable[[Row], bool]


BRANCH_FIELDS = [
    "repo",
    "branch",
    "branch_url",
    "compare_url",
    "branch_created_by",
    "branch_created_by_source",
    "is_default",
    "protected",
    "last_commit_sha",
    "last_commit_date",
    "last_author",
    "last_committer",
    "days_since_last_commit",
    "github_branch_bucket",
    "associated_pr_numbers",
    "associated_pr_authors",
    "associated_pr_states",
    "associated_pr_urls",
    "cleanup_status",
    "cleanup_reason",
    "review_action",
    "review_comment",
]

PR_FIELDS = [
    "repo",
    "number",
    "title",
    "state",
    "draft",
    "created_by",
    "base_branch",
    "head_branch",
    "head_repo",
    "created_at",
    "updated_at",
    "closed_at",
    "merged_at",
    "days_since_created",
    "days_since_updated",
    "days_open",
    "merge_commit_sha",
    "url",
    "cleanup_status",
    "cleanup_reason",
    "review_action",
    "review_comment",
]


def audit_repo(
    client: Any,
    owner: str,
    repo: str,
    include_branches: bool,
    include_prs: bool,
    out_dir: Path,
    stale_days: int,
) -> None:
    full_repo = f"{owner}/{repo}"
    try:
        repo_info = client.get(f"/repos/{quote(owner)}/{quote(repo)}")
    except SpringCleanError as exc:
        raise SpringCleanError(
            f"Could not access {full_repo}. Check the owner/repo spelling and make sure "
            "GITHUB_TOKEN has access to that repository."
        ) from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    report_name = report_basename(owner, repo)
    branch_rows = None
    pr_rows = None

    if include_branches:
        print(f"Collecting branches for {full_repo}...", file=sys.stderr)
        branch_rows = collect_branch_rows(client, owner, repo, repo_info["default_branch"], stale_days)
        write_csv(out_dir / f"{report_name}_branches.csv", BRANCH_FIELDS, branch_rows)

    if include_prs:
        print(f"Collecting pull requests for {full_repo}...", file=sys.stderr)
        pr_rows = collect_pr_rows(client, owner, repo, stale_days)
        write_csv(out_dir / f"{report_name}_pull_requests.csv", PR_FIELDS, pr_rows)

    write_summary(out_dir / f"{report_name}_summary.md", full_repo, repo_info, stale_days, branch_rows, pr_rows)


def collect_branch_rows(
    client: Any,
    owner: str,
    repo: str,
    default_branch: str,
    stale_days: int,
) -> list[Row]:
    full_repo = f"{owner}/{repo}"
    branches = client.paged(f"/repos/{quote(owner)}/{quote(repo)}/branches")
    rows = []

    for branch in branches:
        name = branch["name"]
        sha = branch["commit"]["sha"]
        commit = client.get(f"/repos/{quote(owner)}/{quote(repo)}/commits/{quote(sha)}")
        prs = associated_pull_requests(client, owner, repo, name)
        commit_info = commit.get("commit", {})
        committer = commit_info.get("committer") or {}
        author = commit_info.get("author") or {}
        last_author = login_or_name(commit.get("author"), author)
        last_committer = login_or_name(commit.get("committer"), committer)
        last_commit_date = committer.get("date") or author.get("date")
        commit_age = days_since(last_commit_date)
        bucket = branch_bucket(name, default_branch, last_commit_date, stale_days)
        pr_states = [pr_state(pr) for pr in prs]
        pr_authors = unique_values((pr.get("user") or {}).get("login", "") for pr in prs)
        inferred_created_by, inferred_created_by_source = infer_branch_created_by(
            pr_authors=pr_authors,
            last_author=last_author,
            last_committer=last_committer,
        )
        cleanup_status, cleanup_reason = branch_cleanup_status(
            is_default=name == default_branch,
            protected=branch.get("protected", False),
            bucket=bucket,
            pr_states=pr_states,
            stale_days=stale_days,
        )

        rows.append(
            {
                "repo": full_repo,
                "branch": name,
                "branch_url": branch_url(owner, repo, name),
                "compare_url": compare_url(owner, repo, default_branch, name),
                "branch_created_by": inferred_created_by,
                "branch_created_by_source": inferred_created_by_source,
                "is_default": name == default_branch,
                "protected": branch.get("protected", False),
                "last_commit_sha": sha,
                "last_commit_date": last_commit_date or "",
                "last_author": last_author,
                "last_committer": last_committer,
                "days_since_last_commit": commit_age,
                "github_branch_bucket": bucket,
                "associated_pr_numbers": join_values(pr["number"] for pr in prs),
                "associated_pr_authors": join_values(pr_authors),
                "associated_pr_states": join_values(pr_states),
                "associated_pr_urls": join_values(pr["html_url"] for pr in prs),
                "cleanup_status": cleanup_status,
                "cleanup_reason": cleanup_reason,
                "review_action": "",
                "review_comment": "",
            }
        )

    return sorted(rows, key=branch_sort_key)


def collect_pr_rows(client: Any, owner: str, repo: str, stale_days: int) -> list[Row]:
    full_repo = f"{owner}/{repo}"
    prs = client.paged(f"/repos/{quote(owner)}/{quote(repo)}/pulls", {"state": "open"})
    rows = []

    for pr in prs:
        head = pr.get("head") or {}
        head_repo = head.get("repo") or {}
        base = pr.get("base") or {}
        state = pr_state(pr)
        days_updated = days_since(pr.get("updated_at"))
        cleanup_status, cleanup_reason = pr_cleanup_status(pr, state, days_updated, stale_days)
        rows.append(
            {
                "repo": full_repo,
                "number": pr.get("number", ""),
                "title": pr.get("title", ""),
                "state": state,
                "draft": pr.get("draft", False),
                "created_by": (pr.get("user") or {}).get("login", ""),
                "base_branch": base.get("ref", ""),
                "head_branch": head.get("ref", ""),
                "head_repo": head_repo.get("full_name", ""),
                "created_at": pr.get("created_at", ""),
                "updated_at": pr.get("updated_at", ""),
                "closed_at": pr.get("closed_at", ""),
                "merged_at": pr.get("merged_at", ""),
                "days_since_created": days_since(pr.get("created_at")),
                "days_since_updated": days_updated,
                "days_open": pr_days_open(pr),
                "merge_commit_sha": pr.get("merge_commit_sha", ""),
                "url": pr.get("html_url", ""),
                "cleanup_status": cleanup_status,
                "cleanup_reason": cleanup_reason,
                "review_action": "",
                "review_comment": "",
            }
        )

    return sorted(rows, key=lambda row: row["updated_at"] or "", reverse=True)


def associated_pull_requests(client: Any, owner: str, repo: str, branch_name: str) -> list[dict[str, Any]]:
    path_branch = quote(branch_name, safe="")
    try:
        return client.paged(f"/repos/{quote(owner)}/{quote(repo)}/commits/{path_branch}/pulls")
    except SpringCleanError as exc:
        print(f"Could not fetch associated PRs for {branch_name}: {exc}", file=sys.stderr)
        return []


def infer_branch_created_by(
    pr_authors: list[str],
    last_author: str,
    last_committer: str,
) -> tuple[str, str]:
    if pr_authors:
        return join_values(pr_authors), "associated_pr_author"
    if last_author:
        return last_author, "last_commit_author"
    if last_committer:
        return last_committer, "last_commit_committer"
    return "", "unknown"


def unique_values(values: Any) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        unique.append(str(value))
    return unique


def report_basename(owner: str, repo: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_filename(owner)}_{safe_filename(repo)}_{timestamp}"


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in value)


def branch_bucket(branch: str, default_branch: str, last_commit_date: str | None, stale_days: int) -> str:
    if branch == default_branch:
        return "default"

    age = days_since(last_commit_date)
    if age == "":
        return "unknown"
    return "stale" if int(age) > stale_days else "active"


def branch_cleanup_status(
    is_default: bool,
    protected: bool,
    bucket: str,
    pr_states: list[str],
    stale_days: int,
) -> tuple[str, str]:
    if is_default:
        return "keep_default", "Default branch."
    if protected:
        return "keep_protected", "Branch is protected."
    if bucket == "active":
        return "review_active", f"Branch has commit activity within {stale_days} days."
    if bucket == "unknown":
        return "review_unknown_activity", "Could not determine latest commit age."
    if "open" in pr_states:
        return "review_stale_open_pr", "Stale branch has at least one associated open PR."
    if "merged" in pr_states:
        return "candidate_stale_merged_pr", "Stale branch has at least one associated merged PR."
    if pr_states:
        return "candidate_stale_closed_pr", "Stale branch only has closed/unmerged associated PRs."
    return "candidate_stale_no_pr", "Stale branch has no associated PRs."


def pr_cleanup_status(
    pr: dict[str, Any],
    state: str,
    days_since_updated_value: int | str,
    stale_days: int,
) -> tuple[str, str]:
    if state == "merged":
        return "merged", "PR has been merged."
    if state == "closed":
        return "closed_unmerged", "PR was closed without being merged."

    is_stale = days_since_updated_value != "" and int(days_since_updated_value) > stale_days
    if pr.get("draft") and is_stale:
        return "draft_stale", f"Draft PR has no updates in more than {stale_days} days."
    if is_stale:
        return "open_stale", f"Open PR has no updates in more than {stale_days} days."
    if pr.get("draft"):
        return "draft_active", f"Draft PR was updated within {stale_days} days."
    return "open_active", f"Open PR was updated within {stale_days} days."


def branch_url(owner: str, repo: str, branch: str) -> str:
    return f"https://github.com/{owner}/{repo}/tree/{quote(branch, safe='')}"


def compare_url(owner: str, repo: str, default_branch: str, branch: str) -> str:
    if branch == default_branch:
        return ""
    return f"https://github.com/{owner}/{repo}/compare/{quote(default_branch, safe='')}...{quote(branch, safe='')}"


def branch_sort_key(row: Row) -> tuple[int, int]:
    if row["github_branch_bucket"] == "default":
        return (0, 0)
    days = row["days_since_last_commit"]
    return (1, int(days) if days != "" else sys.maxsize)


def days_since(value: str | None) -> int | str:
    if not value:
        return ""
    dt = parse_github_datetime(value)
    now = datetime.now(timezone.utc)
    return max(0, (now - dt).days)


def pr_days_open(pr: dict[str, Any]) -> int | str:
    created_at = pr.get("created_at")
    if not created_at:
        return ""

    closed_at = pr.get("merged_at") or pr.get("closed_at")
    start = parse_github_datetime(created_at)
    end = parse_github_datetime(closed_at) if closed_at else datetime.now(timezone.utc)
    return max(0, (end - start).days)


def parse_github_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def login_or_name(user: dict[str, Any] | None, git_identity: dict[str, Any]) -> str:
    if user and user.get("login"):
        return user["login"]
    return git_identity.get("name", "")


def pr_state(pr: dict[str, Any]) -> str:
    if pr.get("merged_at"):
        return "merged"
    return pr.get("state", "")


def join_values(values: Any) -> str:
    return ";".join(str(value) for value in values if value not in (None, ""))


def write_csv(path: Path, fields: list[str], rows: list[Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {path}", file=sys.stderr)


def write_summary(
    path: Path,
    full_repo: str,
    repo_info: dict[str, Any],
    stale_days: int,
    branch_rows: list[Row] | None,
    pr_rows: list[Row] | None,
) -> None:
    lines = [
        "# Spring Clean Summary",
        "",
        f"Repo: {full_repo}",
        f"Default branch: {repo_info.get('default_branch', '')}",
        f"Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Stale threshold: {stale_days} days",
        "",
    ]

    if branch_rows is not None:
        lines.extend(branch_summary(branch_rows))
        lines.append("")

    if pr_rows is not None:
        lines.extend(pr_summary(pr_rows))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote summary to {path}", file=sys.stderr)


def branch_summary(rows: list[Row]) -> list[str]:
    return [
        "## Branches",
        "",
        f"- Total: {len(rows)}",
        f"- Default/protected: {count_rows(rows, lambda row: row['is_default'] or row['protected'])}",
        f"- Active: {count_rows(rows, lambda row: row['github_branch_bucket'] == 'active')}",
        f"- Stale: {count_rows(rows, lambda row: row['github_branch_bucket'] == 'stale')}",
        f"- Stale with open PR: {count_rows(rows, lambda row: row_has_pr_state(row, 'open'))}",
        f"- Stale with merged PR: {count_rows(rows, lambda row: row_has_pr_state(row, 'merged'))}",
        f"- Stale with no PR: {count_rows(rows, stale_branch_without_pr)}",
        f"- Cleanup candidates: {count_rows(rows, lambda row: row['cleanup_status'].startswith('candidate_'))}",
        "",
        "### Branch Cleanup Status",
        "",
        *status_lines(rows),
    ]


def pr_summary(rows: list[Row]) -> list[str]:
    return [
        "## Open Pull Requests",
        "",
        f"- Total: {len(rows)}",
        f"- Ready for review: {count_rows(rows, lambda row: row['state'] == 'open' and not row['draft'])}",
        f"- Draft: {count_rows(rows, lambda row: row['draft'])}",
        f"- Open active: {count_rows(rows, lambda row: row['cleanup_status'] == 'open_active')}",
        f"- Open stale: {count_rows(rows, lambda row: row['cleanup_status'] == 'open_stale')}",
        f"- Draft active: {count_rows(rows, lambda row: row['cleanup_status'] == 'draft_active')}",
        f"- Draft stale: {count_rows(rows, lambda row: row['cleanup_status'] == 'draft_stale')}",
        "",
        "### PR Cleanup Status",
        "",
        *status_lines(rows),
    ]


def count_rows(rows: list[Row], predicate: RowPredicate) -> int:
    return sum(1 for row in rows if predicate(row))


def row_has_pr_state(row: Row, state: str) -> bool:
    if row["github_branch_bucket"] != "stale":
        return False
    return state in split_values(row["associated_pr_states"])


def stale_branch_without_pr(row: Row) -> bool:
    return row["github_branch_bucket"] == "stale" and not row["associated_pr_numbers"]


def split_values(value: str) -> list[str]:
    if not value:
        return []
    return [part for part in value.split(";") if part]


def status_lines(rows: list[Row]) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        status = row["cleanup_status"]
        counts[status] = counts.get(status, 0) + 1
    return [f"- {status}: {counts[status]}" for status in sorted(counts)]
