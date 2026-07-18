# Design Decisions — TMS-OC

This is the "why," not the "how" — for setup and run instructions see
[`SETUP.md`](./SETUP.md). Each section states the decision, the alternatives
that were on the table, and the tradeoff being made.

---

## Auth design

**Decision: JWT access + refresh tokens, refresh tokens stored server-side as
SHA-256 hashes, rotated on every use.**

- **Access tokens** are short-lived (15 min default) and stateless — the API
  never hits the database to validate one, it just verifies the HS256
  signature and expiry (`src/common/security.py::verify_token`). This keeps
  the hot path (every authenticated request) fast and horizontally scalable:
  any API replica can validate a token with no shared state.
- **Refresh tokens** are long-lived (7 days) and *are* checked against the
  database (`refresh_tokens` table), because they need to be revocable —
  logout, logout-all-devices, and eventual compromise response all depend on
  being able to invalidate a specific token or all of a user's tokens.
- We never store the raw refresh token, only `sha256(token)`. If the database
  is ever dumped, the hashes are useless without also compromising the
  signing key path — same reasoning as storing password hashes, applied to
  bearer tokens.
- **Rotation on refresh**: `POST /auth/refresh` revokes the token it was
  called with and issues a new pair. This means a stolen refresh token has a
  limited window: once the legitimate client refreshes again, the stolen
  token stops working. The tradeoff is slightly more DB writes per refresh
  cycle, which is negligible at refresh-token frequency (once per ~15 min of
  active use, not once per request).
- **Password hashing**: `passlib` with `argon2` as the primary scheme
  (`bcrypt` kept as a fallback verifier for compatibility). Argon2 was chosen
  over bcrypt-only because it's the current OWASP recommendation and is
  tunable against both GPU and side-channel attacks; bcrypt is kept so
  existing bcrypt hashes (e.g. from a migration) still verify.

**Alternative considered and rejected**: pure stateless JWT with no
server-side refresh-token table (i.e. no way to revoke before expiry). This
was rejected because "no meaningful revocation" isn't compatible with a
`logout-all-devices` feature or a real incident-response story — for a system
handling customer support data, revocability was judged worth the extra
lookup on the refresh path.

### Role enforcement

**Decision: two roles (`ADMIN`, `AGENT`), enforced in the service layer, not
just at the route/dependency level.**

FastAPI's `Depends(get_current_admin_user)` on a route stops an agent from
*hitting an admin-only route at all* (e.g. `DELETE /tickets/{id}`), but it
does nothing to stop an `AGENT` from reading or modifying a ticket that
exists and is simply assigned to someone else — that's an ownership check,
not a role check, and it has to run per-record.

`TicketService` centralizes this in two small helpers:

```python
_ensure_can_view(ticket, user)    # AGENT: only unassigned or own tickets
_ensure_can_modify(ticket, user)  # AGENT: only own tickets
```

...and every ticket, note, and reminder operation calls one of them,
including `GET /tickets/{id}` — this was originally missing and let any
authenticated agent read (and create reminders against) any ticket by ID
regardless of assignment; it's now closed. The assignment brief specifically
calls this out ("not bypassable via direct ticket ID access"), which is why
it's enforced as a helper called from the service layer rather than
duplicated per-route — one place to get it right, one place to test it.

### Rate limiting on auth endpoints

**Decision: Redis-backed fixed-window limiter (5 attempts / 5 min / IP on
login, 10 / 5 min on register), fails open on Redis errors.**

A plain in-memory counter would work for a single process but silently stops
protecting anything the moment you run more than one API replica (each
replica has its own counter). Redis `INCR`/`EXPIRE` gives a shared,
consistent counter across replicas for the cost of one round-trip per
request. It **fails open** — if Redis is briefly unreachable, login/register
still work rather than going down because the rate limiter did; the tradeoff
is a short window with no brute-force protection during a Redis outage,
which was judged better than an auth outage during a Redis outage.

---

## LLM provider tradeoffs

