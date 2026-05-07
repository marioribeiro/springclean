from __future__ import annotations

from urllib.parse import urlparse

from .errors import SpringCleanError


def parse_repo_reference(value: str) -> tuple[str, str]:
    repo_ref = value.strip()
    if not repo_ref:
        raise SpringCleanError("Repository must be in owner/name format.")

    if repo_ref.startswith("git@github.com:"):
        repo_ref = repo_ref.removeprefix("git@github.com:")
    elif "://" in repo_ref:
        parsed = urlparse(repo_ref)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise SpringCleanError("GitHub URL must use github.com.")
        repo_ref = parsed.path.strip("/")

    parts = [part for part in repo_ref.split("/") if part]
    if len(parts) < 2:
        raise SpringCleanError("Repository must be in owner/name format, for example marioribeiro/springclean.")

    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        raise SpringCleanError("Repository must be in owner/name format, for example marioribeiro/springclean.")
    return owner, repo
