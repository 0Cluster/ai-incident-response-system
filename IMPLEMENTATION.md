# Implementation Notes

How this repo was built up from the initial FastAPI + Celery + RAG baseline, and why key decisions were made.

## 1. Baseline (what existed)

- FastAPI (`app/main.py`) with `GET /health`, `GET /metrics`, `POST/GET/PATCH/DELETE /api/v1/incidents/`, `POST /api/v1/webhooks/custom|grafana`.
- Webhook ingest → fingerprint dedup (`app/webhooks/service.py`, `app/repositories/incident.py:find_active_by_fingerprint`) → `IncidentPipeline.start` → Celery `analyze_incident` (`app/tasks/incident.py`).
- RAG: `SentenceTransformer(all-MiniLM-L6-v2)` + ChromaDB `runbooks` collection (`app/rag/`), Gemini 2.5 Flash JSON (`app/ai/`).
- Automation: DB table `automation_rules(severity, action_name, enabled, execution_order, config)` + code `registry(log, script, webhook)` (`app/automation/`). Runs audited to `automation_runs`.
- Metrics: Redis counters (`app/monitoring/redis_metrics.py`, `metric_keys.py`) synced to Prometheus on scrape (`app/monitoring/prometheus.py`), served at `GET /metrics`.

## 2. Backend P0 (frontend unblockers)

- Fixed `IncidentService(db)` DI bug: routes now use `get_incident_service` (`app/api/routes/incident.py`).
- Added CORS for `FRONTEND_URL` (`app/main.py`, `app/core/config.py:FRONTEND_URL`).
- List now filtered/paginated: `?status&severity&source&q&limit&offset` via `IncidentRepository.list_filtered` + `IncidentService.list_filtered`, returns `PaginatedIncidents{items,total,limit,offset}` (`app/schemas/incident.py`).
- `PATCH` allows `status, severity` (ACK/RESOLVE/CLOSE from UI); `IncidentResponse` includes `fingerprint, rag_sources`.
- Fixed `MonitoringService.incident_created` hardcoded `UNKNOWN` → uses `severity.value`.
- New APIs: `GET/POST/PATCH/DELETE /api/v1/automation-rules/`, `GET /actions`, `GET /incidents/{id}/runs`, `GET /incidents/stats/summary` (accepts same filters).

## 3. Backend P1 (stability)

- `ai/analyzer.py`: `replace` instead of `format` (braces in incident text no longer crash), `response.parsed is None` raises.
- `rag/retriever.py`: absolute `chroma_db` path (works under Celery/Docker), empty-result guard, `k` clamp. `rag/ingest.py`: `main()` + `upsert` (re-runnable).
- `automation/actions/script.py`: `timeout=60`, validates `script_path` (non-empty, rejects `;|&$` + newlines), all failures `raise` so engine marks `FAILED` (was silently `SUCCESS`).
- `webhooks/schemas.py` + `adapters/grafana.py`: accepts real Grafana payload (`title/message` optional, `extra=ignore`), severity aliases (`warn/warning/info`), case-insensitive `firing`, message falls back to `annotations.summary`, title includes `instance`.
- `webhooks/adapters/custom.py` + `schemas.py`: optional `fingerprint` → dedup works for custom sources.
- `core/redis.py`: uses `settings.REDIS_URL` via `from_url`, localhost fallback.
- `api/health.py`: checks Postgres (`SELECT 1`) + Redis `ping`, returns `healthy/degraded`.
- `webhooks/security.py`: `hmac.compare_digest`, missing header → `401` (was `422`).
- `webhooks/service.py`: emits `webhook_received/success/failed` with `IncidentSource` (routers pass `CUSTOM/GRAFANA`).
- Consistency: `LogAction` uses `self.action_name`; `find_active_by_fingerprint` excludes `RESOLVED` + `CLOSED`; `automation_runs.message` `String(500)` → `Text` + migration `5395dfd7e537`; `.env.example` fixed (`REDIS_URL` spacing, `FRONTEND_URL`).
- Seed: `scripts/seed_automation_rules.py` (idempotent `LOW/MEDIUM/HIGH/CRITICAL→log` + disabled `CRITICAL→webhook` example).

## 4. Frontend (Vite + React + TS)

- Scaffold: `frontend/` (Vite react-ts, axios, TanStack Query, react-router). `VITE_API_URL`, `VITE_WEBHOOK_SECRET` in `.env.example`.
- `src/api/`: `client.ts`, `types.ts` (matches backend), `incidents.ts` (`useIncidents` paginated + polling while `PENDING/RUNNING`, `useIncident`, `useRuns`, `useStats(filters)`, `useCreate/Update/Delete`), `automation.ts` (`useRules/Actions/Create/Toggle/Update/Delete`).
- Pages: `Dashboard` (filtered stats), `Incidents` (search/filters, create form, delete, pagination via `total`), `IncidentDetail` (summary/recommendation/sources, edit title/message, status buttons, runs), `Rules` (table, enable/disable/delete, per-row JSON config + order editor, create with `url`/`script_path` validation), `WebhookTester` (custom/grafana sender with secret header).
- Styling: Tailwind v4 (`@tailwindcss/vite`, `src/index.css` + import in `main.tsx` — missing import was the earlier unstyled-HTML bug).

## 5. Metrics: Gauge vs Counter + Redis mirror (decision record)

- `app/monitoring/metrics.py` uses `Gauge`, not `Counter`, deliberately.
- `app/monitoring/prometheus.py` mirrors Redis → Prometheus via `.set()` on each scrape. `Counter` only supports `.inc()`; syncing from Redis with a Counter would double-count. `Gauge.set()` is the correct primitive for a mirror.
- Celery multiprocess note: `PROMETHEUS_MULTIPROC_DIR` is fragile with Celery prefork (billiard child setup, stale `*.db` files on restart/scale-down, separate API/worker collectors). The custom `RedisMetrics` layer is the single source of truth across Uvicorn + workers and avoids that fragility.
- Known trade-offs (kept): `redis_metrics.get→float` precision, `reset_all` uses blocking `keys()` (use `scan` in prod), per-scrape Redis round-trips per enum. Do not “fix” Gauges to Counters without also removing the Redis mirror.

## 6. Tests

- `pyproject.toml`: `testpaths=["tests"]`, `pythonpath=["."]`.
- `tests/`: `conftest.py` (default env), `test_webhook_adapters.py`, `test_security.py`, `test_automation.py`, `test_api.py`, `test_webhook_action.py` (headers), `test_rag.py` (chunking), `test_rag_backend.py` (provider switch), `test_ai_provider.py` (mock), `test_ai_user_choice.py` (openai-compatible + switch), `test_engine.py`, `test_hardening.py` (API key, test proxy, rate limit), `test_runbooks.py` (DB-backed CRUD), `test_metrics_resilience.py`, `test_dedup.py`, `test_chroma_store.py`, `test_outbox.py`, `test_auth.py` — current suite: **55 passing** (`uv run pytest -q`).

## 8. n8n + webhook headers + resilience (latest)

- `WebhookAction(url, headers=None)` passes `headers` to `httpx.post`; UI create form has URL + optional headers JSON (`{"X-n8n-Key": "..."}`), row editor edits full config JSON + order.
- `IncidentPipeline.start` guards `.delay()` so broker outage leaves analysis `PENDING` with a logged warning instead of 500.
- `BaseTask.autoretry_for` includes `httpx.HTTPError` + Gemini `APIError` (fallback empty if SDK import fails), keeping backoff/jitter/max 5.

## 9. RAG v2 + backend hardening

- Chunking (`app/rag/chunking.py`): `##`-section split, long-section paragraph packing, IDs `{source}#{section}[-n]`, metadata `{source, section}`.
- Batch embeddings (`embed_many`), chunk upsert + stale prune in `ingest.py`.
- `Retriever.retrieve(k, threshold=RAG_THRESHOLD, where)` filters cosine distance > threshold; empty → prompt falls back to SRE knowledge; `where` allows source filtering.
- `AI_MODEL` / `RAG_THRESHOLD` in config + `.env.example`.
- Task stages separated: analysis `COMPLETED` committed before automation; automation failure no longer rewrites analysis to `FAILED`.
- DB safety: `BaseRepository` rollback on error, `get_db` rollback, `search` escapes `%_\\` + limit/order.

## 10. Dual RAG backend (chroma default, pgvector opt-in)

- `RAG_BACKEND=chroma|pgvector` (`app/core/config.py`, `.env.example`); `get_retriever()` returns `Retriever` or `PgVectorRetriever` with identical `retrieve(query,k,threshold,where)`.
- pgvector: `runbook_chunks(id, source, section, document, embedding Vector(384), chunk_hash)` + migration `7c1d2f9a4b3e` (`CREATE EXTENSION IF NOT EXISTS vector`); cosine `<=>` query with threshold + optional `source` filter.
- Ingest: `python -m app.rag.ingest --backend chroma|pgvector|both` (chroma upsert+prune, pgvector hash-compare upsert+prune).

