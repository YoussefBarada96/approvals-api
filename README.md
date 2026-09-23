# Approvals API

A workflow and approval engine built with FastAPI and PostgreSQL. A request (say, a purchase order) moves through an ordered set of approval steps. Each step is assigned to a role and has a deadline. Every state change is written to an audit trail, and a background worker escalates steps that miss their deadline.

> **Status:** in progress. The service skeleton, health checks, Docker setup and CI are done. The approval workflow itself is being built next.

## Tech stack

| Area | Choice |
| --- | --- |
| API | FastAPI (Python 3.12) |
| Database | PostgreSQL 16, SQLAlchemy 2.0 (async) with asyncpg |
| Config | pydantic-settings (environment variables) |
| Dependencies | pip-tools (`requirements.in` compiled to pinned `requirements.txt`) |
| Tests / lint | pytest, ruff |
| Runtime | Docker, Docker Compose |
| CI | GitHub Actions |

## Running it

### With Docker (recommended)

```bash
docker compose up --build
```

The API runs at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

### Locally

This needs Python 3.12 and a PostgreSQL server you can reach.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install pip-tools
pip-sync requirements.txt requirements-dev.txt
cp .env.example .env            # then point DATABASE_URL at your database
uvicorn app.main:app --reload
```

### Tests and lint

```bash
pytest
ruff check . && ruff format --check .
```

## Endpoints so far

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness: the process is running. Doesn't touch the database |
| GET | `/health/ready` | Readiness: the database answers. Returns 503 if it doesn't |

## Managing dependencies

Direct dependencies are listed in `requirements.in` (runtime) and `requirements-dev.in` (tests and tooling). After editing either file, regenerate the pinned lockfiles:

```bash
pip-compile requirements.in
pip-compile requirements-dev.in
pip-sync requirements.txt requirements-dev.txt
```

The dev file is constrained by `-c requirements.txt`, so packages shared by both files always resolve to the same version.

## Design notes

- **Separate liveness and readiness checks.** If the database goes down, `/health/ready` fails so traffic can be routed away, but `/health` keeps passing, so an orchestrator doesn't restart API containers that are healthy. Restarting them wouldn't fix the database anyway.
- **pip-tools over plain `requirements.txt`.** Every transitive dependency is pinned, so local runs, CI and the Docker image install exactly the same versions. The `.in` files stay short and readable.
- **Non-root container.** The image runs as an unprivileged `appuser`.

More decisions (auth, pagination, locking, the job queue) will be added as those parts are built.
