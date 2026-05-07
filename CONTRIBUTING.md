# Contributing

Spring Clean is intentionally small and read-only. Changes should preserve that default: collect data, explain it clearly, and never mutate GitHub state.

## Local Checks

Run the test suite:

```bash
python -m pip install -e ".[dev]"
coverage run -m pytest
coverage report
```

Coverage must stay at or above the configured threshold in `pyproject.toml`.

Run lint and formatting checks:

```bash
ruff check .
ruff format --check .
```

Run the CLI help:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
springclean --help
springclean repo --help
```

## Pull Request Guidelines

- Keep the collector read-only.
- Keep runtime dependencies deliberate and tied to core user workflows.
- Add or update tests for changes to cleanup status logic, report columns, or GitHub API request behavior.
- Do not commit `.env`, generated reports, or cache files.
