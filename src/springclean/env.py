from __future__ import annotations

import os
from pathlib import Path

from .errors import SpringCleanError


def github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or load_dotenv().get("GITHUB_TOKEN")


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    if not path.exists():
        return {}

    values = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SpringCleanError(f"Invalid .env line {line_number}: expected KEY=value.")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SpringCleanError(f"Invalid .env line {line_number}: missing key.")
        values[key] = unquote_env_value(value)

    return values


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