**Decision: adapter pattern (`BaseLLMAdapter`) behind `llm_service`, so
`TicketService` and Celery tasks depend only on
`classify(title, description) -> LLMClassification` and never import a
concrete provider.** Swapping providers is one env var
(`LLM_PROVIDER=openai|mistral|ollama`), not a code change.

| Provider | Chosen for | Tradeoff accepted |
|---|---|---|
| **OpenAI** (default) | Most reliable JSON-mode output, lowest latency, easiest to demo end-to-end | Per-ticket cost, external network dependency, ticket text leaves the network |
| **Mistral** | Materially cheaper than OpenAI at similar quality; EU-hosted option matters for some data-residency requirements | Slightly less consistent adherence to the requested JSON shape in testing — worth an extra parse-failure branch if used in production |
| **Ollama** (local, `llama3.1` default) | Zero marginal cost, fully offline — the assignment explicitly rewards a dependency-free demo | Needs a GPU for latency that doesn't dominate ticket-creation-to-triage time; classification quality is noticeably behind the hosted models for edge-case tickets |

**Why not a bigger agent framework** (LangChain agents, tool-calling loops,
etc.): the assignment is explicit that this is a single classify-and-return
call, not multi-step reasoning, and the actual task — summarize + pick one of
4 categories + one of 3 priorities — doesn't benefit from tool use or
planning. An agent framework here would be complexity with no corresponding
capability gain, and it would make the "swap the provider without touching
business logic" requirement harder, not easier, since most agent frameworks
couple prompt orchestration to a specific provider's tool-calling format.

### Failure handling

**Decision: ticket creation never waits on the LLM call.**

`POST /tickets` persists the ticket (`status=OPEN`, `priority=MEDIUM`,
`category=OTHER`) and commits *before* enqueuing
`classify_ticket_task.delay(ticket.id)` on Celery. The HTTP response returns
as soon as the ticket is saved — the LLM call happens entirely after the
response, in a worker process. This was the one hard constraint in the
brief ("must not block ticket creation") and it's structural, not just a
try/except: there is no code path in the request handler that calls an LLM
adapter at all. As of this pass, the enqueue call itself is also wrapped in
a try/except (`src/tickets/service.py::create_ticket`) — a broker outage
(Redis down, network blip) logs `classification_enqueue_failed` and the
ticket is still returned successfully rather than surfacing as a 500; it
simply stays at `classification_status=PENDING` until retried or handled
manually.

