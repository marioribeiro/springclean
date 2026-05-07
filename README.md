# Spring Clean

Spring Clean is a read-only GitHub repository cleanup tool. It helps teams review old branches and open pull requests so they can decide what to keep, close, or delete manually.

The command is called `springclean`.

Spring Clean never changes GitHub. It does not delete branches, close pull requests, push commits, or update repository settings.

## What It Does

- Shows saved audit reports in a terminal browser.
- Audits one GitHub repository at a time.
- Lists branches, latest activity, protection/default status, and associated pull requests.
- Lists currently open pull requests, including drafts.
- Adds cleanup status and reason columns to guide review.
- Adds editable `review_action` and `review_comment` columns for team decisions.
- Writes timestamped local files so reports do not overwrite each other.
- Can list repositories available to your GitHub token.

The terminal browser is built with [Textual](https://textual.textualize.io/), a Python framework for terminal user interfaces.

## What You Need

- Python 3.10 or newer.
- A GitHub token that can read the repositories you want to audit.
- Terminal access on the machine that can reach those repositories.

For private repositories, use a token with read access to repository contents and pull requests. A fine-grained GitHub token with read-only permissions is recommended.

## Quick Start

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install Spring Clean:

```bash
python -m pip install springclean
```

Create a local `.env` file in the directory where you will run Spring Clean:

```bash
GITHUB_TOKEN=ghp_your_token_here
```

Open Spring Clean:

```bash
springclean
```

If your machine uses `python3` and `pip3`, use these instead:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install springclean
```

## Using The Browser

Run:

```bash
springclean
```

Spring Clean opens on the reports list. From there you can:

- load an existing report
- list repositories available to your token
- run a new audit
- search and filter rows
- tag branch and pull request rows for follow-up
- delete old local reports after confirmation

Keyboard controls:

| Key | Action |
| --- | --- |
| `o` | Show reports |
| `b` | Show branch report |
| `p` | Show pull request report |
| `g` | Enter a GitHub repo or URL and run a new audit |
| `l` | List repositories available to `GITHUB_TOKEN` |
| `d` | Delete the selected local report, or mark a branch for deletion / PR for closure |
| `k` | Mark the selected branch or PR as keep |
| `r` | Mark the selected branch or PR as review |
| `c` | Add or edit a short review comment |
| `u` | Clear the selected review action and comment |
| `enter` | Load the selected report or audit the selected GitHub repo |
| `/` | Focus search |
| `s` | Cycle filters |
| `a` | Reset to all rows |
| `escape` | Clear search or cancel a modal |
| `q` | Quit |

Delete only removes local Spring Clean report files. GitHub is not changed.

Review tags are saved back into the selected branch or pull request CSV. They do not call the GitHub API.

## Running Audits From The Command Line

The browser is the main workflow, but the CLI is useful for repeatable runs or scripts.

Audit branches:

```bash
springclean repo marioribeiro/springclean --branch
```

Audit open and draft pull requests:

```bash
springclean repo marioribeiro/springclean --pr
```

Audit both:

```bash
springclean repo marioribeiro/springclean --branch --pr
```

Use a different stale threshold:

```bash
springclean repo marioribeiro/springclean --branch --pr --stale-days 180
```

Choose another output directory:

```bash
springclean repo marioribeiro/springclean --branch --pr --out team-reports
```

Use another reports directory in the browser:

```bash
springclean --reports-dir team-reports
```

Show help:

```bash
springclean --help
springclean repo --help
```

Show the installed version:

```bash
springclean --version
```

## Output Files

By default, reports are written to `./reports`.

File names include the repository and UTC timestamp:

```text
reports/marioribeiro_springclean_20260507T134500Z_branches.csv
reports/marioribeiro_springclean_20260507T134500Z_pull_requests.csv
reports/marioribeiro_springclean_20260507T134500Z_summary.md
```

Generated reports may contain private repo names, branch names, pull request titles, and usernames. Treat them as internal artifacts when auditing private repositories.

## Branch Report

The branch CSV includes:

- branch name and GitHub links
- best-effort branch creator/context owner
- default and protected flags
- latest commit metadata
- days since latest commit
- GitHub-like activity bucket
- associated pull request numbers, authors, states, and URLs
- cleanup status and reason
- editable `review_action` and `review_comment` columns

GitHub does not expose a durable branch creator field through the branch API. `branch_created_by` is inferred in this order:

1. Associated PR author, when GitHub links the branch to a PR
2. Latest commit author
3. Latest commit committer

`branch_created_by_source` records which fallback was used.

Branch buckets:

| Bucket | Meaning |
| --- | --- |
| `default` | Repository default branch |
| `active` | Non-default branch with commits inside the stale threshold |
| `stale` | Non-default branch with no commits inside the stale threshold |

Branch cleanup statuses:

| Status | Meaning |
| --- | --- |
| `keep_default` | Default branch |
| `keep_protected` | Protected branch |
| `review_active` | Branch has recent commit activity |
| `review_stale_open_pr` | Stale branch has at least one associated open PR |
| `candidate_stale_merged_pr` | Stale branch has at least one associated merged PR |
| `candidate_stale_closed_pr` | Stale branch only has closed/unmerged associated PRs |
| `candidate_stale_no_pr` | Stale branch has no associated PRs |

## Pull Request Report

The pull request CSV includes only currently open pull requests, including drafts.

It includes:

- PR number, title, state, and draft flag
- `created_by`
- base and head branch details
- created and updated timestamps
- age columns
- GitHub URL
- cleanup status and reason
- editable `review_action` and `review_comment` columns

Pull request cleanup statuses:

| Status | Meaning |
| --- | --- |
| `open_active` | Open PR updated inside the stale threshold |
| `open_stale` | Open PR not updated inside the stale threshold |
| `draft_active` | Draft PR updated inside the stale threshold |
| `draft_stale` | Draft PR not updated inside the stale threshold |

## Summary

The Markdown summary includes:

- repo name and default branch
- generation timestamp
- stale threshold
- branch counts by bucket and cleanup status
- open PR counts by draft/ready state and cleanup status

Use it as a quick overview before reviewing rows in the browser or CSV.

## Troubleshooting

`Missing GITHUB_TOKEN`

Add `GITHUB_TOKEN` to `.env`, or set it in the shell where you run Spring Clean.

`Could not access owner/repo`

Check that the repository name is in `owner/name` format, the token can access that repository, and the command is running from the directory that contains your `.env`.

`GitHub API returned 403`

The token may not have enough permission, the API rate limit may be exhausted, or GitHub may have applied a secondary rate limit. Wait and retry, or use a token with the expected repository access.

`python: command not found`

Try the same command with `python3`:

```bash
python3 -m pip install springclean
```

## For Developers

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Create a local `.env` file from the example when working from the repository:

```bash
cp .env.example .env
```

Run tests:

```bash
coverage run -m pytest
coverage report
```

The coverage gate is configured at 95%.

Run lint and formatting checks:

```bash
ruff check .
ruff format --check .
```

Build and check the package:

```bash
python -m build
python -m twine check dist/*
```

Useful local checks:

```bash
springclean --help
springclean repo --help
```

## Publishing

The PyPI package name is `springclean`.

Publishing uses PyPI Trusted Publishing through GitHub Actions. Before the first release, create pending trusted publishers in PyPI and TestPyPI with these values:

| Field | PyPI | TestPyPI |
| --- | --- | --- |
| PyPI project name | `springclean` | `springclean` |
| Owner | `marioribeiro` | `marioribeiro` |
| Repository | `springclean` | `springclean` |
| Workflow | `publish.yml` | `publish.yml` |
| Environment | `pypi` | `testpypi` |

Require manual approval for the `pypi` GitHub environment before publishing real releases.

To test the package flow without publishing to PyPI, run the `Publish` workflow manually. That publishes to TestPyPI.

To publish a real release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Main runtime dependency:

- [Textual](https://textual.textualize.io/) for the terminal browser

## Project Principles

- Product name in prose: **Spring Clean**
- CLI command: `springclean`
- Read-only by default and by design
- CSV-first for easy team review
- Terminal review should work from saved report files unless the user explicitly asks for a GitHub action
- Prefer explicit cleanup signals over hidden automation

## License

MIT