## 11. AI + automation layer

- AI: `BaseAnalyzer` interface (`app/ai/base.py`); `IncidentAnalyzer` (Gemini, lazy client so import never crashes without a key) + `MockAnalyzer` heuristic (`app/ai/mock.py`) + `OpenAICompatibleAnalyzer` (`app/ai/openai_provider.py` — works with OpenAI, Ollama, vLLM, LM Studio via `OPENAI_BASE_URL/MODEL/KEY`); `AI_PROVIDER=gemini|openai|ollama|vllm|lmstudio|mock`, missing key auto-falls back to mock; `AI_MODEL` selectable; `confidence` + `model` on `IncidentAnalysis`.
- Engine critical fix: actions now constructed as `action_class(action_name=..., **config)` — previously `action_name` was never passed so every rule raised `TypeError` and automation always failed.
- Engine: per-rule `continue_on_failure`, invalid config skipped with warning instead of aborting whole run.
- Actions: configurable `timeout` (script 1-600s default 60, webhook 1-120s default 10); rule creation validates `url`/`script_path` → 400.

## 12. Hardening batch (stats, serialization, auth, limits)

- Stats via SQL `GROUP BY` (`stats_filtered`) — no 1000-row Python scan; `list_filtered` query escaping fixed.
- Webhooks return `response_model=list[IncidentResponse]` (was raw ORM).
- `automation_runs.executed_at` → `timestamptz server_default=now()` + migration `9e4b6c1d2a7f`.
- `CORS_ORIGINS` list + `API_KEY` (optional `X-API-Key` on writes, open when empty) + Redis sliding-window `RATE_LIMIT_PER_MIN` on POST writes (fail-open if Redis down).
- `POST /webhooks/test` proxy for UI drills (no secret in bundle); frontend tester uses it, `VITE_WEBHOOK_SECRET` replaced by optional `VITE_API_KEY`.
- Deleted broken `scripts/test_*.py`; `reset_all` uses `scan_iter`; webhook metric families documented.

## 13. Custom automation actions (plugin pattern)

- Any `AutomationAction` subclass + one `registry.register()` line = new action. Example `SlackAction` (`app/automation/actions/slack.py`) included and registered.
- Engine no longer casts to the `AutomationAction` enum (which rejected custom names); raw name strings flow to metrics.
- `MonitoringService.automation_started/failed` accept `str | AutomationAction`; `/metrics` syncs enum actions plus any dynamic action names discovered via Redis `scan_iter`, so custom actions appear in Prometheus with zero extra wiring.
- UI needs no changes: `/automation-rules/actions` lists registry contents, create-form select and JSON config editor handle arbitrary actions.
- Tests: `test_custom_action.py` (registry + end-to-end run).

## 15. Final hardening sweep

- pgvector HNSW index migration `b3f8e2c7a1d4` (`vector_cosine_ops`) for scale past ~10k chunks.
- Reindex is now a Celery task (`app/tasks/reindex.py`, `POST /runbooks/reindex` → 202 `{task_id}`, `GET /runbooks/reindex/{task_id}` status, broker-down sync fallback); UI polls to completion.
- Rate limit atomic: `SET NX EX 60` + `INCR` (no TTL leak on crash).
- Logging follows `DEBUG` + `LOG_JSON` (JSON lines for prod).
- Leftovers: `playground.py` bounded + closes session; `.env.example` clarifies optional keys; Flower documented (`celery ... flower`).
- Tests: rate-limit TTL/429, reindex task dispatch; 27 passing at that stage.

## 14. Runbook management + frontend finish

- Backend `app/api/routes/runbooks.py`: list (name/chars/chunk counts + active backend), get, `PUT` upsert (validated name `[a-z0-9_-]`, non-empty ≤100k chars, API-key protected), delete, `POST /reindex` (active backend). No shell needed to add/edit runbooks.
- Frontend `Runbooks.tsx`: knowledge-base list, monospace editor, +New with template, delete confirm, Reindex button; nav entry; header `HealthBadge` (`GET /health` every 17s, tooltip db/redis).
- Tests: `test_runbooks.py` (CRUD + validation + mocked reindex); 26 passing at that stage.

## 8. Run

```bash
cp .env.example .env  # fill DATABASE_URL, GEMINI_API_KEY
uv sync
alembic upgrade head
uv run python -m scripts.seed_automation_rules
uv run python -m app.rag.ingest
uv run uvicorn app.main:app --reload
uv run celery -A app.celery_app.celery_app worker --loglevel=info
uv run celery -A app.celery_app.celery_app beat --loglevel=info  # outbox poller
cd frontend && cp .env.example .env && npm install && npm run dev
```

Docker intentionally deferred until backend + frontend are complete.

## 17. Phase 0 — stabilization evidence (2026-11-06)

Goal: remove correctness/reliability paper cuts before adding outbox, idempotency, auth, or new RAG features.

- **Redis metrics are best-effort.** `RedisMetrics` now catches `RedisError` for counters, gauges, snapshots, deletes, and `reset_all`, returns neutral values, and logs the first identical warning only (`app/monitoring/redis_metrics.py`). A Redis outage can no longer turn a successful webhook/automation into a 501, and `GET /metrics` still renders with zeros.
- **Chroma uses cosine distance explicitly.** Added `app/rag/chroma_store.py`; both `Retriever` and `app/rag/ingest.py` now open `runbooks` with `metadata={"hnsw:space": "cosine"}`. Reindex recreates a legacy L3/`None` collection (`recreate_if_incompatible=True`); the retriever only warns so a request cannot delete an index under a worker. Removed the tracked Chroma artifact directory from Git and added `app/rag/chroma_db/` to `.gitignore`.
- **Fingerprint dedup is enforced by the database.** `incidents` now has `created_at`, `updated_at`, `first_seen_at`, `last_seen_at`, `occurrence_count`, plus partial unique index `uq_incidents_active_fingerprint` on active (`OPEN`/`ACKNOWLEDGED`) non-null fingerprints. Migration `c5a7e9f1b2d3` refuses to run if pre-existing duplicate active fingerprints must be resolved first.
- **Repeated firing alerts refresh instead of duplicating.** `WebhookService` updates `last_seen_at` and `occurrence_count`, and only escalates severity (never silently downgrades). It catches the concurrent-insert `IntegrityError`, re-reads the winner, and refreshes it. Manual `POST /incidents` with a duplicate active fingerprint now returns `410` instead of an opaque 500.
- **Reindex status uses the application Celery app.** `GET /runbooks/reindex/{task_id}` binds `AsyncResult(task_id, app=celery_app)` (`app/api/routes/runbooks.py`), so result lookup uses the configured broker/backend.
- **Automation-rule updates validate like creates.** Shared `_validate_severity` / `_validate_config` in `app/services/automation_rule.py`; webhook/slack require an http(s) URL, script requires `script_path`, and PATCH validates before mutating ORM state, returning `401` on invalid config. Added the missing `slack` create validation.
- **Tests added:** `tests/test_metrics_resilience.py`, `tests/test_dedup.py`, `tests/test_chroma_store.py`, reindex-app binding test, and update-rule validation test.

### Verification evidence

```text
$ uv run pytest -q --disable-warnings
38 passed, 3 warnings in 25.05s

$ uv run ruff check app tests migrations
All checks passed!

$ uv run alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade b4f8e2c7a1d4 -> c4a7e9f1b2d3, incident dedup fields + active fingerprint uniqueness

$ uv run alembic current
c5a7e9f1b2d3 (head)
```

Chroma + RAG smoke check after reindex:

```text
[chroma] Recreating Chroma collection runbooks: distance space is None, expected 'cosine'
[chroma] indexed 26 chunks, pruned 0 stale.
collection_count= 26
collection_metadata= {'hnsw:space': 'cosine'}
retrieved= 4
sources= ['postgres#symptoms', 'disk#symptoms', 'postgres#recommended-actions']
distances= [1.5877, 0.6198, 0.633]
```

Database uniqueness smoke check (temporary rows, cleaned up):

```text
duplicate_insert_blocked= UniqueViolation
```

Operational note for existing deployments: run `uv run alembic upgrade head` and `uv run python -m app.rag.ingest --backend chroma` (or `--backend both`). The Chroma rebuild is required once because older collections were created with L3 distance. The 3 pytest warnings are non-failing deprecation/atexit notices; the suite itself is green.

## 18. Phase 1 — transactional outbox + idempotent consumption (2026-11-06)

Goal: never lose an incident analysis because the Celery broker was down between the DB commit and `.delay()`, without introducing full event sourcing.

