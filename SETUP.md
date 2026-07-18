# Setup & Running — TMS-OC

Pure mechanics: what to install, what to configure, how to run it. For *why*
things are built the way they are (auth design, LLM provider choice,
background-job architecture, search tradeoffs), see [`README.md`](./README.md).

## Prerequisites

- Docker + Docker Compose (recommended path), **or**
- Python 3.11+, a local PostgreSQL 16 instance, and Redis if you want to run
  without Docker
- An API key for OpenAI or Mistral if you want to use those LLM providers
  instead of the local Ollama option (no key needed for Ollama)

## 1. Configure environment variables

```bash
cp .env.example .env
```

| Variable | Default | Notes |
|---|---|---|
| `APP_NAME`, `APP_VERSION` | `TMS-OC`, `1.0.0` | Cosmetic, shown in `/` and `/health` |
| `DEBUG` | `false` | `true` enables SQL echo + pretty console logs instead of JSON |
| `LOG_LEVEL` | `INFO` | Standard Python levels |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5433/tms_oc` | Async driver for the app; Alembic and Celery derive a sync URL from this automatically |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery result backend + rate limiter storage |
| `CELERY_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | Celery broker (RabbitMQ) |
| `JWT_SECRET` | placeholder — **change this** | HS256 signing key for access + refresh tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `LLM_PROVIDER` | `openai` | `openai` \| `mistral` \| `ollama` |
| `OPENAI_KEY` / `MISTRAL_KEY` | — | Only required for the provider you select |
| `OLLAMA_URL` | `http://localhost:11434` | Only used when `LLM_PROVIDER=ollama` |
| `LLM_MAX_RETRIES` | `3` | Celery task-level retries on LLM failure (up to 4 total attempts) — see [`README.md`](./README.md#llm-provider-tradeoffs) |
| `LLM_RETRY_BACKOFF_BASE` | `1.0` | Seconds; delay per retry is `base * 2^retry_number` |
| `LLM_RETRY_BACKOFF_MAX` | `600` | Cap on the backoff delay, in seconds |
| `CORS_ORIGINS` | `["http://localhost:3000", "http://localhost:8000"]` | JSON array |

## 2. Run the full stack (recommended)

```bash
docker compose up --build
```

This brings up, in one command:

- `postgres` (port `5433` on the host → `5432` in-container)
- `redis` (port `6379`) — Celery result backend + rate limiter
- `rabbitmq` (port `5672`, management UI on `15672`, default `guest`/`guest`) — Celery broker
- `ollama` (port `11434`, GPU-accelerated if available — set `LLM_PROVIDER=ollama` to use it for a zero-API-cost demo)
- `adminer` (port `8080`) — a DB browser, point it at the `postgres` service
- `api` — FastAPI on `http://localhost:8000` (`/docs` for Swagger, `/redoc` for ReDoc)
- `celery-worker` — consumes the `classification` and `reminders` queues
- `celery-beat` — fires the periodic sweep jobs on schedule

The API container runs migrations are **not** applied automatically by
compose — run them once after the containers are up:

```bash
docker compose exec api alembic upgrade head
```

## 3. Run locally without Docker (API only)

You can run just the API against Postgres without Docker, but reminders and
ticket classification are Celery jobs — without `celery-worker` (and
`celery-beat` for reminders) running somewhere, tickets will stay at
`classification_status=PENDING` and reminders won't fire. Either run those
processes locally too (`celery -A src.celery_app worker --loglevel=info` /
`celery -A src.celery_app beat --loglevel=info`) or use `docker compose up`
for the full stack.

```bash
docker compose up postgres redis rabbitmq    # database + Celery backend + broker
python -m venv .venv && source .venv/bin/activate   # or pyenv/venv of your choice
pip install -r requirements/dev.txt
alembic upgrade head
uvicorn src.main:app --reload
```

## 4. Create your first user and try the API

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme123", "role": "ADMIN"}'

curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme123"}'
# -> {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}

curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Cannot log in", "description": "Getting a 500 on /login since this morning", "customer_email": "customer@example.com"}'
```

The ticket is returned immediately (`category=OTHER`, `priority=MEDIUM`,
`classification_status=PENDING`); poll `GET /api/v1/tickets/{id}` a few
seconds later to see the LLM-assigned `summary`, `category`, and `priority`
once the Celery task completes.

## 5. Database migrations

```bash
# generate a new migration after changing src/common/models.py
alembic revision --autogenerate -m "describe the change"

# apply migrations
alembic upgrade head

# roll back one step
alembic downgrade -1
```

## 6. Running tests

```bash
pytest
```

Tests run against SQLite (a local `test.db` file), not Postgres - no
Docker, database service, or migrations required to run the suite.
`tests/conftest.py` builds the schema itself
(`Base.metadata.create_all()`) fresh before every test and drops it after,
rather than running Alembic migrations. `Ticket.search_vector` is declared
with `.with_variant(Text(), "sqlite")` (see `src/common/models.py`) so
schema creation succeeds on SQLite, and `TicketRepository.search()` falls
back to a plain `ILIKE` match instead of the real Postgres
`tsvector`/`websearch_to_tsquery` path when it detects a non-Postgres
dialect - see [`README.md`](./README.md#ticket-search--filtering) for
why that's an acceptable tradeoff for tests specifically. The LLM service is
auto-swapped to `MockLLMAdapter` and Celery runs in eager/in-memory mode - no
live LLM provider, broker, or Redis instance is required either.

To point tests at a different database instead (e.g. to exercise the real
Postgres full-text-search path), export `DATABASE_URL` before running
`pytest`:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/tms_oc pytest
```

## Troubleshooting

- **`InterfaceError: cannot perform operation: another operation is in progress`**:
  this was caused by `init_db()` calling `Base.metadata.create_all()` on every
  app startup in addition to Alembic already owning the schema — a restart
  (especially under `uvicorn --reload`) could interrupt that reflection
  mid-query and hand a half-finished pooled connection to the next real
  request. Fixed: `init_db()` now only does a connectivity check
  (`SELECT 1`); Alembic is the only thing that creates or alters tables.
  Make sure you've run `alembic upgrade head` at least once (step 5) — the
  app no longer creates tables for you. If you still see this after
  upgrading, it means something else is sharing a connection across
  concurrent coroutines - check for any `asyncio.gather(...)` calls using
  the same `AsyncSession`, since asyncpg connections can only run one query
  at a time.
- **Migrations fail against a fresh Postgres container**: make sure
  `docker compose up postgres` has finished its healthcheck before running
  `alembic upgrade head` — the container reports "started" before Postgres
  is actually ready to accept connections.
- **LLM classification never completes**: confirm `celery-worker` is up and
  consuming the `classification` queue (`docker compose logs celery-worker`),
  and that the relevant API key / Ollama URL is set correctly. A ticket that
  ends up with `classification_status=FAILED` and `manual_triage=true`
  means all `LLM_MAX_RETRIES` retries were exhausted — check the worker logs
  for the underlying provider error.
