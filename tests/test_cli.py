from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import pytest

from springclean.cli import main, parse_repo
from springclean.errors import SpringCleanError


def test_parse_repo_requires_owner_and_name() -> None:
    assert parse_repo("owner/repo") == ("owner", "repo")
    assert parse_repo("https://github.com/owner/repo/pull/1") == ("owner", "repo")
    with pytest.raises(SpringCleanError):
        parse_repo("owner")


def test_main_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(sys, "argv", ["springclean", "--version"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 0
    assert "springclean 0.1.0" in capsys.readouterr().out


def test_main_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(sys, "argv", ["springclean", "repo", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--branch" in help_text
    assert "--pr" in help_text


def test_main_runs_repo_audit() -> None:
    with (
        patch.object(sys, "argv", ["springclean", "repo", "owner/repo", "--branch", "--out", "reports"]),
        patch("springclean.cli.github_token", return_value="token"),
        patch("springclean.cli.GitHubClient") as client_class,
        patch("springclean.cli.audit_repo") as audit,
    ):
        client = client_class.return_value

        assert main() == 0

    audit.assert_called_once_with(
        client=client,
        owner="owner",
        repo="repo",
        include_branches=True,
        include_prs=False,
        out_dir=Path("reports"),
        stale_days=90,
    )


def test_main_runs_report_browser_by_default() -> None:
    with (
        patch.object(sys, "argv", ["springclean"]),
        patch("springclean.cli.run_browser") as run_browser,
    ):
        assert main() == 0

    run_browser.assert_called_once_with(Path("reports"))


def test_main_uses_configured_reports_dir_for_browser() -> None:
    with (
        patch.object(sys, "argv", ["springclean", "--reports-dir", "team-reports"]),
        patch("springclean.cli.run_browser") as run_browser,
    ):
        assert main() == 0

    run_browser.assert_called_once_with(Path("team-reports"))


def test_main_reports_missing_token() -> None:
    stderr = io.StringIO()
    with (
        patch.object(sys, "argv", ["springclean", "repo", "owner/repo", "--pr"]),
        patch("springclean.cli.github_token", return_value=None),
        redirect_stderr(stderr),
    ):
        assert main() == 1

    assert "Missing GITHUB_TOKEN" in stderr.getvalue()


def test_main_rejects_missing_report_selection() -> None:
    with patch.object(sys, "argv", ["springclean", "repo", "owner/repo"]):
        with pytest.raises(SystemExit):
            main()


def test_main_rejects_invalid_stale_days() -> None:
    with patch.object(sys, "argv", ["springclean", "repo", "owner/repo", "--pr", "--stale-days", "0"]):
        with pytest.raises(SystemExit):
            main()
