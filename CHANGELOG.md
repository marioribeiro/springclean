# Changelog

## 0.1.0 - 2026-05-07

Initial V1 release.

- Add read-only GitHub repository audit CLI.
- Write timestamped branch CSV reports.
- Write timestamped open/draft pull request CSV reports.
- Generate timestamped Markdown summaries.
- Add bare `springclean` terminal browser for report selection, report review, and read-only audit runs.
- Add cleanup status and reason fields for review workflows.
- Add blank review action/comment fields for team notes.
- Support local `.env` token loading.
- Add tests, CI, project metadata, license, contribution notes, and security notes.
- Split implementation into a small `src/springclean` package.
- Add `ruff`, `pytest`, and `coverage` dev tooling with a CI coverage gate.
