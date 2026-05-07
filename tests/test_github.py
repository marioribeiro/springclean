from __future__ import annotations

import io
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from springclean.errors import SpringCleanError
from springclean.github import GitHubClient

from .helpers import FakeUrlopenResponse, PagedClient


def test_get_decodes_json_and_headers() -> None:
    client = GitHubClient(token="secret", api_root="https://example.test")
    response = FakeUrlopenResponse(b'{"ok": true}', {"X-RateLimit-Remaining": "1"})

    with patch("springclean.github.urlopen", return_value=response) as urlopen:
        assert client.get("/repos/example", {"page": 1}) == {"ok": True}

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://example.test/repos/example?page=1"
    assert request.headers["Authorization"] == "Bearer secret"


def test_get_maps_network_errors() -> None:
    client = GitHubClient(token="secret")

    with patch("springclean.github.urlopen", side_effect=URLError("dns")):
        with pytest.raises(SpringCleanError, match="Could not reach GitHub API"):
            client.get("/repos/example")


def test_get_handles_empty_body() -> None:
    client = GitHubClient(token="secret")

    with patch("springclean.github.urlopen", return_value=FakeUrlopenResponse(b"")):
        assert client.get("/repos/example") is None


def test_get_maps_auth_http_errors() -> None:
    client = GitHubClient(token="secret")
    error = HTTPError(
        url="https://api.github.com/repos/example",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b'{"message":"Bad credentials"}'),
    )

    with patch("springclean.github.urlopen", side_effect=error):
        with pytest.raises(SpringCleanError, match="authentication failed"):
            client.get("/repos/example")


def test_get_maps_other_http_errors() -> None:
    client = GitHubClient(token="secret")

    for code, expected in [(403, "403"), (404, "not found"), (500, "500")]:
        error = HTTPError(
            url="https://api.github.com/repos/example",
            code=code,
            msg="Boom",
            hdrs=None,
            fp=io.BytesIO(b"not json"),
        )

        with patch("springclean.github.urlopen", side_effect=error):
            with pytest.raises(SpringCleanError, match=expected):
                client.get("/repos/example")


def test_waits_when_rate_limited() -> None:
    client = GitHubClient(token="secret")

    with (
        patch("springclean.github.time.time", return_value=100),
        patch("springclean.github.time.sleep") as sleep,
    ):
        client._maybe_wait_for_rate_limit({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "101"})

    sleep.assert_called_once_with(2)


def test_retries_http_rate_limit_with_retry_after() -> None:
    client = GitHubClient(token="secret")
    error = HTTPError(
        url="https://api.github.com/user/repos",
        code=429,
        msg="Too Many Requests",
        hdrs={"Retry-After": "3"},
        fp=io.BytesIO(b'{"message":"rate limited"}'),
    )
    response = FakeUrlopenResponse(b'{"ok": true}', {"X-RateLimit-Remaining": "1"})

    with (
        patch("springclean.github.urlopen", side_effect=[error, response]) as urlopen,
        patch("springclean.github.time.sleep") as sleep,
    ):
        assert client.get("/user/repos") == {"ok": True}

    assert urlopen.call_count == 2
    sleep.assert_called_once_with(3)


def test_retries_primary_rate_limit_until_reset() -> None:
    client = GitHubClient(token="secret")
    error = HTTPError(
        url="https://api.github.com/user/repos",
        code=403,
        msg="Forbidden",
        hdrs={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "101"},
        fp=io.BytesIO(b'{"message":"API rate limit exceeded"}'),
    )
    response = FakeUrlopenResponse(b'{"ok": true}', {"X-RateLimit-Remaining": "1"})

    with (
        patch("springclean.github.urlopen", side_effect=[error, response]),
        patch("springclean.github.time.time", return_value=100),
        patch("springclean.github.time.sleep") as sleep,
    ):
        assert client.get("/user/repos") == {"ok": True}

    sleep.assert_called_once_with(2)


def test_paged_combines_pages() -> None:
    first_page = [{"id": index} for index in range(100)]
    second_page = [{"id": 100}]
    client = PagedClient([first_page, second_page])

    rows = client.paged("/items", {"state": "open"})

    assert len(rows) == 101
    assert client.params_seen[0] == {"state": "open", "per_page": 100, "page": 1}
    assert client.params_seen[1] == {"state": "open", "per_page": 100, "page": 2}


def test_paged_requires_list_response() -> None:
    client = PagedClient([{"not": "a list"}])

    with pytest.raises(SpringCleanError, match="Expected a list response"):
        client.paged("/items")


def test_paged_stops_on_empty_page() -> None:
    client = PagedClient([[]])

    assert client.paged("/items") == []
