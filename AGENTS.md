# Repository Guidelines

## Project Structure and Module Organization
- `apps/rd_desktop/` is the desktop GUI app (entrypoint `apps/rd_desktop/main.py`).
- `apps/remote_ocr_server/` hosts the FastAPI server and Celery workers.
- `packages/rd_domain/`, `packages/rd_pipeline/`, and `packages/rd_adapters/` implement the layered core libraries.
- `database/migrations/` stores SQL migrations; `docs/` holds reference docs like `docs/DATABASE.md`.
- `logs/` contains runtime logs (for example `logs/app.log`).

## Build, Test, and Development Commands
- `pip install -r requirements.txt` installs local dependencies.
- `python apps/rd_desktop/main.py` runs the desktop client.
- `python build.py` builds a Windows exe into `dist/CoreStructure.exe`.
- `.\start-server.ps1` starts redis/web/worker via Docker Compose; add `-Build` or `-NoCache` when needed.
- `docker compose up -d --build` starts the OCR server; use `-f docker-compose.dev.yml` or `-f docker-compose.local.yml` for dev or low-memory setups.
- Manual server: `redis-server`, then `uvicorn apps.remote_ocr_server.main:app --host 0.0.0.0 --port 8000 --reload`, then `celery -A apps.remote_ocr_server.celery_app worker --loglevel=info --concurrency=1`.

## Coding Style and Naming Conventions
- Python 3.11+, 4-space indentation, format with Black and isort from `.pre-commit-config.yaml`.
- Install hooks with `pre-commit install` and run `pre-commit run --all-files` before pushing.
- Use `snake_case` for modules and functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Respect layering rules from `pyproject.toml`: `rd_domain` has no dependencies on higher layers.

## Testing Guidelines
- There is no dedicated `tests/` tree yet; add tests under `tests/` and name files `test_*.py`.
- Run `pytest` from the repo root and cover new pipeline or domain logic.

## Commit and Pull Request Guidelines
- Prefer conventional commits: `feat:`, `fix:`, `refactor:`, `chore:` with optional scopes like `feat(docker): ...`.
- PRs should include a short summary, testing results, and linked issues; include screenshots or a short GIF for GUI changes.
- Call out `.env` or config changes explicitly so reviewers can update local settings.