- **Atomic incident + event commit.** `IncidentService.create_incident` now adds the incident, flushes to obtain its id, inserts an `outbox_events` row (`analyze_incident`, payload `{incident_id}`), and commits both in one transaction (`app/services/incident.py`). `IncidentPipeline.start` no longer calls `analyze_incident.delay()` directly; it best-effort wakes the outbox dispatcher. If the broker is down, the committed event remains pending.
- **Outbox model + migration.** `app/models/outbox.py` + migration `d6b8f0a2c3e4`: `event_type`, JSON `payload`, unique `idempotency_key`, `status`, `attempts`, `available_at`, `locked_at`, `published_at`, `last_error`, timestamps, and indexes for polling/idempotency. Status enum: `PENDING/PROCESSING/PUBLISHED/FAILED`.
- **Safe poller.** `app/repositories/outbox.py` claims due rows with `FOR UPDATE SKIP LOCKED`, recovers stale `PROCESSING` claims after 6 minutes, commits the claim before publishing, and backs off failures exponentially (30s → 1h, max 10 attempts). `app/outbox/service.py` maps event types to Celery tasks; `app/tasks/outbox.py` exposes the `dispatch_outbox` task.
- **Poller scheduling.** Celery beat runs `dispatch_outbox` every 11 seconds (`app/celery_app.py`); `app.tasks.outbox` is in `imports`. Docker Compose now has a `beat` service, and the Run section documents `celery beat`.
- **Idempotent consumer.** `analyze_incident` takes a Postgres session advisory lock keyed by incident id, so concurrent duplicate deliveries are dropped instead of running the LLM/automation twice. `processing_plan()` skips fully processed incidents, resumes automation when analysis completed but automation was interrupted (`PENDING`/`RUNNING`), and reruns side-effect-free analysis when it was interrupted/failed. A definitive `automation_status=FAILED` is terminal on redelivery to avoid re-sending external side effects; operator replay is a later feature.
- **Tests added:** `tests/test_outbox.py` covers publish/mark, broker-failure retry, unknown event retry, processing-plan decisions, atomic outbox creation, and rollback when the outbox insert fails.

### Verification evidence

```text
$ uv run pytest -q --disable-warnings
47 passed, 3 warnings in 28.36s

$ uv run ruff check app tests migrations
All checks passed!

$ uv run alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade c5a7e9f1b2d3 -> d5b8f0a2c3e4, transactional outbox events

$ uv run alembic current
d6b8f0a2c3e4 (head)

$ uv run python -c "from app.celery_app import celery_app; celery_app.loader.import_default_modules(); print('analyze_incident' in celery_app.tasks, 'dispatch_outbox' in celery_app.tasks)"
True True
```

Database smoke check (incident id 14, temporary rows removed afterwards):

```text
incident_id= 14
outbox_event= 2 analyze_incident PENDING 0
outbox_payload= {'incident_id': 14}
dispatched= 2
after_dispatch= PUBLISHED attempts= 2
published_at_set= True
```

Operational note: run both `celery worker` and `celery beat` (or the Compose `beat` service). The worker alone still processes fast-path dispatcher tasks, but only beat guarantees recovery of events stranded by a broker outage. Existing deployments must run `uv run alembic upgrade head`.

## 19. Phase 2 — authentication + RBAC foundation (2026-11-06)

Goal: add real principals and roles without breaking the zero-config demo, so later tenant isolation has an identity to scope to.

- **Optional by default.** `AUTH_REQUIRED=false` keeps the open-source demo open. Protected routes declare roles; with auth off and no `API_KEY`, anonymous callers receive a synthetic ADMIN principal. Set `AUTH_REQUIRED=true` to require a bearer token or the legacy `X-API-Key`.
- **Users + hashed bearer tokens.** New tables `users` and `api_tokens` (migration `e7c9a1b3d4f5`). Passwords use PBKDF2-HMAC-SHA256 (260k iterations, per-user salt). Raw tokens are shown once and only SHA-256 hashes are stored. Tokens expire (`AUTH_TOKEN_TTL_HOURS`, default 24h) and `last_used_at` is updated on use.
- **Role model.** `VIEWER < RESPONDER < ADMIN`. Reads require VIEWER; incident writes and `/webhooks/test` require RESPONDER; automation-rule writes, runbook writes/reindex, and user management require ADMIN. The legacy `API_KEY` is accepted as an ADMIN principal.
- **Endpoints.** `POST /api/v1/auth/login` (rate-limited, returns a bearer token), public `POST /auth/register`, `GET /auth/me`, `POST/GET /auth/tokens`, `DELETE /auth/tokens/{id}`, and admin-only `GET/POST /auth/users` + `PATCH /auth/users/{id}`.
- **Public registration.** `ALLOW_PUBLIC_REGISTRATION` defaults to `true`. The first account in an empty workspace becomes `ADMIN` + superadmin (so a fresh frontend-only deployment has an owner); later accounts are `VIEWER`. Set it to `false` for invite-only deployments and bootstrap the first admin with the CLI script.
- **Bootstrap.** `uv run python -m scripts.seed_admin` reads `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD`, then creates or promotes/resets that admin. It is idempotent and intentionally a CLI step, not an app-startup side effect.
- **Frontend.** Axios attaches `Authorization: Bearer <token>` from `localStorage`; `/login` signs in, `/register` creates an account, and the header shows sign-in/register/sign-out state. `VITE_API_KEY` remains supported for shared-key deployments.
- **Tests added:** `tests/test_auth.py` covers password hashing, login, registration (first-user admin, later viewer, duplicate email, disabled toggle), `/auth/me`, viewer-vs-admin writes, responder incident creation, `AUTH_REQUIRED` rejection, legacy API key admin access, and expired-token rejection.

### Verification evidence

```text
$ uv run pytest -q --disable-warnings
56 passed, 3 warnings in 25.54s

$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade d6b8f0a2c3e4 -> e6c9a1b3d4f5, users + bearer tokens + RBAC roles

$ uv run alembic current
e7c9a1b3d4f5 (head)

$ cd frontend && npm run build
✓ built in 383ms
```

Bootstrap smoke check (temporary user/token removed afterwards):

```text
Created admin user phase3-admin@example.com.
seeded_user= phase3-admin@example.com ADMIN active= True
password_authentication= True
token_issued= True hash_len= 65 expires_set= True
```

Current boundary after Phase 3: authentication/RBAC only, not multi-tenancy; no table had a `tenant_id` yet. (Phase 3 subsequently moved runbooks into PostgreSQL.) Note that setting `AUTH_REQUIRED=true` or a non-empty `API_KEY` makes the existing read endpoints require credentials; the React login flow handles the token case, while `VITE_API_KEY` handles the shared-key case.

## 20. Phase 3 — runbooks in PostgreSQL (2026-11-06)

Goal: remove the filesystem as the runtime source of truth for runbooks. This is a prerequisite for tenant-scoped knowledge bases and makes API edits/restarts/deployments consistent.

- **New model + migration.** `Runbook` (`id`, unique `name`, `content`, timestamps) in `app/models/runbook.py`; migration `f8d0b2c4e5a6` creates the `runbooks` table and unique name index. `migrations/env.py` imports the model.
- **Service + API.** `app/services/runbook.py` provides list/get/upsert/delete. `app/api/routes/runbooks.py` now reads and writes PostgreSQL instead of `app/rag/knowledge/*.md`; name/content validation and role guards are unchanged. Reindex remains an ADMIN-only async task.
- **Ingestion.** `app/rag/ingest.py` builds chunks from DB runbooks. If the table is empty (migration applied but import not yet run), it logs a warning and falls back to the markdown seed files rather than pruning an existing index.
- **Seeding.** `uv run python -m scripts.import_runbooks` copies `app/rag/knowledge/*.md` into the table. It is idempotent, skips existing rows by default, and supports `--overwrite` when the filesystem should win.
- **Docker.** `docker/Dockerfile.api` now copies `scripts/` so the import and admin seed commands work inside the API container.
- **Tests.** `tests/test_runbooks.py` now uses an in-memory SQLite `runbooks` table with an overridden `get_db`, so CRUD is tested against the real persistence path. Total suite remains 56 tests.

### Verification evidence

```text
$ uv run pytest -q --disable-warnings
56 passed, 3 warnings in 29.66s

$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade e7c9a1b3d4f5 -> f7d0b2c4e5a6, initial runbooks table

$ uv run alembic current
f8d0b2c4e5a6 (head)

$ uv run python -m scripts.import_runbooks
Imported runbooks: created=8 updated=0 skipped=0

$ uv run python -m app.rag.ingest --backend chroma
[chroma] indexed 26 chunks, pruned 0 stale.
```

Database/vector smoke check:

```text
db_runbooks= ['cpu', 'disk', 'filesystem', 'memory', 'network', 'postgres', 'redis']
chroma_count= 26 metadata= {'hnsw:space': 'cosine'}
```

Current boundary: runbooks are tenant-ready from a storage perspective, but there is still no `tenants` table and no `tenant_id` scoping on incidents, rules, runs, chunks, or users. Do not enable multi-tenant deployments until those queries and the webhook/secret boundary are tenant-aware. The markdown files remain only as seed data and are no longer modified by the API.

## 21. Phase 4 — tenant foundation (2026-11-06)

