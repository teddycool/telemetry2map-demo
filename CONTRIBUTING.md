# Contributing

Thanks for contributing to telemetry2map-demo.

## Prerequisites

- Python 3.12+
- pip
- Docker (optional, for compose-based runs)

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run the app

```bash
python3 scripts/run_demo.py
```

## Run tests

```bash
# Fast local checks used by CI
pytest tests/unit tests/integration

# Full containerized test profile
docker compose --profile test run --build --rm tests

# Browser tests (Playwright)
docker compose --profile browser-test run --build --rm browser-tests
```

## Lint

```bash
ruff check .
```

## Pull requests

- Keep PRs focused and small when possible.
- Update docs when behavior or APIs change.
- Ensure unit/integration tests pass before opening or updating a PR.
