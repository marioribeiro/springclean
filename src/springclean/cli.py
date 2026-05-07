from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .env import github_token
from .errors import SpringCleanError
from .github import GitHubClient
from .repo_refs import parse_repo_reference
from .reports import DEFAULT_STALE_DAYS, audit_repo
from .tui import run_browser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command is None:
            run_browser(Path(args.reports_dir))
            return 0

        if not args.branch and not args.pr:
            parser.error("Choose at least one report: --branch and/or --pr.")

        if args.stale_days < 1:
            parser.error("--stale-days must be greater than zero.")

        owner, repo = parse_repo(args.repo)
        token = github_token()
        if not token:
            raise SpringCleanError("Missing GITHUB_TOKEN. Add it to .env or export it in your shell.")
        client = GitHubClient(token=token)
        audit_repo(
            client=client,
            owner=owner,
            repo=repo,
            include_branches=args.branch,
            include_prs=args.pr,
            out_dir=Path(args.out),
            stale_days=args.stale_days,
        )
    except SpringCleanError as exc:
        print(f"springclean: {exc}", file=sys.stderr)
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="springclean",
        description="Spring Clean writes and browses GitHub repository cleanup reports.",
        epilog="Run without a subcommand to open the terminal browser.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--reports-dir",
        dest="reports_dir",
        default="reports",
        help="Reports directory used by the terminal browser. Defaults to ./reports.",
    )
    subparsers = parser.add_subparsers(dest="command")

    repo_parser = subparsers.add_parser("repo", help="Audit one repository.")
    repo_parser.add_argument("repo", help="Repository in owner/name format.")
    repo_parser.add_argument("--branch", dest="branch", action="store_true", help="Write branch report.")
    repo_parser.add_argument(
        "--pr",
        dest="pr",
        action="store_true",
        help="Write open and draft pull request report.",
    )
    repo_parser.add_argument(
        "--out",
        default="reports",
        help="Output directory for report files. Defaults to ./reports.",
    )
    repo_parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Days without activity before a branch or PR is stale. Defaults to {DEFAULT_STALE_DAYS}.",
    )

    return parser


def parse_repo(value: str) -> tuple[str, str]:
    return parse_repo_reference(value)