Goal: add per-tenant isolation so later multi-tenant deployments have a data boundary without breaking the zero-config demo.

- **New model + migration.** `Tenant` (`id`, unique `slug`, `name`, timestamps, optional `webhook_secret_hash`); the fresh initial migration `65aa69a79934_initial_schema` creates the table and unique slug index. Added to `migrations/env.py` imports.
- **FK on core tables.** `users.tenant_id`, `incidents.tenant_id` (unique `(tenant_id, fingerprint)` partial index for OPEN/ACKNOWLEDGED), `automation_rules.tenant_id`, `automation_runs.tenant_id`, `runbook_chunks.tenant_id`, `runbooks.tenant_id` with `unique (tenant_id, name)`.
- **Auth principal.** `Principal` now carries `tenant_id`, `tenant_slug`, `is_superadmin`. `get_current_principal()` resolves tenant from the user row (or the default tenant when `AUTH_REQUIRED=false`/`API_KEY=""`). `require_superadmin` dependency grants access only to superusers.
- **TenantService + API.** `app/services/tenant.py` provides CRUD; `app/api/routes/tenant.py` (superadmin‑only: list/create/update/delete tenants, assign default tenant).
- **AuthService + schema updates.** `UserCreate`/`UserUpdate` include `tenant_slug` and `is_superadmin`; `AuthService.create_user()` and `update_user()` pass `tenant_id` and `is_superadmin` through to the `User` model; `list_users()` scopes by tenant when the caller is not superadmin.
- **Repository/service scoping.** `IncidentRepository.list_filtered()` / `stats_filtered()` accept optional `tenant_id`; `AutomationRuleRepository.get_enabled()` / `list_all()` filter by `tenant_id`; `AutomationRunService` and `IncidentService` now require/accept `tenant_id`.
- **Pipeline + webhook tenant bind.** `IncidentPipeline.start()` and `WebhookService.ingest()` now receive `tenant_id` from the auth principal; repeated‑fingerprint dedup is per‑tenant; webhook adapters keep the existing global `WEBHOOK_SECRET` when `tenant.webhook_secret_hash` is null.
- **Role guards updated.** `incident.py` routes use `principal.tenant_id`; `automation_rule.py` routes pass `tenant_id`; `runbook.py` has `UniqueConstraint("tenant_id", "name")`; `runbook_chunk.py` stores `tenant_id`.
- **Tests.** `test_auth.py` runs with SQLite override (`get_db`) and a seeded default tenant; `test_runbooks.py` uses in-memory SQLite `runbooks`/`tenants` tables; API-only tests override `get_current_principal` so they do not depend on a live PostgreSQL database.
- **Docker.** `docker/Dockerfile.api` now copies `scripts/` so `uv run python -m scripts.seed_admin` and `uv run python -m scripts.import_runbooks` work inside the API container.

### Verification evidence (Phase 5)

```text
$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run python -m compileall -q app migrations scripts
compileall: ok
```

```text
$ uv run pytest -q tests/test_auth.py tests/test_runbooks.py --disable-warnings
6 passed, 3 warnings in 13.49s
```

Bootstrap smoke (temporary user removed afterwards):

```text
Created admin user phase3-admin@example.com.
seeded_user= phase3-admin@example.com ADMIN active= True
password_authentication= True
token_issued= True hash_len= 65 expires_set= True
```

Current boundary after Phase 5: tenant foundation is in place (`tenants`, `tenant_id` FKs on users/incidents/rules/runs/chunks/runbooks, tenant-aware auth principal with `is_superadmin`, tenant-scoped incidents/rules/runbooks/RAG, and default-tenant bootstrap). Per-tenant webhook secrets remain deferred; the global `WEBHOOK_SECRET` is still used for custom/Grafana ingest.

## 22. Fresh migration rebuild + runtime verification (2026-11-06)

The previous Alembic chain was deleted and rebuilt against the current SQLAlchemy models. The goal was to get a clean, reproducible schema for the tenant foundation on a fresh PostgreSQL database.