Retry lives at exactly one layer: `classify_ticket_task` (in
`src/tasks/classification_tasks.py`) catches any exception from
`llm_service.classify_sync()` and calls Celery's own `self.retry(exc=exc,
countdown=..., max_retries=settings.llm_max_retries)`. The countdown is
computed by `_backoff_seconds()`: `llm_retry_backoff_base * 2^retry_number`,
capped at `llm_retry_backoff_max` — so 1s → 2s → 4s → 8s... up to a
configurable ceiling (default 10 min), for up to `LLM_MAX_RETRIES` retries
(default 3, i.e. 4 total attempts). `LLMService.classify()` /
`classify_sync()` are deliberately single-attempt, with no retry loop of
their own — an earlier version had a second, hand-rolled `asyncio.sleep`
retry loop inside the service in addition to Celery's, which meant a
transient failure could get retried twice over with compounding delays, and
it doubled up on the same `LLM_MAX_RETRIES` setting for two different
loops. Consolidating retry into Celery's native mechanism means each retry
is genuinely a fresh task execution — the ticket is re-fetched from the DB
and the LLM is called again from scratch — rather than a retry nested inside
a single long-running call. If all retries are exhausted
(`MaxRetriesExceededError`), the ticket is left with
`classification_status=FAILED` and `manual_triage=True` — visible in a
"needs manual triage" filter — rather than left silently `PENDING` forever
or, worse, blocking anything.

There is deliberately no periodic "sweep for stuck-PENDING tickets" job on
Celery beat - the per-ticket `classify_ticket_task` already retries itself
for every failure mode except the `.delay()` call never reaching the broker
at all, which is rare enough and outside this assignment's scope to not
warrant a standing periodic job.

---

## Background jobs: Celery only

**Decision: Celery (worker + beat) is the sole system of record for
background work. The earlier in-process APScheduler implementation has been
removed.**

An APScheduler-based fallback (`src/scheduler/{reminders, classification,
service}.py`, started from `main.py`'s lifespan, gated by
`SCHEDULER_ENABLED`) was built early on as a zero-infrastructure path for
running the API standalone. It was removed rather than kept as a permanent
fallback: running it alongside Celery against the same database was a real
bug, not a hypothetical one — neither implementation took a row lock around
its due-reminder / pending-classification query, so two schedulers polling
the same table could both pick up the same due reminder and both fire it
(duplicate notifications), or both send the same ticket to the LLM
(duplicate cost, and a race on which result gets saved last). Keeping a
second scheduler implementation around — even disabled by default — meant
that bug stayed one misconfigured env var away at all times, for a
zero-Redis demo path that Docker Compose (the primary deployment path)
never needed. `main.py`'s lifespan no longer references a scheduler at all;
there is nothing to gate with an env var.

**Why Celery over "just APScheduler everywhere"**: APScheduler running
in-process ties the scheduler's lifetime and failure mode to the API
process, and — more importantly — doesn't coordinate across replicas. If you
horizontally scale the API (multiple Uvicorn workers or multiple pods), each
replica would start its own APScheduler and you're back to the exact
duplicate-firing problem above, except now it's inherent to scaling the API
rather than a one-time bug. Celery beat is a single, separate process by
design, so scaling the API doesn't multiply the scheduler.

Running the API without Docker still works (see `SETUP.md`), but reminders
and classification now require `celery-worker` (and `celery-beat` for
reminders) to be running somewhere — there's no longer an in-process
fallback that picks up the slack if they aren't.

**What's still not fully production-safe**: the due-reminder and
pending-classification queries are still plain `SELECT` + application-level
status updates, not `SELECT ... FOR UPDATE SKIP LOCKED`. This is fine with
exactly one Celery beat process and one worker (the current setup), but
scaling to multiple Celery worker replicas consuming the same queue would
reintroduce a duplicate-processing race, just between workers instead of
between schedulers. Adding row-level locking (or a Redis-based distributed
lock per reminder/ticket ID) is the next step before that scale-out.

---

## Ticket search & filtering

**Decision: Postgres full-text search (`tsvector` generated column + GIN
index, queried via `websearch_to_tsquery`), combined with equality filters
(`status`, `priority`, `category`, `assignee_id`) and a date range,
offset/limit paginated.** This was option 1 of the upgrade path documented
below, now implemented (`alembic/versions/a3f7c9e21d40_...py`,
`src/tickets/repository.py::search`).

**Why FTS over the ILIKE-only approach this project started with**: `ILIKE
'%term%'` (leading wildcard) can't use a standard B-tree index, so it's a
sequential scan over `tickets` once the table is large — fine at demo/small
support-team volume, not fine in the tens/hundreds of thousands of rows.
Postgres FTS needed no new service, stays inside the same transaction as
everything else, and adds relevance ranking (`ts_rank`) and stemming
("logging" also matching "login") that `ILIKE` structurally can't do.
`Ticket.search_vector` is a *generated* column
(`GENERATED ALWAYS AS (to_tsvector(...)) STORED`) — Postgres maintains it
automatically on every insert/update of `title`/`description`; the app never
writes to it (`server_default=FetchedValue()` on the model tells SQLAlchemy
to leave the column out of INSERT/UPDATE entirely).

**Test suite runs against SQLite, with a dialect-aware fallback in the
repository.** `TicketRepository.search()` checks the session's bind dialect:
on Postgres it uses the real `tsvector`/`websearch_to_tsquery`/`ts_rank`
path described above; on any other dialect (SQLite, in the test suite) it
falls back to a plain `Ticket.title.ilike(...) | Ticket.description.ilike(...)`
match. `Ticket.search_vector` is declared as
`TSVECTOR().with_variant(Text(), "sqlite")` on the model specifically so
`Base.metadata.create_all()` (which `tests/conftest.py` uses to build the
schema per test run, rather than running Alembic) succeeds on SQLite at
all — it becomes an ordinary, unpopulated `TEXT` column there.

This was a deliberate tradeoff, not an oversight: a real Postgres-backed
test suite would exercise the actual FTS code path end-to-end (stemming,
`ts_rank` ordering, `websearch_to_tsquery` phrase/exclusion syntax) and was
tried, but it made the suite depend on a running Postgres instance with a
separate `testdb` database provisioned via a Docker init script — a real
cost for local iteration speed and CI setup, for a project at this scale.
SQLite keeps the suite fully self-contained (`pytest` with nothing else
running) at the cost of the FTS-specific behavior (ranking, stemming, the
`websearch_to_tsquery` operators) only being exercised manually, by pointing
`DATABASE_URL` at a real Postgres instance before running `pytest` (see
`SETUP.md`) rather than on every default test run. If FTS correctness ever
becomes critical enough to need CI coverage specifically, the fix is a
separate Postgres-only test job (e.g. a `pytest -k postgres` marker run
against a CI Postgres service container), not switching the whole suite
back to Postgres by default.

**Remaining upgrade path, if this ever needs to go further:**

1. ~~**Postgres full-text search**~~ — done, see above.
2. **`pg_trgm` + GIN index**. Would help specifically with typo-tolerant /
   partial-substring matching that stemmed FTS doesn't cover (e.g. matching
   "recieve" against "receive"). Not implemented — no signal yet that
   typo-tolerance is needed beyond what `websearch_to_tsquery` already gives.
3. **Dedicated search engine** (OpenSearch/Elasticsearch, or a lighter
   option like Meilisearch/Typesense). The right call once you need faceted
   search across many fields, sub-100ms search at high query volume, or
   relevance tuning that Postgres FTS doesn't give you — but it means
   standing up and operating a second system and keeping it in sync with
   Postgres (CDC, dual writes, or periodic reindex), which is real ongoing
   cost. For this project's actual scale, adopting one now would be
   over-engineering ahead of an actual need.

---

## API contract & error handling

**Decision: a single `AppException` hierarchy
(`NotFoundException`, `ForbiddenException`, `ConflictException`,
`UnauthorizedException`, `ValidationException`, ...) mapped to a consistent
`{"success": false, "error": {"code", "message", "details"}}` JSON shape by
one set of exception handlers (`src/common/exceptions.py`), registered once
in `main.py`.**

Handlers exist for `AppException`, FastAPI's own `HTTPException`, and a
catch-all `Exception` handler that returns a generic `500` and only includes
the raw error string when `DEBUG=true` — so an unexpected exception in
production never leaks an internal error message or stack trace to a client,
while local development still gets the detail needed to debug it.

Every service method raises a specific `AppException` subclass rather than
returning `None`/`False` and letting the router decide what that means —
this keeps the "what HTTP status does this failure mean" decision in one
place (the exception class → status code mapping) instead of duplicated
per-route.

## Observability

**Decision: structured JSON logs (structlog) with a request-correlation ID
propagated through every log line for a given request, plus a dedicated
`BackgroundTaskLogger` for Celery task lifecycles.**

`CorrelationIdMiddleware` reads (or generates) an `X-Request-ID` per request,
stores it in a `ContextVar`, and every log line emitted during that request —
across router, service, and repository layers — picks it up automatically
via a structlog processor, with no need to thread a request ID through every
function signature. Background tasks (Celery) use the same JSON-structured
approach with `task_started`/`task_progress`/`task_completed`/`task_failed`
events, so a ticket's classification failure and its eventual retry are
traceable as one narrative in the logs rather than scattered
unstructured print-equivalents.

This was chosen over plain `logging.info(f"...")` calls specifically because
the brief evaluates "structured request logging / correlation IDs" as a named
bonus item, and because in a system with async request handling + a separate
Celery worker process, being able to grep one request ID across both is the
difference between debugging in minutes vs. reconstructing a timeline by
hand from timestamps.
