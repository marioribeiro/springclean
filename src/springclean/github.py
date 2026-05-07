from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import SpringCleanError

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
RATE_LIMIT_RETRY_CODES = {403, 429}
RATE_LIMIT_RETRIES = 2


@dataclass
class GitHubClient:
    token: str
    api_root: str = API_ROOT
    rate_limit_retries: int = RATE_LIMIT_RETRIES

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._url(path, params)
        request = Request(url, headers=self._headers())
        attempt = 0

        while True:
            try:
                with urlopen(request, timeout=30) as response:
                    self._maybe_wait_for_rate_limit(response.headers)
                    body = response.read().decode("utf-8")
                    break
            except HTTPError as exc:
                if self._should_retry_rate_limit(exc, attempt):
                    attempt += 1
                    continue
                self._raise_http_error(exc)
            except URLError as exc:
                raise SpringCleanError(f"Could not reach GitHub API: {exc.reason}") from exc

        if not body:
            return None
        return json.loads(body)

    def paged(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        params = dict(params or {})
        params["per_page"] = 100
        page = 1
        items: list[Any] = []

        while True:
            params["page"] = page
            batch = self.get(path, params)
            if not isinstance(batch, list):
                raise SpringCleanError(f"Expected a list response from {path}")
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        return items

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "springclean",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def _url(self, path: str, params: dict[str, Any] | None) -> str:
        url = f"{self.api_root}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return url

    def _maybe_wait_for_rate_limit(self, headers: Any) -> None:
        sleep_for = self._rate_limit_sleep_seconds(headers)
        if sleep_for is None:
            return

        print(f"GitHub rate limit reached. Sleeping for {sleep_for}s.", file=sys.stderr)
        time.sleep(sleep_for)

    def _should_retry_rate_limit(self, exc: HTTPError, attempt: int) -> bool:
        if exc.code not in RATE_LIMIT_RETRY_CODES or attempt >= self.rate_limit_retries:
            return False
        sleep_for = self._rate_limit_sleep_seconds(exc.headers)
        if sleep_for is None:
            return False

        print(f"GitHub rate limit reached. Sleeping for {sleep_for}s before retrying.", file=sys.stderr)
        time.sleep(sleep_for)
        return True

    def _rate_limit_sleep_seconds(self, headers: Any) -> int | None:
        retry_after = self._int_header(headers, "Retry-After")
        if retry_after is not None:
            return max(0, retry_after)

        remaining = self._header(headers, "X-RateLimit-Remaining")
        reset = self._int_header(headers, "X-RateLimit-Reset")
        if remaining != "0" or reset is None:
            return None

        return max(0, reset - int(time.time())) + 1

    def _int_header(self, headers: Any, name: str) -> int | None:
        value = self._header(headers, name)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _header(self, headers: Any, name: str) -> str | None:
        if headers is None:
            return None
        value = headers.get(name)
        if value is not None:
            return value
        lower_name = name.lower()
        for key, candidate in getattr(headers, "items", lambda: [])():
            if key.lower() == lower_name:
                return candidate
        return None

    def _raise_http_error(self, exc: HTTPError) -> None:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = payload.get("message", "")
        except Exception:
            detail = exc.reason

        if exc.code == 401:
            raise SpringCleanError("GitHub authentication failed. Check GITHUB_TOKEN.") from exc
        if exc.code == 403:
            raise SpringCleanError(f"GitHub API returned 403: {detail}") from exc
        if exc.code == 404:
            raise SpringCleanError(f"GitHub resource not found or not accessible: {detail}") from exc
        raise SpringCleanError(f"GitHub API returned {exc.code}: {detail}") from exc