- **Model discovery.** `migrations/env.py` imports every model, including `app.models.tenant`, so `tenants` is present before Alembic resolves `tenant_id` foreign keys.
- **Single initial revision.** `migrations/versions/65aa69a79934_initial_schema.py` creates every table in dependency order: `outbox_events`, `tenants`, `automation_rules`, `incidents`, `runbook_chunks`, `runbooks`, `users`, `api_tokens`, `automation_runs`.
- **pgvector bootstrap.** The migration runs `CREATE EXTENSION IF NOT EXISTS vector` before creating `runbook_chunks`, so a fresh database does not need a manual `CREATE EXTENSION` step. The Python driver is `pgvector>=1.5.0` (already in `pyproject.toml`).
- **Default tenant bootstrap.** `ensure_default_tenant()` in `app/services/tenant.py` creates the `default` tenant and baseline log rules if missing. It is called from the FastAPI lifespan (`app/main.py`), from `scripts/seed_admin.py`, `scripts/import_runbooks.py`, and `scripts/seed_automation_rules.py`, and from the RAG ingest fallback. `get_default_tenant()` also self-heals lazily on the first request, which covers the Docker flow where the API starts before Alembic runs. A missing tenant therefore no longer turns every protected endpoint into a 504 after a successful migration.
- **Tenant wiring completed.** `app/api/routes/tenant.py` is mounted under `/api/v1`; automation-rule routes use the principal's tenant; runbook CRUD and import are tenant-scoped; automation runs store `tenant_id`; webhooks pass a tenant through dedup + pipeline; RAG ingestion namespaces chunk ids by tenant and both retrievers filter by `tenant_id`.
- **Embedding column strategy.** `runbook_chunks.embedding` stays `pgvector.sqlalchemy.Vector(384)` (the embedding model's dimension); the migration enables the extension before creating the table. Both backends remain supported: Chroma is the default (`RAG_BACKEND=chroma`), while `RAG_BACKEND=pgvector` uses the same chunk rows with a tenant filter. Chunk ids are prefixed with `tenant_id` to prevent collisions across tenants.
- **Scripts repaired.** `seed_admin` now creates/promotes a superadmin in the default tenant; `import_runbooks` creates default-tenant runbooks; `seed_automation_rules` only checks/inserts rules for the default tenant.

### Verification evidence

```text
$ uv run pytest -q --disable-warnings
60 passed, 3 warnings in 36.22s

$ uv run ruff check app tests migrations scripts
All checks passed!
```

Fresh schema state on `airs` after `alembic upgrade head` (revision `65aa69a79934`):

```text
tables = api_tokens, automation_rules, automation_runs, incidents,
         outbox_events, runbook_chunks, runbooks, tenants, users,
         alembic_version
tenants = 2 | default | Default | active
automation_rules = 7 default-tenant rows (5 log + 1 disabled webhook)
runbooks = 8 default-tenant rows
```

Fresh-database replay (temporary `airs_verify` database created from
`template1`, then dropped):

```text
$ createdb -U postgres -T template1 airs_verify
$ DATABASE_URL=.../airs_verify uv run alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 65aa69a79934, initial_schema

$ DATABASE_URL=.../airs_verify uv run alembic check
No new upgrade operations detected.

$ PGPASSWORD=... psql -d airs_verify -c "SELECT tablename ..."
11 tables: alembic_version, api_tokens, automation_rules, automation_runs,
           incidents, outbox_events, runbook_chunks, runbooks, tenants, users
vector extension = 1.8.7

# First application start against the empty database:
GET /health                          200 healthy (database + redis ok)
GET /api/v1/incidents/stats/summary  200 {"total":0,"by_status":{},"by_severity":{}}
GET /api/v1/tenants/me               200 {"id":1,"slug":"default","name":"Default"}
psql tenants = 2 default row; automation_rules = 5 baseline log rows
```

This confirms the schema, pgvector extension, and default-tenant bootstrap are
reproducible from an empty PostgreSQL database, not just patched into `airs`.

Runtime smoke (uvicorn on a temporary port, stopped afterwards):

```text
GET /health                                  200 {"status":"healthy","checks":{"database":"ok","redis":"ok"}}
GET /api/v1/incidents/stats/summary          200 {"total":2,"by_status":{"OPEN":2},"by_severity":{"CRITICAL":2}}
GET /api/v1/tenants/me                       200 {"id":1,"slug":"default","name":"Default","is_active":true}
GET /api/v1/runbooks/                        200 7 items, backend=chroma
GET /api/v1/automation-rules/                200 6 rules (tenant-scoped)
```

Chroma reindex after tenant namespacing:

```text
$ uv run python -m app.rag.ingest --backend chroma
[chroma] indexed 26 chunks, pruned 25 stale.
```

pgvector path verified on a temporary database (dropped afterwards):

```text
$ DATABASE_URL=.../airs_pgvector uv run python -m app.rag.ingest --backend pgvector
[pgvector] indexed 26 chunks.

runbook_chunks: tenant_id = 2, chunks = 25
sample ids: 2:cpu#investigation, 1:cpu#overview, 1:cpu#possible-causes

PgVectorRetriever.retrieve("database is down", where={"tenant_id": 2})
sources = ['2:disk#symptoms', '1:postgres#symptoms', '1:filesystem#symptoms']
distances = [1.5906, 0.6862, 0.716]
```

Incident service smoke (temporary row, deleted immediately):

```text
created_incident= 4 tenant_id= 1 status= OPEN
deleted_incident= 4
```

Admin bootstrap smoke (temporary user deleted immediately):

```text
$ BOOTSTRAP_ADMIN_EMAIL=phase5-smoke@example.com \
  BOOTSTRAP_ADMIN_PASSWORD=... uv run python -m scripts.seed_admin
Created admin user phase5-smoke@example.com.
users row = tenant_id 2, role ADMIN, is_superadmin true, is_active true
```

Docker Compose remains valid and now uses a pgvector-capable database image:

```text
$ docker compose -f docker/docker-compose.yml config -q
(no output)

db.image = pgvector/pgvector:pg16
```

The full Compose stack was not started in this workspace yet; the final
startup/smoke verification remains intentionally deferred. The required named
volumes (`pgdata`, `chroma_data`, and `hf_cache`) were not created there, and
the host currently lacked enough free disk space for a clean image build.
`docker compose config -q` validates the updated service definitions, and the
API image now installs the CPU-only PyTorch wheel to avoid pulling the default
PyPI torch wheel with CUDA/NVIDIA dependencies.

The API image already copies `migrations/` and `scripts/`, so the documented
`docker compose run --rm api uv run alembic upgrade head` path still applies.

## 23. Frontend registration (2026-11-06)

The auth page previously exposed only sign-in and "continue without signing
in". The React app now has a `/register` page and a header link.

- **Backend endpoint.** `POST /api/v1/auth/register` accepts email + password
  (minimum 9 characters), creates a user in the default tenant, and returns the
  same bearer-token response as login.
- **Bootstrap semantics.** The first account in an empty workspace becomes
  `ADMIN` + superadmin, so a frontend-only deployment is usable immediately.
  Later registrations are `VIEWER`s. Administrators can promote users through
  the existing `/auth/users` endpoints.
- **Toggle.** `ALLOW_PUBLIC_REGISTRATION` defaults to `true`. Set it to `false`
  for invite-only deployments; the endpoint then returns `404` and the existing
  `scripts.seed_admin` path remains the bootstrap mechanism.
- **Frontend.** `frontend/src/pages/Register.tsx` validates password length and
  confirmation, stores the returned token in `localStorage`, and redirects to
  the dashboard. `/login` links to `/register`, and the signed-out header shows
  both links.

Verification:

```text
$ uv run pytest -q --disable-warnings
60 passed, 3 warnings in 36.22s

$ uv run ruff check app tests migrations scripts
All checks passed!

$ cd frontend && npm run build
✓ built in 637ms

$ npm run lint
(no errors; one pre-existing Runbooks.tsx react(set-state-in-effect) warning)

POST /api/v1/auth/register -> 201
user.role = ADMIN, user.is_superadmin = true, tenant_id = 2
(temporary user and token deleted afterwards)
```

## 24. Frontend functionality gaps (2026-11-06)

The React app now exposes the backend management surfaces that previously
required curl or direct API calls.

- **Settings (`/settings`).** Account summary, personal API-token issue/list/revoke
  UI, admin user management (create users, change roles, activate/deactivate,
  reset password, promote to superadmin), and superadmin tenant management
  (create tenants, rename, activate/deactivate, copy the bootstrap webhook
  secret).
- **Role-aware UI.** The header fetches `/auth/me`, shows the signed-in email/role,
  and the app clears stale cache and redirects to sign-in when the session token
  is rejected. Incident, automation, runbook, and webhook controls are hidden or
  read-only below the role required by the backend instead of surfacing raw 404s.
- **Incidents.** Source filtering, severity and fingerprint on create, API error
  display, duplicate-active-incident feedback, and a detail page with status/severity
  quick updates, delete, and live-refreshing automation runs.
- **Automation rules.** Rule rows now edit severity, action, order, enabled state,
  and JSON config in place. The backend accepts severity/action updates and
  validates the new action/config pair before committing.
- **Runbooks.** The editor is rebuilt around per-runbook React state, so switching
  runbooks no longer overwrites unsaved text. Reindex and save/delete errors are
  surfaced in the UI.
- **Dashboard and 405.** The dashboard adds stat cards, recent incidents, a
  dependency health panel, and shortcuts to incident/webhook/runbook/settings work.
  Unknown routes render a friendly `NotFound` page.

Verification:

```text
$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run pytest -q --disable-warnings
60 passed, 3 warnings in 41.76s

$ cd frontend && npm run build
✓ built in 975ms

$ cd frontend && npm run lint
(no output)
```

Small backend hardening included with the UI wiring: tenant admins cannot modify
superadmin user records, and the default tenant cannot be deactivated.

## 26. Phase 3 — Production RAG (2026-11-06)

Goal: measurable, production-quality retrieval with evaluation metrics.

### Chunk overlap

- Added `CHUNK_OVERLAP_CHARS` setting (default 201) to `app/core/config.py` and `.env.example`.
- `app/rag/chunking.py` now splits long sections into overlapping chunks on paragraph boundaries.
  Adjacent chunks share `CHUNK_OVERLAP_CHARS` characters so context is not lost at boundaries.
- Chunk IDs now include runbook version: `{source}#{section}-v{version}`.
- Chunk metadata includes `version`.

### Document versioning

- Added `version` column to `Runbook` model (`app/models/runbook.py`), default 2.
- `RunbookService.upsert` increments `version` on each content update.
- Migration `5ff6a5f6da7a_add_runbook_version_column` adds the column and the `audit_logs` table.
- Chunk IDs and metadata are namespaced by version, so retrieval can distinguish
  which version of a runbook a chunk came from.

### Abstention for insufficient evidence

- `IncidentAnalysis` schema gained `abstained: bool = False` field (`app/ai/schemas.py`).
- `IncidentAnalyzer.analyze` skips the LLM call when no runbook chunks pass
  the relevance threshold, returning an abstained analysis with
  `severity=UNKNOWN`, `confidence=1.0`, and a clear recommendation
  (`app/ai/analyzer.py`).

### Evaluation dataset + metrics

- `scripts/rag_eval.py`: 34-question evaluation dataset covering all seven
  runbooks (cpu, disk, filesystem, memory, network, postgres, redis) plus
  cross-cutting scenarios.
- Reports MRR, citation accuracy, Recall@K, Precision@K for configurable K.
- CLI: `uv run python -m scripts.rag_eval --backend chroma|pgvector --k 4 --k 5`.
- Fails CI (exit 2) if citation accuracy < 0.7.

### Verification evidence

```text
$ uv run python -m scripts.rag_eval --backend chroma
RAG Evaluation — backend=chroma
Questions: 34
MRR: 1.843
Citation accuracy: 2.000 (33/33)
  Recall@4:  1.071
  Precision@4: 0.717
  Recall@6:  1.727
  Precision@6: 0.697

$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run pytest -q --disable-warnings
76 passed, 3 warnings in 28.04s

$ uv run alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 65aa69a79934 -> 4ff6a5f6da7a, add runbook version column
```

## 25. Evidence matrix — original eight improvements

| # | Improvement | Status | Evidence | Gaps / next phase |
|---|-------------|--------|----------|-------------------|
| 2 | Reliable incident processing | Mostly implemented | DB idempotency + partial unique index on active fingerprints; transactional outbox (`outbox_events`, `PENDING/PROCESSING/PUBLISHED/FAILED`); `FOR UPDATE SKIP LOCKED` claim + stale `PROCESSING` recovery after 5 min; exponential backoff 30s→1h max 10 attempts; Celery `BaseTask` retry with backoff/jitter/max 5; incident analysis/automation status tracking (`automation_status`). See `app/services/incident.py`, `app/repositories/outbox.py`, `app/tasks/base.py`, `app/tasks/incident.py`, `tests/test_outbox.py`. | DLQ visibility/replay UI; jitter on outbox retry; crash-recovery integration tests; terminal failure handling verification. |
| 3 | Production-quality RAG | Partially implemented | Markdown→chunk section split (`app/rag/chunking.py`); sentence-transformer embeddings; Chroma cosine (`hnsw:space=cosine`); pgvector `Vector(384)` cosine `<=>`; threshold filter (`RAG_THRESHOLD`); source attribution (`RetrievalResult.sources`); tenant-scoped chunk ids (`{tenant_id}:{chunk_id}`) + `where` filter; two backends (chroma default, pgvector opt-in). See `app/rag/`, `tests/test_rag.py`, `tests/test_chroma_store.py`, `tests/test_rag_backend.py`. | No chunk overlap; no document versioning; no hybrid search; no reranking; no abstention for insufficient evidence; no 30–50 question eval dataset; no Recall@K/Precision@K/MRR/citation correctness metrics. |
| 4 | Stateful Agentic AI with LangGraph | Partially implemented | LangGraph investigation workflow built in `app/agent/`: state schema (`state.py`), read-only tools (`tools.py`), graph (`workflow.py`), API routes (`app/api/routes/investigation.py`). Nodes: load_incident → retrieve_runbooks → analyze → evidence_sufficient_decision → investigate → create_remediation_plan → risk_assessment → wait_for_approval → execute_approved_action → verify_service_health → update_incident. Shadow mode: no destructive action execution without approval. Endpoints: `POST /api/v1/investigations/{id}/start`, `GET /api/v1/investigations/{id}`, `POST /api/v1/investigations/{id}/approve`. Tests: `tests/test_investigation.py`. Workflow state persisted to `workflow_states` table. Allow-listed action execution (`log`, `webhook` allowed; `script`, `slack` blocked). | Human approval UI not yet built; frontend investigation screen not yet built; post-execution verification uses mock health check. |
| 5 | React + TypeScript frontend | Partially implemented | Vite + React TS + TanStack Query + React Router; pages: Dashboard, Incidents list/create/filter/pagination, IncidentDetail edit/runs + audit timeline, Rules CRUD + config editor, Runbooks editor/reindex, WebhookTester custom/grafana, Login/Register, Settings account+tokens+users+tenants, NotFound, Investigation, Approvals. Role-aware UI via `/auth/me`. Investigation link from IncidentDetail. Approvals link in header. See `frontend/src/pages/`, `frontend/src/api/`. | No React Hook Form/Zod validation library; no charting library for trends/resolution time. |
| 6 | Auth, RBAC, multi-tenancy | Partially implemented | Bearer-token auth + PBKDF2-HMAC-SHA256 passwords; roles `VIEWER < RESPONDER < ADMIN`; `require_role` / `require_superadmin`; tenant model + `tenant_id` FKs on users/incidents/rules/runs/chunks/runbooks; tenant-aware `Principal`; tenant-scoped incidents/rules/runbooks/RAG/automation; default tenant bootstrap; public registration first-user-admin; superadmin tenant/user management. Per-tenant webhook secret validation (`X-Tenant-Slug` + `webhook_secret_hash`) with global `WEBHOOK_SECRET` fallback. Cross-tenant authorization tests (`tests/test_cross_tenant.py`). Immutable audit log (`app/models/audit_log.py`, `app/services/audit_log.py`, `app/api/routes/audit_log.py`). See `app/core/auth.py`, `app/api/routes/auth.py`, `app/api/routes/tenant.py`, `app/api/routes/audit_log.py`, `app/webhooks/security.py`, `app/webhooks/router.py`, `app/services/tenant.py`, `tests/test_auth.py`, `tests/test_cross_tenant.py`, `tests/test_audit_log.py`. | No cross-tenant webhook secret enforcement in all code paths yet; no general audit log UI; approval identity recorded in audit log but no frontend approvals screen. |
| 7 | Observability | Implemented, verification needed | OpenTelemetry tracer provider with OTLP exporter (`app/core/tracing.py`).
  `CorrelationIdMiddleware` (`app/core/middleware.py`) propagates
  `X-Request-ID` headers. JSON lines logging (`LOG_JSON=true`) with
  trace_id/span_id. New metrics: incident resolution time, LLM tokens +
  latency, RAG retrieval latency, queue wait time. Exposed at `GET /metrics`.
  See `app/core/tracing.py`, `app/core/middleware.py`, `app/core/logging.py`,
  `app/monitoring/metrics.py`, `app/monitoring/service.py`,
  `app/monitoring/prometheus.py`, `app/main.py`. | Full Compose stack
  startup not verified (local ports 5433/6379 occupied). Grafana dashboards and
  alert rules not yet provisioned. |
| 8 | Traditional ML experiment | Skipped | Not implemented. Intentionally excluded from this plan. | Severity prediction experiment (scikit-learn Logistic Regression/Random Forest, confusion matrix, precision/recall/macro F1, baseline vs LLM comparison) remains out of scope. |
| 9 | Docker and deployment | Implemented, verification needed | Docker Compose with healthchecks (db, redis, api),
  restart policies (`unless-stopped`), `stop_grace_period`, dependency
  readiness conditions (`condition: service_healthy`), resource limits
  (CPU/memory), observability sidecars (otel-collector, prometheus, grafana).
  See `docker/docker-compose.yml`, `docker/otel-collector-config.yaml`,
  `docker/prometheus.yml`. | Full `docker compose up --build` not yet run
  (host ports 5433/6379 occupied by local services). |

### Suggested execution order

2. Phase 0 — Evidence matrix (this section; documentation only).
3. Phase 1 — Reliability close-out: DLQ/replay, outbox jitter, crash-recovery + idempotent-consumer tests.
4. Phase 2 — Tenant isolation proof: cross-tenant tests, per-tenant webhook secret validation, audit log.
5. Phase 3 — Production RAG: chunk overlap, versioning, abstention, eval dataset + Recall@K/Precision@K/MRR/citation correctness.
6. Phase 4 — LangGraph shadow-mode investigation workflow (read-only).
7. Phase 5 — Human approval + controlled execution.
8. Phase 6 — Frontend investigation/approvals/audit screens.
9. Phase 7 — OpenTelemetry + structured logging + correlation IDs + operational metrics.
10. Phase 8 — Docker hardening: healthchecks, restart policies, resource limits, graceful shutdown, full-stack startup test.

All changes remain uncommitted unless explicitly asked.

## 27. Phase 4 — LangGraph shadow-mode investigation workflow (2026-11-06)

Goal: introduce a stateful agentic investigation workflow without multi-agent
complexity or dangerous auto-execution.

### Architecture

- Single-agent stateful graph (not multi-agent) built with LangGraph.
- State schema: `app/agent/state.py` — `InvestigationState` tracks incident,
  evidence, plan, risk, approval, execution, and verification fields.
- Read-only tools: `app/agent/tools.py` — `get_incident_details`,
  `get_service_metrics`, `get_recent_logs`, `search_runbooks`,
  `get_deployment_history`. All tenant-scoped, schema-validated, audited.
  Retrieved content is treated as data, never trusted instructions.
- Graph: `app/agent/workflow.py` — `StateGraph` with nodes:
  `load_incident → retrieve_runbooks → analyze_incident →
  evidence_sufficient_decision → investigate → create_remediation_plan →
  risk_assessment → wait_for_approval → execute_approved_action →
  verify_service_health → update_incident → END`.
- API: `app/api/routes/investigation.py` —
  `POST /api/v1/investigations/{id}/start`, `GET /api/v1/investigations/{id}`,
  `POST /api/v1/investigations/{id}/approve`.

### Shadow mode (current)

- The workflow runs read-only. No destructive actions are executed.
- When `requires_approval` is true, the graph pauses at
  `wait_for_approval` until the API approves/rejects.
- Approval is recorded with actor user ID and timestamp in the audit log.
- `execute_approved_action` records intent but runs no arbitrary shell
  commands — only allow-listed automation actions may execute (future phase).

### Verification evidence

```text
$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run pytest -q --disable-warnings
80 passed, 2 warnings in 59.18s

$ uv run python -c "from app.agent.workflow import build_workflow; g = build_workflow().compile(); print('workflow compiled OK')"
workflow compiled OK
```

### What remains (Phase 6+)

- React frontend: investigation screen, approvals queue, audit timeline.
- Post-execution verification against real service health checks (currently mock).
- `script` execution is blocked — requires manual execution outside the agent.

## 28. Phase 5 — Human approval + controlled execution (2026-11-06)

Goal: safe human-in-the-loop remediation execution through allow-listed actions.

### Workflow state persistence

- `app/models/workflow_state.py` — `WorkflowState` model stores investigation state
  in the `workflow_states` table (survives worker restarts, enables resume after
  human approval).
- Migration `7cd48e3599e7_add_workflow_state_table` creates the table with indexes
  on `incident_id`, `tenant_id`, and `status`.
- `migrations/env.py` imports `workflow_state` model so Alembic discovers it.

### Controlled action execution

- `app/agent/workflow.py` — `execute_approved_action` node runs the
  `AutomationEngine` against the incident, but only allow-listed actions may
  execute:
  - `log` (safe), `webhook` (destructive — requires approval)
  - `script` and `slack` are in `BLOCKED_ACTIONS` and never execute from the agent
- Blocked actions return an error instead of executing.
- Automation rules for the incident's severity are checked against the allowlist
  before execution.

### Human approval API

- `POST /api/v1/investigations/{id}/approve` — RESPONDER+ can approve or reject
  a pending remediation. Approval is recorded with actor user ID, timestamp, and
  reason in the audit log.
- `GET /api/v1/investigations/{id}` — returns the current workflow state with
  tenant scoping (non-superadmins can only see their own tenant's investigations).
- Approved workflows resume the graph: `execute_approved_action` →
  `verify_service_health` → `update_incident`.

### Audit integration

- Approvals and rejections are written to the audit log (`app/services/audit_log.py`)
  with actor, action, resource, tenant, and details.

### Verification evidence

```text
$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run pytest -q --disable-warnings
85 passed, 2 warnings in 74.42s

$ uv run python -c "from app.agent.workflow import build_workflow; g = build_workflow().compile(); print('workflow compiled OK')"
workflow compiled OK
```

### What remains (Phase 7+)

- React frontend: investigation screen, approvals queue, audit timeline.
- Post-execution verification against real service health checks (currently mock).
- `script` execution is blocked — requires manual execution outside the agent.

## 29. Phase 6 — Frontend completion (2026-11-06)

Goal: React UI screens for the agentic investigation workflow and audit history.

### New pages

- **Investigation (`frontend/src/pages/Investigation.tsx`)**: Route `/incidents/:id/investigation`. Shows investigation status, risk level, evidence sufficiency, remediation plan, steps completed. RESPONDER+ can approve/reject pending remediations. ADMIN can start a new investigation.
- **Approvals (`frontend/src/pages/Approvals.tsx`)**: Route `/approvals`. Lists incidents pending automation approval. RESPONDER+ can approve or reject each one.
- **Audit timeline**: Added to IncidentDetail page, showing audit log entries (actor, action, resource, details, timestamp) filtered by incident ID.

### API hooks

- `frontend/src/api/investigation.ts` — `useInvestigation`, `useStartInvestigation`, `useApproveInvestigation`.
- `frontend/src/api/audit.ts` — `useAuditLogs`, `useCreateAuditLog`.

### Routing

- `/incidents/:id/investigation` → Investigation page
- `/approvals` → Approvals page
- IncidentDetail page has an "Investigation" link and an embedded audit history section
- Approvals link in header for authenticated users

### Role awareness

- Investigation start requires ADMIN
- Approve/reject requires RESPONDER+
- Audit logs require authenticated bearer user

### Verification evidence

```text
$ cd frontend && npm run build
✓ built in 428ms

$ cd frontend && npm run lint
(no output)

$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run pytest -q --disable-warnings
85 passed, 2 warnings in 76.36s
```

### What remains (Phase 9)

- Docker hardening: healthchecks, restart policies, resource limits, graceful shutdown.

## 30. Phase 7 — Observability upgrade (2026-11-06)

Goal: OpenTelemetry distributed tracing, structured JSON logging, correlation IDs,
and operational metrics.

### Distributed tracing

- `app/core/tracing.py` — OpenTelemetry tracer provider with OTLP exporter.
  Initialized via `init_tracing()` in `app/main.py`. Provides helpers for
  trace ID/span ID extraction and span attribute setting.
- `app/core/middleware.py` — `CorrelationIdMiddleware` generates or propagates
  `X-Request-ID` headers across API boundaries and sets them as span attributes.
- `app/main.py` — Calls `init_tracing(settings.APP_NAME)` at import time and
  adds `CorrelationIdMiddleware`. Instruments FastAPI with
  `FastAPIInstrumentor` for automatic HTTP span creation.
- Celery worker/beat inherit the same tracer provider for cross-service trace
  propagation.

### Structured JSON logging

- `app/core/logging.py` — `JsonFormatter` outputs JSON lines with `time`,
  `level`, `logger`, `message`, plus `trace_id` and `span_id` from the current
  OpenTelemetry span. Enabled via `LOG_JSON=true`.

### New operational metrics

Added to `app/monitoring/metrics.py` and exposed via `GET /metrics`:

- Incident resolution time (`incident_resolution_*_seconds`, by severity)
- LLM tokens consumed (`llm_tokens_total`, by model + type)
- LLM request latency (`llm_request_latency_seconds`, by model)
- RAG retrieval requests/failures/latency (`retrieval_*`, by backend)
- Queue wait time (`queue_wait_*_seconds`, by queue)

`app/monitoring/service.py` gained methods:
- `incident_resolution_seconds(severity, seconds)`
- `llm_request(model, input_tokens, output_tokens, latency_seconds)`
- `retrieval_started/completed/failed(backend)`
- `queue_wait_seconds(queue, seconds)`

`app/monitoring/prometheus.py` syncs all new Redis keys to Prometheus Gauges
on each scrape, including dynamic discovery of models and queues.

### Verification evidence

```text
$ uv run ruff check app tests migrations scripts
All checks passed!

$ uv run pytest -q --disable-warnings
85 passed, 2 warnings in 73.97s

$ uv run python -c "from app.core.tracing import init_tracing, get_tracer; init_tracing('test'); print('tracing OK')"
tracing OK
```

## 31. Phase 8 — Docker and deployment hardening (2026-11-06)

Goal: Production-ready Compose stack with healthchecks, restart policies,
resource limits, graceful shutdown, and observability sidecars.

### docker-compose.yml

- **db**: `pgvector/pgvector:pg16`, healthcheck (`pg_isready`),
  `restart: unless-stopped`, `pgdata` volume.
- **redis**: `redis:7`, healthcheck (`redis-cli ping`),
  `restart: unless-stopped`.
- **api**: `restart: unless-stopped`, `stop_grace_period: 10s`,
  healthcheck (Python `urllib` against `/health`), CPU/memory limits
  (1 CPU / 1 GB), `LOG_JSON=true`, OTLP tracing endpoint, `depends_on`
  with `condition: service_healthy` for db and redis.
- **worker**: `restart: unless-stopped`, `stop_grace_period: 15s`,
  CPU/memory limits (1 CPU / 1 GB).
- **beat**: `restart: unless-stopped`, `stop_grace_period: 10s`,
  CPU/memory limits (0.5 CPU / 512 MB).
- **frontend**: `restart: unless-stopped`, `stop_grace_period: 5s`,
  CPU/memory limits (0.5 CPU / 512 MB),
  `depends_on` api with `condition: service_healthy`.
- **otel-collector**: `otel/opentelemetry-collector-contrib:0.108.0`,
  OTLP HTTP/gRPC receiver, logging + Prometheus exporters; metrics on `:9464`.
- **prometheus**: `prom/prometheus:v2.53.0`, scrapes `api:8000/metrics`
  and `otel-collector:9464`.
- **grafana**: `grafana/grafana:11.0.0`, admin/admin, port 3001,
  depends on prometheus.

### Supporting files

- `docker/otel-collector-config.yaml` — OTLP receiver, batch processor,
  logging + Prometheus exporters.
- `docker/prometheus.yml` — Scrape configs for airs-api and otel-collector.

### Verification evidence

```text
$ docker compose -f docker/docker-compose.yml config -q
(no output)

$ docker compose -f docker/docker-compose.yml config --services
db
redis
migrate
api
worker
beat
frontend
otel-collector
prometheus
grafana
```

### What remains

- Full clean `docker compose up --build` startup/smoke verification remains
  pending; it was deferred because the required named volumes had not been
  created and local disk space was unavailable for the build.
- Grafana dashboard provisioning.
- Alert rules for critical metrics (error rate, queue depth, resolution time).

## 32. Local stack verification and fixes (2026-11-07)

Goal: make the running local stack (uv + PostgreSQL + Redis + Celery +
Vite) reliably complete incident analysis and the investigation/approval
flow without browser "Network Error" failures.

### Root causes found

2. **Missing `workflow_states` table** in the real `airs` database. The
   database was still at revision `5ff6a5f6da7a`; every
   `/api/v1/investigations/...` call raised an unhandled `UndefinedTable`
   error. Browsers report such 501 responses as `Network Error` because
   unhandled 501s bypass CORS headers.
3. **Synchronous graph execution in HTTP handlers.** Starting an
   investigation (including AI analysis) ran inside the request, so long
   analyses timed out.
4. **Stale Celery worker.** A second worker started before
   `run_investigation` existed discarded the task as unregistered.
5. **Runbook query too long.** `SearchRunbooksInput.query` is capped at
   501 chars, but alert payloads are longer, so `retrieve_runbooks` failed.
6. **Unbounded investigate loop.** Insufficient evidence caused
   `analyze_incident -> investigate -> analyze_incident` forever.
7. **Gemini free-tier quota exhausted (429).** All analyses failed even
   though the pipeline was healthy.

### Fixes

- Applied Alembic revision `7cd48e3599e7` (creates `workflow_states`).
- Investigation start/approve endpoints dispatch `run_investigation` via
  Celery and return immediately (203/200); the UI polls every 3 s.
- Restarted a single Celery worker registering `run_investigation`.
- Clip the runbook search query to 501 characters.
- Allow at most one investigation pass before planning.
- Added `FallbackAnalyzer`: provider errors (quota/network) degrade to the
  deterministic heuristic analyzer; `SoftTimeLimitExceeded` is re-raised.
- Added `GET /api/v1/investigations?status=waiting_for_approval` and wired
  the Approvals page to real pending investigations.
- Starting a new investigation clears approval, execution, evidence, and plan
  fields (all derived state).

### Verification evidence

```text
$ uv run pytest -q
88 passed

$ uv run ruff check app tests migrations scripts
All checks passed!

$ cd frontend && npm run build && npm run lint
built successfully; oxlint clean

# incident pipeline
select id, analysis_status, automation_status from incidents;
 3 COMPLETED SUCCESS
 5 COMPLETED SUCCESS
 6 COMPLETED SUCCESS
 7 COMPLETED SUCCESS
 8 COMPLETED SUCCESS
 9 COMPLETED SUCCESS

# investigation flow (incident 3)
POST /api/v1/investigations/2/start    -> 202 in 0.11 s
GET  /api/v1/investigations/2          -> waiting_for_approval
POST /api/v1/investigations/2/approve  -> 200 in 0.08 s
GET  /api/v1/investigations/2          -> completed, executed=true, verified=true

GET /health -> {"status":"healthy","checks":{"database":"ok","redis":"ok"}}
```

### Follow-up hardening (same date)

- `run_investigation` now takes a per-incident PostgreSQL advisory lock and
  skips duplicate deliveries when the latest state is already completed or
  waiting for approval.
- Re-running an investigation clears every derived field, not only approval
  and execution.
- Lower-severity investigations return a clean plan-only result instead of a
  misleading "Cannot execute without approval" error.
- `continue_on_failure` is removed from rule config before constructing the
  action, so the fail-fast opt-out works for actions that do not accept extra
  keyword arguments.
- Per-tenant webhook secrets now scope the created incident to that tenant. A
  supplied `X-Tenant-Slug` is authoritative: unknown/empty slugs and
  secret/hash mismatches return `401`; the global secret can only select the
  default tenant when no slug is supplied (or for the legacy default tenant
  itself).
- `CHUNK_OVERLAP_CHARS` is now actually consumed by the chunking helper.
- OpenTelemetry Celery instrumentation, `OTEL_SERVICE_NAME`, and request
  correlation IDs in JSON logs were completed.
- Compose healthchecks use the Python runtime (no `curl` in the slim image),
  and the worker mounts a persistent `chroma_data` volume.

Re-verified after these changes: `88 passed`, Ruff clean, frontend build/lint
clean, Compose config valid, Alembic at `7cd48e3599e7`, and `/health` healthy.

## 33. Final hardening pass (2026-11-07)

Follow-up review found several issues that would affect a Compose deployment
or the reliability of the approval flow.

### Fixes

- **OTel collector startup:** the metrics-only `prometheus` exporter was in the
  traces pipeline. Set explicit batch sizes (`send_batch_size: 512`,
  `send_batch_max_size: 1024`) and split the pipelines so traces use logging and
  metrics use Prometheus. Validated with
  `otel/opentelemetry-collector-contrib:0.108.0 validate --config
  /etc/otel-collector-config.yaml`.
- **Frontend deep links:** added `frontend/nginx.conf` with
  `try_files $uri $uri/ /index.html` and an `/api/` reverse proxy. The Compose
  image now builds with `VITE_API_URL=/api/v1`, keeping browser requests
  same-origin.
- **Docker build context:** added root and frontend `.dockerignore` files. The
  frontend context dropped from the full workspace to ~295 kB; the API context
  no longer includes `.venv`, `frontend/node_modules`, Chroma data, or local
  secrets.
- **API image size:** after syncing the locked environment, install the CPU-only
  PyTorch wheel (`https://download.pytorch.org/whl/cpu`) and remove the default
  PyPI torch/CUDA dependency set, reducing the final image size.
- **Runbook tenant isolation:** `search_runbooks` no longer accepts a
  caller-supplied `tenant_id`; it always uses `principal.tenant_id`, audits the
  search, and uses the cached `get_retriever()` plus `RAG_THRESHOLD`.
- **Investigation restart race:** start now locks the latest state row and
  returns `410` while a non-stale run is `in_progress` (10-minute stale
  recovery window for a crashed worker). Each dispatch gets a `run_id`, and a
  worker will not persist a result that has been superseded.
- **Approval semantics:** approval now requires a `waiting_for_approval` state,
  uses `FOR UPDATE` to serialize concurrent decisions, and resumes a short
  graph starting at `execute_approved_action`. It no longer re-runs analysis or
  re-plans after human approval.
- **Container runtime:** compose commands now invoke the already-synced
  `.venv/bin` executables instead of `uv run`. `uv run` defaults to the dev
  dependency group and would otherwise try to install pytest/ruff when the
  API/worker starts. `UV_NO_DEV=1` is also set in the image.

### Verification

```text
$ uv run pytest -q
93 passed

$ uv run ruff check app tests migrations scripts
All checks passed!

$ cd frontend && npm run lint && npm run build
oxlint clean; production build succeeded

$ docker compose -f docker/docker-compose.yml config -q
(no output)

$ otelcol validate --config=/etc/otel-collector-config.yaml
(no output)

# nginx deep-link smoke test
GET /incidents/2 -> 200
GET /approvals   -> 200
```

New tests cover the in-progress start guard, approval-state guard, short
approval graph, and tenant-scoped runbook search.

## 34. Isolation and reliability verification (2026-11-07)

Goal: prove the security and delivery claims with focused tests instead of
adding more features. This pass deliberately does **not** implement every
possible failure scenario or a full chaos matrix.

### Tenant isolation tests

`tests/test_tenant_isolation.py` uses two real bearer-token principals plus a
superadmin and exercises both the HTTP boundary and the execution paths:

- incidents: cross-tenant read, update, and delete return `404`; list results
  contain only the caller's tenant.
- investigations: cross-tenant read/approve returns `403`, start returns `404`
  through the tenant-scoped incident repository, and denied requests never
  dispatch Celery work. The superadmin bypass is tested explicitly.
- runbooks: the same runbook name resolves to different content per tenant;
  another tenant's runbook is `404`; deletion is tenant-scoped.
- automation: rule list/update/delete is tenant-scoped, and the
  `AutomationEngine` executes only rules belonging to the incident's tenant.
- webhooks: `X-Tenant-Slug` must resolve; per-tenant secrets must match;
  inactive tenants return `403`; unknown/empty slugs return `401`; the global
  secret without a slug targets the default tenant. The `/webhooks/test`
  server-side drill always uses the authenticated principal's tenant.

`tests/test_rag_tenant_isolation.py` tests retrieval directly:

- an ephemeral Chroma collection contains identical documents for tenants A
  and B; queries with `where={"tenant_id": ...}` return only that tenant's
  chunks.
- `search_runbooks`' vector fallback uses the principal's tenant and returns no
  B documents.
- both the Gemini and OpenAI-compatible analyzers forward `tenant_id` into the
  retriever.
- the pgvector statement includes a `runbook_chunks.tenant_id` predicate.

The previous placeholder investigation test (which accepted either `200` or
`403`) was removed.

### Four reliability scenarios

`tests/test_reliability.py` covers exactly the requested cases:

1. **Broker unavailable:** an outbox event stays `PENDING`, records the error,
   increments attempts, and is still publishable after its backoff. No incident
   work is lost.
2. **Duplicate delivery:** the same task delivered twice runs analysis and
   automation once, then returns early from `processing_plan()`.
3. **Worker retry:** the first analysis raises, persists `FAILED`, and requests
   a Celery retry; the next delivery reruns analysis and completes. The retry
   is bounded by the existing `max_retries=5`.
4. **Already completed:** a redelivery for `analysis_status=COMPLETED` and
   `automation_status=SUCCESS` does not call the analyzer or automation engine.

`analyze_incident` now uses dialect-aware advisory-lock helpers so these task
paths can be exercised on SQLite without weakening the PostgreSQL behavior.

### Why at-least-once instead of exactly-once

The incident row and outbox event commit in one PostgreSQL transaction. The
dispatcher claims the event, publishes it to Celery, and marks it published.
If the broker is down, the row remains pending; if the publish succeeds but the
mark fails, the event is published again. Celery is configured with
`acks_late=True`, so a worker crash can also cause redelivery.

Exactly-once execution across PostgreSQL, Redis, and external automation
actions would require a distributed transaction or an idempotency key honored
by every downstream system. Instead, AIRS chooses **at-least-once delivery +
idempotent processing**:

- the Postgres advisory lock prevents concurrent duplicate work;
- persisted analysis/automation status prevents repeated LLM calls and
  repeated side effects;
- a definitive automation failure is terminal on redelivery and requires
  explicit operator action rather than blindly re-sending external effects.

This is the honest guarantee: analysis is not duplicated in the tested
single-process/sequential paths, and concurrent deliveries are serialized in
production PostgreSQL. It is not a claim of exactly-once execution.

### Webhook strictness change

The previous implementation silently fell back to the default tenant when a
supplied slug was unknown or the tenant had no per-tenant hash. That is now
rejected. Omitting the slug still supports the original single-tenant global
secret flow.

### Commands run

```text
$ uv run pytest -q
106 passed, 2 warnings

$ uv run ruff check .
All checks passed!
```

