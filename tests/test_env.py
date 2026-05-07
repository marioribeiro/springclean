from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from springclean.env import github_token, load_dotenv
from springclean.errors import SpringCleanError


def test_load_dotenv_supports_comments_and_quoted_values(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "\n# local token\nGITHUB_TOKEN='abc123'\nOTHER=value\n",
        encoding="utf-8",
    )

    assert load_dotenv(path) == {"GITHUB_TOKEN": "abc123", "OTHER": "value"}


def test_load_dotenv_rejects_invalid_lines(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("GITHUB_TOKEN\n", encoding="utf-8")

    with pytest.raises(SpringCleanError):
        load_dotenv(path)


def test_load_dotenv_rejects_missing_key_and_handles_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / ".env.missing"
    invalid = tmp_path / ".env"
    invalid.write_text("=value\n", encoding="utf-8")

    assert load_dotenv(missing) == {}
    with pytest.raises(SpringCleanError, match="missing key"):
        load_dotenv(invalid)


def test_github_token_prefers_environment() -> None:
    with patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"}):
        assert github_token() == "env-token"
