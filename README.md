# AI Incident Response System (AIRS)

A production-oriented incident-response platform that turns monitoring alerts
into deduplicated incidents, grounds AI analysis in tenant-specific runbooks,
executes policy-controlled automation, and runs a human-in-the-loop agentic
investigation workflow — all observable through Prometheus, OpenTelemetry, and
Grafana.

AIRS is deliberately **not** a black box that silently remediates production.
It is a **shadow-mode-first** system: the agent investigates, proposes a plan,
classifies risk, and pauses for human approval before any destructive action can
run.

---

## Table of contents

1. [Highlights](#1-highlights)
2. [Architecture](#2-architecture)
3. [Technology stack](#3-technology-stack)
4. [Repository layout](#4-repository-layout)
5. [Data model](#5-data-model)
6. [Core workflows](#6-core-workflows)
   - 6.1 [Alert ingestion and deduplication](#61-alert-ingestion-and-deduplication)
   - 6.2 [Transactional outbox](#62-transactional-outbox)
   - 6.3 [AI analysis pipeline](#63-ai-analysis-pipeline)
   - 6.4 [Retrieval-Augmented Generation](#64-retrieval-augmented-generation-rag)
   - 6.5 [Automation engine](#65-automation-engine)
   - 6.6 [Agentic investigation (LangGraph)](#66-agentic-investigation-langgraph)
   - 6.7 [Remote agent investigation and remediation](#67-remote-agent-investigation-and-remediation)
   - 6.8 [Audit trail](#68-audit-trail)
7. [Security and multi-tenancy](#7-security-and-multi-tenancy)
8. [Observability](#8-observability)
9. [API reference](#9-api-reference)
10. [Frontend](#10-frontend)
11. [Configuration](#11-configuration)
12. [Local development](#12-local-development)
13. [Docker Compose](#13-docker-compose)
14. [Database migrations](#14-database-migrations)
15. [Testing and quality](#15-testing-and-quality)
16. [Operations and troubleshooting](#16-operations-and-troubleshooting)
17. [Design decisions and trade-offs](#17-design-decisions-and-trade-offs)
18. [Performance characteristics](#18-performance-characteristics)
19. [Known limitations and roadmap](#19-known-limitations-and-roadmap)

---

## 1. Highlights

- **Alert ingestion** from Grafana, generic webhooks, and an in-app tester.
- **Fingerprint deduplication** with severity escalation, occurrence counting,
  and resolved-alert handling.
- **Transactional outbox** so a Redis/Celery outage never loses an analysis.
- **RAG-grounded AI analysis** using versioned, tenant-scoped runbooks stored in
  PostgreSQL and embedded in ChromaDB or pgvector.
- **Provider abstraction**: Google Gemini, any OpenAI-compatible endpoint
  (OpenAI, Ollama, vLLM, LM Studio), or a deterministic zero-key mock.
- **Deterministic fallback** when the configured LLM is unavailable (quota,
  network, invalid key) so the pipeline still completes.
- **Policy-controlled automation**: log, script, webhook, Slack, and custom
  actions, with validation, per-rule `continue_on_failure`, and execution logs.
- **LangGraph investigation agent**: read-only evidence tools, a persisted state
  machine, an explicit allowlist/blocklist for built-in actions, and human
  approval for built-in destructive actions.
- **Remote operations agent**: outbound-only polling, PostgreSQL-backed durable
  jobs, structured action catalog, exact per-job approvals, and idempotent
  diagnostics with non-replayed destructive remediation.
- **Multi-tenant RBAC**: `VIEWER < RESPONDER < ADMIN`, plus superadmin tenants.
- **Append-only audit trail** for approvals, rejections, and privileged actions,
  plus durable job-event history for every remote transition.
- **Observability**: Prometheus metrics, OpenTelemetry traces, correlation IDs,
  JSON logs, Grafana/Prometheus stack.
- **Hardened Compose stack**: health checks, restart policies, resource limits,
  graceful shutdown, and observability sidecars.

---

## 2. Architecture

### 2.1 Component diagram

```text
                         ┌──────────────────────────┐
                         │  Grafana / Prometheus /  │
                         │  generic monitoring      │
                         └────────────┬─────────────┘
                                      │ webhook
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ FastAPI API (:8000)                                                      │
│  • CORS + correlation-ID middleware                                       │
│  • optional auth (anonymous / API key / bearer token)                     │
│  • rate limiting on writes                                                │
│  • incident, runbook, automation, tenant, outbox, audit, investigation    │
│  • Prometheus /metrics, OpenAPI /docs                                     │
└───────────────┬───────────────────────────────────────────────┬───────────┘
                │ same transaction                              │ Celery task
                ▼                                               ▼
┌───────────────────────────────┐                  ┌──────────────────────────┐
│ PostgreSQL                    │                  │ Redis                    │
│  • tenants/users/api_tokens   │                  │  • Celery broker/backend │
│  • incidents                  │                  │  • rate-limit keys       │
│  • outbox_events              │                  │  • metric counters       │
│  • automation_rules/runs      │                  └────────────┬─────────────┘
│  • runbooks/runbook_chunks    │                               │
│  • workflow_states            │                               ▼
│  • audit_logs                 │                  ┌──────────────────────────┐
└───────────────┬───────────────┘                  │ Celery worker            │
                │                                  │  • analyze_incident      │
                │                                  │  • run_investigation     │
                ▼                                  │  • reindex_runbooks      │
┌───────────────────────────────┐                  │  • dispatch_outbox       │
│ ChromaDB or pgvector          │◄─────────────────┤                          │
│  • runbook embeddings         │   retrieval      └────────────┬─────────────┘
└───────────────────────────────┘                               │
                                                                ▼
                                                   ┌──────────────────────────┐
                                                   │ LLM provider             │
                                                   │  Gemini / OpenAI-compat  │
                                                   │  / deterministic mock    │
                                                   └──────────────────────────┘

Celery beat ── every 10s ──► dispatch_outbox ──► outbox_events ──► worker

Remote agent (outbound only) ──poll/ack/result──► API ──durable jobs──► PostgreSQL
                                      │
                                      └──► allowlisted local action on the target host

Observability: API/worker ──OTLP traces──► OpenTelemetry Collector ──► logs
               API /metrics ──────────────────────────────────► Prometheus ──► Grafana
```

### 2.2 Runtime processes

| Process | Purpose | Command |
|---|---|---|
| API | HTTP endpoints, auth, webhooks, metrics | `uv run uvicorn app.main:app --reload` |
| Worker | AI analysis, automation, investigations, RAG reindex | `uv run celery -A app.celery_app.celery_app worker --loglevel=info` |
| Beat | Periodic outbox dispatch | `uv run celery -A app.celery_app.celery_app beat --loglevel=info` |
| Frontend | React SPA | `cd frontend && npm run dev` |
| Remote agent | Outbound polling, allowlisted diagnostics/remediation | `cd remote-agent && python -m app.main` |
| PostgreSQL | System of record | external or Compose |
| Redis | Broker, result backend, counters, rate limits | external or Compose |
| ChromaDB | Embedded persistent vector store | in-process, `app/rag/chroma_db/` |
| OTel Collector | Trace/metric collection | Compose |
| Prometheus | Metrics scraping | Compose |
| Grafana | Dashboards | Compose |

### 2.3 Request lifecycle

1. A monitoring system posts an alert to `/api/v1/webhooks/grafana` (or
   `/custom`) with `X-Webhook-Secret` and optionally `X-Tenant-Slug`.
2. The webhook is validated, parsed by a source-specific adapter, and normalized
   into one or more `IncidentCreate` objects.
3. `WebhookService` looks up an active incident by fingerprint.
   - **Resolved** alert → mark the active incident `RESOLVED`.
   - **Repeated firing** alert → update `last_seen_at`, increment
     `occurrence_count`, escalate severity if needed.
   - **New** alert → insert the incident and an `outbox_events` row in the same
     database transaction.
4. The API fast-path pokes Celery (`dispatch_outbox.delay()`); if the broker is
   down, the outbox poller recovers the event later.
5. The worker claims the event with `SELECT … FOR UPDATE SKIP LOCKED`, publishes
   `analyze_incident`, and marks the event `PUBLISHED`.
6. Analysis retrieves runbook evidence, calls the configured LLM (or falls back),
   persists summary/severity/recommendation/sources, and marks analysis
   `COMPLETED`.
7. Matching automation rules run in order; each execution is recorded in
   `automation_runs`, and `automation_status` ends `SUCCESS` or `FAILED`.
8. If requested, the LangGraph investigation runs asynchronously, persists a
   `workflow_states` snapshot, and either pauses for approval or completes.
   Incidents with a target agent instead use the durable remote-job planner.
9. Remote agents poll outbound for jobs, execute one allowlisted action, and
   post a bounded/redacted result; result processing resumes the investigation.
10. Metrics are mirrored to Redis counters and exposed as Prometheus gauges on
    scrape; traces and JSON logs carry correlation IDs.

### 2.4 Investigation state machine

```text
                    ┌───────────────┐
                    │ load_incident │
                    └───────┬───────┘
                            ▼
                  ┌──────────────────┐
                  │ retrieve_runbooks│
                  └────────┬─────────┘
                           ▼
                   ┌───────────────┐
             ┌─────┤ analyze_incident│◄──────────────┐
             │     └───────┬───────┘                │
             │             │ evidence sufficient?   │
             │      ┌──────┴───────┐                │
             │      ▼              ▼                │
             │  insufficient    sufficient          │
             │      │              │                │
             │      ▼              │                │
             │ ┌───────────┐       │                │
             │ │investigate│───────┘ (at most once) │
             │ └───────────┘                        │
             │                                      │
             ▼                                      │
   ┌──────────────────────┐                          │
   │ create_remediation_plan│                        │
   └──────────┬───────────┘                          │
              ▼                                      │
      ┌───────────────┐                              │
      │ risk_assessment│                             │
      └──────┬────────┘                              │
             │ approval required & not approved?     │
      ┌──────┴───────────────┐                       │
      ▼                      ▼                       │
┌──────────────────┐  ┌──────────────────────┐        │
│ wait_for_approval│  │ execute_approved_action│──────┘
│ (API resumes)    │  │ executes only when    │
└──────────────────┘  │ requires_approval and │
                      │ approved is True;     │
                      │ otherwise plan-only   │
                      └──────────┬───────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ verify_service_health│
                      └──────────┬───────────┘
                                 ▼
                        ┌─────────────────┐
                        │ update_incident │
                        └─────────────────┘
```

Note: `MEDIUM` and lower severities are shadow-only. They do not require
approval and therefore never execute automation from the agent path; the
`execute_approved_action` guard rejects execution without both
`requires_approval=True` and `approved=True`.

---

## 3. Technology stack

| Layer | Technology | Version / notes |
|---|---|---|
| Language | Python | `>=3.14` |
| API | FastAPI | `>=0.138.2` |
| ORM | SQLAlchemy | `>=2.0.51`, typed `Mapped` models |
| Validation | Pydantic / pydantic-settings | v2 |
| Migrations | Alembic | `>=1.18.5` |
| Database | PostgreSQL | 16 in Compose; pgvector image |
| Vector search | ChromaDB `>=1.5.9` or pgvector `>=0.5.0` | pluggable backend |
| Embeddings | Sentence Transformers | `all-MiniLM-L6-v2`, 384 dimensions |
| AI | Google Gemini / OpenAI-compatible / mock | `google-genai>=2.10.0`, `httpx` |
| Agent | LangGraph `>=0.2.0` + langchain-core | single-agent state graph |
| Queue | Celery `>=5.6.3` | Redis broker + result backend |
| Cache/counters | Redis `redis:7` in Compose; `redis>=8.0.1` client | rate limits, metrics mirrors |
| Metrics | prometheus-client `>=0.25.0` | `/metrics` |
| Tracing | OpenTelemetry `>=1.30.0` | FastAPI + OTLP exporter |
| Frontend | React 19, TypeScript 6, Vite 8 | SPA |
| Data fetching | TanStack Query 5, Axios | polling + caching |
| Styling | Tailwind CSS 4 | utility-first |
| Frontend lint | oxlint | `npm run lint` |
| Backend lint | Ruff | `uv run ruff check` |
| Tests | pytest `>=9.1.1` | 122 backend tests + 10 agent tests |
| Containers | Docker + Compose | hardened services |

---

## 4. Repository layout

```text
.
├── app/
│   ├── agent/                    # LangGraph investigation agent
│   │   ├── state.py              # InvestigationState (Pydantic)
│   │   ├── tools.py              # read-only, tenant-scoped tools
│   │   └── workflow.py           # nodes, edges, allowlist/blocklist
│   ├── ai/                       # LLM analyzers
│   │   ├── analyzer.py           # Gemini + RAG + abstention
│   │   ├── base.py               # analyzer interface
│   │   ├── client.py             # Gemini client factory
│   │   ├── fallback.py           # provider-failure degradation
│   │   ├── mock.py               # deterministic heuristic analyzer
│   │   ├── openai_provider.py    # OpenAI-compatible analyzer
│   │   ├── prompts.py            # analysis prompt
│   │   └── schemas.py            # IncidentAnalysis response schema
│   ├── api/
│   │   ├── health.py             # GET /health
│   │   └── routes/               # auth, incidents, automation, runbooks,
│   │                             # tenants, outbox, audit, agents, remote jobs
│   ├── remote/                   # action catalog, planner, agent auth, redaction
│   ├── automation/
│   │   ├── actions/              # log, script, webhook, slack
│   │   ├── base.py               # AutomationAction ABC
│   │   ├── engine.py             # rule execution engine
│   │   └── registry.py           # action registry
│   ├── core/
│   │   ├── auth.py               # principals, password/token hashing, RBAC
│   │   ├── config.py             # pydantic-settings configuration
│   │   ├── dependencies.py       # DI factories
│   │   ├── exception_handlers.py
│   │   ├── logging.py            # plain/JSON logs with trace IDs
│   │   ├── middleware.py         # correlation IDs
│   │   ├── providers.py          # cached analyzer/retriever factories
│   │   ├── redis.py              # Redis client
│   │   ├── security.py           # API key + rate limiting
│   │   └── tracing.py            # OpenTelemetry setup/helpers
│   ├── database/                 # Base + SessionLocal
│   ├── exceptions/               # domain exceptions
│   ├── models/                   # SQLAlchemy models + enums
│   ├── monitoring/               # Redis counters + Prometheus gauges
│   ├── outbox/                   # outbox dispatcher service
│   ├── pipelines/                # incident creation pipeline
│   ├── rag/                      # chunking, embeddings, Chroma/pgvector
│   │   ├── chroma_db/            # embedded persistent index
│   │   └── knowledge/            # seed runbooks (markdown)
│   ├── repositories/             # data-access layer
│   ├── schemas/                  # API request/response models
│   ├── services/                 # business logic
│   ├── tasks/                    # Celery tasks
│   ├── webhooks/                 # adapters, validation, ingestion service
│   ├── celery_app.py             # Celery configuration + model imports
│   └── main.py                   # FastAPI application factory
├── docker/
│   ├── docker-compose.yml        # full stack + observability
│   ├── Dockerfile.api            # API/worker/beat image
│   ├── otel-collector-config.yaml
│   └── prometheus.yml
├── frontend/
│   ├── src/api/                  # typed Axios clients + TanStack hooks
│   ├── src/pages/                # dashboard, incidents, investigation, ...
│   ├── src/components/
│   └── Dockerfile                # Vite build + nginx runtime
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 64aa69a79934_initial_schema.py
│       ├── 4ff6a5f6da7a_add_runbook_version_column.py
│       ├── 6cd48e3599e7_add_workflow_state_table.py
│       └── 8d1c0a7b2f34_add_remote_agents_and_jobs.py
├── remote-agent/                 # standalone outbound polling agent
│   ├── app/                      # config, client, actions, executor, runner
│   ├── systemd/airs-agent.service
│   ├── tests/
│   ├── Dockerfile
│   └── README.md
├── scripts/
│   ├── import_runbooks.py
│   ├── seed_admin.py
│   ├── seed_automation_rules.py
│   ├── playground.py
│   └── rag_eval.py
├── tests/                        # 122 pytest tests
├── IMPLEMENTATION.md             # phase-by-phase engineering log
├── pyproject.toml
├── alembic.ini
└── README.md
```

---

## 5. Data model

### 5.1 Tables

| Table | Purpose | Key columns |
|---|---|---|
| `tenants` | Tenant isolation boundary | `slug`, `name`, `is_active`, `webhook_secret_hash` |
| `users` | Local accounts | `email`, `password_hash`, `role`, `is_active`, `is_superadmin`, `tenant_id` |
| `api_tokens` | Bearer tokens | `user_id`, `token_hash` (SHA-256), `name`, `expires_at`, `last_used_at` |
| `incidents` | Incident lifecycle | `tenant_id`, `title`, `message`, `status`, `analysis_status`, `automation_status`, `severity`, `ai_summary`, `recommendation`, `source`, `fingerprint`, `rag_sources`, `occurrence_count`, `first_seen_at`, `last_seen_at`, `target_agent_id` |
| `outbox_events` | Durable task hand-off | `event_type`, `payload`, `idempotency_key`, `status`, `attempts`, `available_at`, `locked_at`, `published_at`, `last_error` |
| `automation_rules` | Declarative automation | `tenant_id`, `severity`, `action_name`, `enabled`, `execution_order`, `config` |
| `automation_runs` | Execution history | `tenant_id`, `incident_id`, `action_name`, `status`, `message`, `executed_at` |
| `runbooks` | Editable operational docs | `tenant_id`, `name`, `content`, `version`, `metadata` |
| `runbook_chunks` | pgvector index | `id`, `tenant_id`, `source`, `section`, `document`, `embedding(384)`, `chunk_hash` |
| `workflow_states` | Persisted agent state | `incident_id`, `tenant_id`, `state_json`, `status`, `current_step`, timestamps |
| `remote_agents` | Registered outbound targets | `tenant_id`, `agent_key`, `display_name`, `hostname`, `status`, `capabilities`, `last_seen_at` |
| `remote_agent_credentials` | Hashed agent credentials | `agent_id`, `token_hash`, `expires_at`, `revoked_at` |
| `remote_agent_events` | Agent audit trail | `tenant_id`, `agent_id`, `event_type`, `actor_type`, `details` |
| `remote_jobs` | Durable remote action state | `tenant_id`, `incident_id`, `agent_id`, `action_id`, `action_parameters`, `execution_type`, `status`, `lease_id`, `expires_at` |
| `remote_job_results` | Redacted agent output | `job_id` (unique), `status`, `stdout_redacted`, `stderr_redacted`, `structured_output`, timings |
| `remote_job_approvals` | Exact-parameter approvals | `job_id` (unique), `action_hash`, `parameters_hash`, `approved_by`, `expires_at`, `reason` |
| `remote_job_events` | Job audit trail | `tenant_id`, `job_id`, `event_type`, `actor_type`, `details` |
| `audit_logs` | Append-only audit trail | `actor_*`, `action`, `resource_type`, `resource_id`, `tenant_id`, `details`, `created_at` |
| `alembic_version` | Migration head | `version_num` |

### 5.2 Enumerations

| Enum | Values |
|---|---|
| `IncidentStatus` | `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `CLOSED` |
| `AnalysisStatus` | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED` |
| `AutomationStatus` | `PENDING`, `RUNNING`, `SUCCESS`, `FAILED` |
| `OutboxStatus` | `PENDING`, `PROCESSING`, `PUBLISHED`, `FAILED` |
| `UserRole` | `VIEWER`, `RESPONDER`, `ADMIN` |
| `Severity` | `UNKNOWN`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `AutomationAction` | `log`, `script`, `webhook` (registry also has `slack`) |
| `IncidentSource` | `MANUAL`, `CUSTOM`, `PROMETHEUS`, `GRAFANA`, `GITHUB` |
| `RemoteAgentStatus` | `ACTIVE`, `DISABLED`, `REVOKED` |
| `RemoteExecutionType` | `DIAGNOSTIC`, `REMEDIATION`, `VERIFICATION` |
| `RemoteJobStatus` | `PENDING_APPROVAL`, `APPROVED`, `DISPATCHED`, `ACKNOWLEDGED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELLED`, `EXPIRED`, `UNKNOWN` |
| `RemoteApprovalStatus` | `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED` |

### 5.3 Relationships and invariants

```text
tenants 1──* users 1──* api_tokens
tenants 1──* incidents 1──* automation_runs
tenants 1──* automation_rules
tenants 1──* runbooks 1──* runbook_chunks
incidents 1──* workflow_states
tenants 1──* remote_agents 1──* remote_agent_credentials
remote_agents 1──* remote_agent_events
incidents 1──* remote_jobs 1──1 remote_job_results
remote_jobs 1──1 remote_job_approvals
remote_jobs 1──* remote_job_events
```

- Tenant-owned tables (users, incidents, automation rules/runs, runbooks,
  runbook chunks, workflow states, remote agents, agent credentials/events,
  remote jobs/results/approvals/events, audit logs) carry `tenant_id`;
  tenant-facing queries are scoped by the caller's tenant. Superadmin-scoped
  endpoints (tenants, audit log, outbox) can operate globally; user management
  is tenant-scoped for tenant admins and global for superadmins.
  `outbox_events` is deliberately global infrastructure state.
- An active incident fingerprint is unique per tenant through a partial unique
  index covering rows whose status is `OPEN` or `ACKNOWLEDGED`. Concurrent
  duplicate alerts race safely: one INSERT wins and the loser refreshes the
  winner.
- Analysis status and automation status are independent of the incident
  lifecycle (`OPEN`/`RESOLVED`/…), so a resolved incident can still retain its
  analysis result.
- Agent credentials are stored only as SHA-256 hashes and are usable only
  while the agent is `ACTIVE`, the credential is unexpired, and it has not been
  revoked. Revocation is permanent; `disable` is reversible with `enable`.
- A remote job is bound to one tenant, incident, agent, action, normalized
  parameter set, execution type, and investigation run. Its idempotency key is
  unique, and each job has at most one result and one approval record.
- Approval hashes cover tenant, incident, agent, action, parameters, and risk;
  the approval row adds the approver, expiry, and reason. Any parameter drift
  invalidates the decision.
- `workflow_states` is append-only per run; the API reads the latest row by
  descending `id` (not `updated_at`, which can tie within the same second).

---

## 6. Core workflows

### 6.1 Alert ingestion and deduplication

Endpoints:

- `POST /api/v1/webhooks/grafana` — Grafana unified alerting payload.
- `POST /api/v1/webhooks/custom` — generic `{title, message, severity,
  fingerprint}` payload.
- `POST /api/v1/webhooks/test` — authenticated in-app drill endpoint so the
  browser never needs the webhook secret.

Authentication:

- `X-Webhook-Secret` is required. With no tenant slug it is compared with the
  global `WEBHOOK_SECRET`.
- If `X-Tenant-Slug` is supplied and that tenant has a
  `webhook_secret_hash`, the SHA-256 of the supplied secret is compared with the
  stored hash and the incident is created in that tenant. This enables
  per-tenant secrets.
- With no `X-Tenant-Slug`, the global secret targets the default tenant.
  When a slug is supplied it is authoritative: empty or unknown slugs are
  rejected with `401`. Tenants created through the API have a per-tenant hash
  and must present that tenant's secret; a non-default tenant without a hash
  is rejected with `401`. Only the legacy default tenant may be selected
  explicitly with the global secret. Inactive tenants are rejected with `403`.

Grafana normalization:

- Each alert becomes one incident.
- `labels.severity` is mapped through `CRITICAL/HIGH/MEDIUM/LOW` and aliases
  (`critical`, `error`, `warning`, `warn`, `info`).
- Missing severity on a firing alert defaults to `CRITICAL`.
- Title is `alertname` plus `instance` when present.
- `status="resolved"` marks the matching active incident `RESOLVED` instead of
  creating a new one.

Deduplication semantics:

- Fingerprint is matched only against active incidents.
- A repeat firing event increments `occurrence_count`, refreshes
  `last_seen_at`, and **only escalates** severity (never downgrades).
- A resolved event with no active incident is ignored.
- Concurrent duplicates are resolved by the partial unique index; the losing
  request reloads and refreshes the existing incident.

### 6.2 Transactional outbox

The incident row and the `outbox_events` row are committed atomically. The
broker is a delivery mechanism, not the source of truth.

Event types currently mapped:

| Event type | Celery task |
|---|---|
| `analyze_incident` | `app.tasks.incident.analyze_incident` |

Dispatcher algorithm (`OutboxService.dispatch_pending`):

1. Recover `PROCESSING` claims older than **300 s** back to `PENDING`.
2. Claim up to `limit` due events with
   `SELECT … FOR UPDATE SKIP LOCKED`; set `PROCESSING`, increment `attempts`,
   set `locked_at`, and commit.
3. Publish the mapped Celery task.
4. On success → `PUBLISHED`, `published_at=now()`.
5. On failure → `PENDING` with exponential backoff and ±25 % jitter:
   `min(3600, 30 × 2^(attempts−1))`, or `FAILED` after **10 attempts**
   (`last_error` stores the message, truncated to 4 000 chars).

Operational controls:

- `GET /api/v1/outbox/?status=FAILED` — inspect the dead-letter set
  (superadmin).
- `POST /api/v1/outbox/{event_id}/replay` — move a `FAILED` event back to
  `PENDING` (superadmin).
- `GET /metrics` — queue-wait gauges are defined but broker wait time is not
  yet recorded (see §8.1).

At-least-once delivery is intentional; the worker absorbs duplicates with a
PostgreSQL advisory lock per incident and status checks (`processing_plan`).

### 6.3 AI analysis pipeline

Flow:

```text
incident.message
      │
      ▼
RAG retrieval (tenant-scoped)
      │
      ├── no chunk passes RAG_THRESHOLD ──► abstained analysis
      │                                      (no LLM call)
      ▼
prompt (context + incident)
      │
      ▼
structured JSON response (schema-validated)
      │
      ├── success ──► summary, severity, recommendation, sources
      └── provider failure ──► deterministic fallback
```

Providers:

| `AI_PROVIDER` | Required configuration | Notes |
|---|---|---|
| `gemini` | `GEMINI_API_KEY`, `AI_MODEL` | Google GenAI SDK |
| `openai` | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | Any OpenAI-compatible API |
| `ollama` / `vllm` / `lmstudio` | `OPENAI_BASE_URL`, `OPENAI_MODEL` | Local inference |
| `mock` | none | Deterministic heuristic analyzer |

Fallback behavior:

1. If the selected provider requires a key and none is configured (Gemini, or
   `AI_PROVIDER=openai`), `get_incident_analyzer()` returns the mock analyzer.
   Local `ollama`/`vllm`/`lmstudio` providers can run without a key.
2. At runtime, `FallbackAnalyzer` wraps the real provider. Any provider error
   (quota exhausted, network error, invalid model) logs a warning and returns a
   heuristic `IncidentAnalysis` with `model="fallback"`.
3. `SoftTimeLimitExceeded` is deliberately re-raised so a task timeout is never
   converted into a false success.

Abstention:

- If retrieval returns no sources above `RAG_THRESHOLD`, the analyzer returns
  `abstained=True`, `severity=UNKNOWN`, `confidence=0.0`, and no LLM call is
  made. This reduces cost and prevents hallucinated remediations. If the
  incident already has a known severity from its alert source, the abstained
  analysis preserves it rather than overwriting it with `UNKNOWN`.
- `sources` (runbook chunk IDs) are persisted on the incident for
  explainability.

Analysis status transitions:

```text
PENDING ──► RUNNING ──► COMPLETED
                    └──► FAILED (exception re-raised for retry visibility)
```

### 6.4 Retrieval-Augmented Generation (RAG)

#### Ingestion

- Seed runbooks live in `app/rag/knowledge/*.md`:
  `cpu`, `disk`, `filesystem`, `memory`, `network`, `postgres`, `redis`.
- `scripts/import_runbooks.py` imports them into the `runbooks` table once
  (never overwrites DB edits unless `--overwrite`).
- Runbooks are editable through the UI/API. The markdown files are seed data;
  PostgreSQL is the runtime source of truth.
- Saving or deleting a runbook does **not** rebuild the vector index by itself.
  Use the **Reindex** button or `POST /api/v1/runbooks/reindex` (asynchronous
  Celery task). The UI explicitly reminds operators to reindex after edits.
- If the broker is unavailable, the reindex endpoint falls back to synchronous
  ingest and returns `status: completed` with `task_id: null`. The route is
  declared with HTTP 202 statically, so the fallback response also carries
  `202`, not `200`.

#### Chunking (`app/rag/chunking.py`)

- Split on `##` headings into section-level chunks.
- Maximum chunk size: **1 500 chars**.
- Long sections are split on paragraph boundaries with **200 chars of
  overlap** by default (`CHUNK_OVERLAP_CHARS`, configurable) so evidence is not
  lost at boundaries.
- Chunk IDs are deterministic and versioned:
  `{source}#{section}-v{version}` or `…-v{version}-{n}`. Vector IDs add a
  tenant namespace: `{tenant_id}:{chunk_id}` so equal runbook names in
  different tenants cannot collide.
- Metadata: `{source, section, version, tenant_id}` (tenant id is added by the
  ingest layer).

#### Embeddings

- Sentence Transformers `all-MiniLM-L6-v2`, 384 dimensions.
- Batch embedding at ingest time; cached service instance per process.

#### Backends

| `RAG_BACKEND` | Storage | Notes |
|---|---|---|
| `chroma` (default) | Embedded persistent ChromaDB at `app/rag/chroma_db/` | Zero-config quickstart |
| `pgvector` | `runbook_chunks` table with `vector(384)` | Single-Postgres prod path; requires the `vector` extension |
| `both` | Both | Ingestion/reindex writes both; retrieval uses Chroma |

Both retrievers expose the same `retrieve(query, k, threshold, where)`
interface. The factory selects pgvector only when `RAG_BACKEND=pgvector`;
every other value uses Chroma.

#### Retrieval

- Default `k=3`, `RAG_THRESHOLD=1.2` (cosine distance: 0 identical, 2 opposite).
- Chunks above the threshold are dropped.
- `where={"tenant_id": …}` enforces tenant isolation at the vector layer.
- Returned IDs are stored in `incidents.rag_sources`.

#### Evaluation

`scripts/rag_eval.py` runs a fixed question set against the knowledge base and
reports retrieval quality. The latest local run produced:

- **MRR:** 0.843
- **Citation accuracy:** 1.0

```bash
uv run python -m scripts.rag_eval --backend chroma --k 3 --k 5
```

### 6.5 Automation engine

Rules are database-driven (`automation_rules`) and evaluated after analysis
completes. Each rule selects a severity, an action, a config payload, an
execution order, and an enabled flag.

Supported actions:

| Action | Config | Semantics |
|---|---|---|
| `log` | — | Writes an `automation_runs` entry |
| `script` | `script_path`, `timeout` | Executes a local script with no shell; path must not contain `; \| & $ \` \n \r`; timeout 1–600 s |
| `webhook` | `url`, `headers`, `timeout` | POSTs the incident payload; timeout 1–120 s |
| `slack` | `url`, `channel` | Slack incoming-webhook compatible |
| custom | arbitrary | Register a subclass in `app/automation/registry.py` |

Engine semantics:

- Rules are ordered by `execution_order`.
- Unknown actions are skipped with a warning.
- Action constructors that reject unexpected config keys with `TypeError` are
  skipped; other constructor errors surface at runtime, so rule creation
  validates the common config shapes first.
- Default is **fail-fast**: an action exception rolls back the poisoned
  transaction, persists `automation_status=FAILED`, and re-raises.
- Per-rule `config.continue_on_failure=true` continues with remaining rules.
- No matching rules → `automation_status=SUCCESS` (nothing to do is success).
- Every action records status, message, and timestamp in `automation_runs`,
  exposed at `GET /api/v1/incidents/{id}/runs`.

Webhook payload:

```json
{
  "id": 1,
  "title": "High CPU",
  "message": "CPU 95% for 5m",
  "summary": "Sustained CPU saturation",
  "severity": "HIGH",
  "status": "OPEN",
  "recommendation": "Scale out or restart the worker pool"
}
```

Agent-specific policy (separate from the general engine):

- **Allowlist:** `log` = safe, `webhook` = destructive (requires approval).
- **Blocklist:** `script` and `slack` are never executed by the investigation
  agent; they require manual execution outside the agent.
- These lists cover built-in action names. Custom actions are trusted code and
  are not filtered by this policy (see §7.6).

### 6.6 Agentic investigation (LangGraph)

A single-agent stateful workflow, not a multi-agent swarm. The graph is
compiled once per process (`get_compiled_workflow`) and can also be invoked by
the Celery task `run_investigation`.

#### API flow

| Step | Endpoint | Behavior |
|---|---|---|
| Start | `POST /api/v1/investigations/{incident_id}/start` | Resets approval, execution, evidence, and plan fields; persists `in_progress`; dispatches Celery; returns `202`. Returns `409` while a non-stale run is already `in_progress`. |
| Poll | `GET /api/v1/investigations/{incident_id}` | Latest persisted state |
| Queue | `GET /api/v1/investigations?status=waiting_for_approval` | Latest state per incident |
| Approve/reject | `POST /api/v1/investigations/{incident_id}/approve` | `RESPONDER+`; only a `waiting_for_approval` state can be decided; records/audits the decision, then resumes execution or stops |

The HTTP handlers never run the graph synchronously. This is deliberate: an
investigation can include LLM calls and must not block a browser request.

#### State (`InvestigationState`)

Input:

- `incident_id`, `tenant_id`, `run_id`, `actor_user_id`, `actor_email`,
  timestamps. `run_id` identifies one dispatch attempt; a worker discards a
  result whose `run_id` no longer matches the latest state.

Loaded incident:

- `incident_title`, `incident_message`, `incident_severity`, `incident_source`,
  `incident_fingerprint`, `incident_status`, `incident_analysis_status`,
  `incident_automation_status`.

Evidence:

- `retrieved_context`, `retrieved_sources`, `retrieved_distances`,
  `evidence_sufficient`, `investigation_notes`, `metrics_checked`,
  `logs_checked`, `deployment_history_checked`.

Plan and approval:

- `remediation_plan`, `risk_level`
  (`safe|non_destructive|destructive|unknown`), `requires_approval`,
  `approved` (`None` = not requested), `approved_by`, `approved_at`,
  `approval_reason`.

Execution and verification:

- `executed`, `executed_by`, `executed_at`, `execution_result`,
  `execution_error`, `verified`, `verification_result`, `service_healthy`.

Outcome:

- `workflow_status`
  (`pending|in_progress|waiting_for_agent|waiting_for_approval|completed|failed`),
  `error`, `current_step`, `steps_completed`.
- Remote fields: `mode`, `target_agent_id`, `investigation_round`,
  `pending_job_ids`, `evidence`, `planner_reasoning`, `remote_action`,
  `remote_action_hash`, `baseline_metrics`.

#### Nodes

| Node | Responsibility |
|---|---|
| `load_incident` | Tenant-scoped read of the incident; clears prior error |
| `retrieve_runbooks` | Vector search; query clipped to the tool limit (500 chars) |
| `analyze_incident` | Uses the configured analyzer (fallback-aware) |
| `investigate` | At most one evidence-gathering pass (metrics/logs/deployments) |
| `create_remediation_plan` | Builds a human-readable plan and risk classification |
| `risk_assessment` | HIGH/CRITICAL → destructive + approval required |
| `wait_for_approval` | Pauses; the API resumes later |
| `execute_approved_action` | Runs built-in allow-listed automation after explicit approval |
| `verify_service_health` | Calls the health check and records the result |
| `update_incident` | Marks the workflow complete |

Loop safety: after `investigate` runs once, the conditional edge proceeds to
planning even if evidence is still insufficient. This prevents an infinite
`analyze → investigate → analyze` loop.

#### Approval semantics

- `requires_approval` is true for `HIGH`/`CRITICAL`, false for `MEDIUM`/lower.
- `wait_for_approval` persists `waiting_for_approval`; the approval endpoint
  records `approved`, `approved_by`, `approved_at`, and `approval_reason`.
- Approving dispatches `run_investigation` with `resume=True`. It executes the
  short approval graph (`execute_approved_action → verify_service_health →
  update_incident`) and deliberately does **not** re-run analysis or re-plan;
  the plan the human approved is the plan that is acted on. For built-in
  actions, only `log` and `webhook` can run; custom actions are trusted code
  and are not filtered by this policy.
- `execute_approved_action` is defensive: it refuses to execute unless both
  `requires_approval` and `approved is True`. Lower-severity runs are therefore
  plan-only (shadow mode) even though they pass through the same node.
- Rejecting persists a completed/stopped state and does not execute anything.
- Restarting an investigation clears prior approval, execution, evidence, and
  plan fields, so a previous consent or stale evidence can never influence a
  new run.
- The Celery task takes a PostgreSQL advisory lock per incident and skips
  duplicate deliveries when the latest run is already completed or still
  waiting for a human decision.
- Approval and rejection are written to `audit_logs` with actor identity.

#### Read-only tools (`app/agent/tools.py`)

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `get_incident_details` | `incident_id` | Incident fields | Tenant-scoped; audited |
| `get_service_metrics` | `service`, `window_minutes` | Error rate, p95 latency, request rate | Mock adapter; service name regex-validated |
| `get_recent_logs` | `service`, `window_minutes`, `lines` | Log lines | Mock adapter |
| `search_runbooks` | `query`, `k` | Documents + sources + distances | Exact name fast path, vector fallback; tenant always taken from the principal |
| `get_deployment_history` | `service`, `limit` | Deployment records | Mock adapter |

Guardrails:

- Pydantic input schemas with bounds (`k` 1–10, query ≤ 500 chars, etc.).
- Tenant scoping on every tool.
- Audit writes are best-effort and never break a tool call.
- Retrieved content is treated as **data**, never as instructions, to reduce
  prompt-injection risk.
- Tool outputs are schema-validated before entering the graph.

### 6.7 Remote agent investigation and remediation

Remote incidents use the same persisted `InvestigationState`, but replace the
local tool nodes with a durable job layer. An incident is remote when it has a
`target_agent_id`; otherwise the LangGraph path is unchanged.

#### Target selection

- Admin-created agents have a tenant-scoped `agent_key`, `hostname`, and
  `display_name`.
- Grafana alerts can set `labels.agent_id` or `labels.agent`; otherwise the
  adapter falls back to `labels.instance` (including `host:port` by stripping
  the port). Generic webhooks use `target_agent_ref`.
- Resolution only matches `ACTIVE` agents in the alert's tenant. Unknown or
  inactive targets leave the incident local and visible for manual triage.

#### Job lifecycle

```text
PENDING_APPROVAL ──approve──► APPROVED ──poll──► DISPATCHED ──ack──► ACKNOWLEDGED
       │                         │                    │
       └──reject──► CANCELLED    └──expiry──► EXPIRED  ├──result──► SUCCEEDED
                                                       ├──result──► FAILED / TIMED_OUT
                                                       └──lease lost──► APPROVED (diagnostic)
                                                                       UNKNOWN (destructive)
```

- `remote_jobs`, `remote_job_results`, `remote_job_approvals`, and
  `remote_job_events` live in PostgreSQL and are the source of truth. Celery
  messages are only wake-ups; a broker outage cannot erase a pending job.
- Polling leases one job atomically. The agent acknowledges before executing.
- The agent-facing poll/ack response is a minimal job contract; it does not
  expose tenant identity, idempotency keys, approval records, approver, or
  operator identity.
- Delivery is **at-least-once**. The server stores one result per job (unique
  `job_id`) and returns that same result for duplicate posts. The agent also
  keeps a local SQLite execution record so a result POST failure can be retried.
- Diagnostic leases can be retried after expiry. A destructive job that was
  acknowledged and then lost is marked `UNKNOWN`, never replayed automatically.
- Every transition appends a `remote_job_events` row.
- The 30-second `recover_remote_jobs` task also resumes any terminal job whose
  result was never applied (lost broker wake-up, expired approval, lost lease),
  so an investigation cannot remain `waiting_for_agent` forever. A destructive
  job lost after acknowledgement ends the run as failed/`UNKNOWN` for manual
  reconciliation.
- Starting a new investigation cancels jobs that have not been leased and
  refuses to restart while a destructive job is approved or in flight, so an
  old approval cannot be reused by a new run. The restart, approval, and
  result-processing paths use a consistent PostgreSQL row-lock order (latest
  `workflow_states` row, then the job row).

#### Action registry and safety

The server catalog in `app/remote/actions.py` is authoritative. An LLM may only
choose an action ID and validated parameters; it never supplies shell text.
The v1 catalog contains:

| Action | Type | Risk | Approval |
|---|---|---|---|
| `inspect_memory`, `inspect_cpu_usage`, `inspect_disk_usage` | diagnostic | safe | no |
| `list_memory_processes`, `list_cpu_processes`, `inspect_process` | diagnostic | safe | no |
| `inspect_service_status`, `inspect_service_logs` | diagnostic | safe | no |
| `restart_service` | remediation | destructive | per-job |
| `terminate_process` | remediation | destructive | per-job |

The agent independently enforces:

- fixed argv commands, no shell;
- service names must be in `AIRS_ALLOWED_SERVICES` (`nginx` and
  `nginx.service` are both accepted);
- disk paths must be under `AIRS_ALLOWED_DISK_ROOTS`;
- remediation is disabled unless `AIRS_ENABLE_REMEDIATION=true`;
- `terminate_process` revalidates PID start time, owner, and command and refuses
  PID 1, the agent itself, root-owned processes, and critical process names;
- output is redacted and size-bounded locally, then sanitized again on the
  server (stdout, stderr, error text, and nested structured output).

#### Approval binding

A remediation job creates a `RemoteJobApproval` bound by SHA-256 to tenant,
incident, agent, action ID, normalized parameters, and risk level. Approval:

- requires `RESPONDER+` in the job's tenant;
- requires the job to still be `PENDING_APPROVAL`;
- checks the stored hash against the current job, and optionally against an
  `action_hash` sent by the UI;
- enforces the approval expiry;
- verifies the latest investigation run still matches the job's `run_id`;
- records approver, email, timestamp, and reason.

The incident-level approval endpoint intentionally rejects remote
investigations; use `POST /api/v1/remote-jobs/{job_id}/approve` or
`/reject`. After approval the agent polls the job, executes it, returns a
result, and the investigation queues a distinct `VERIFICATION` job that reuses
diagnostic probes. Verification passes only when the returned evidence meets
the configured memory threshold/drop (and service-active check when a target
service is known).

#### Remote agent

`remote-agent/` is a standalone Python daemon with `httpx` as its only runtime
dependency. It heartbeats capabilities, polls, acknowledges, executes, stores
the result locally, and posts it with retry. Run it as a constrained host
service or on a disposable lab VM; see `remote-agent/README.md` and
`remote-agent/systemd/airs-agent.service`. It is not a sandbox: use the smallest
host privilege set that can perform the approved actions, keep the shown-once
token secret, and use TLS outside a local lab.

### 6.8 Audit trail

`audit_logs` is append-only at the application layer (there are no update or
delete endpoints). Each row records:

- actor (`actor_user_id`, `actor_email`, `actor_is_superadmin`),
- action (`investigation.approve`, `investigation.reject`, tool invocations,
  privileged writes),
- resource (`resource_type`, `resource_id`),
- tenant,
- JSON `details`,
- timestamp.

API:

- `GET /api/v1/audit-log/?tenant_id=&action=&limit=&offset=`
- `POST /api/v1/audit-log/`

Both endpoints are **superadmin-only** at the route layer. The service supports
tenant filtering, but a regular tenant `ADMIN` cannot read or append audit
entries through the API in this version.

---

## 7. Security and multi-tenancy

### 7.1 Authentication modes

| Mode | Trigger | Resulting principal |
|---|---|---|
| Open demo | `AUTH_REQUIRED=false`, `API_KEY` empty | Anonymous `ADMIN` + superadmin in the default tenant |
| Legacy API key | `X-API-Key` matches `API_KEY` | `ADMIN`, superadmin |
| Bearer token | `Authorization: Bearer <token>` | Token owner's role/tenant |
| Protected | `AUTH_REQUIRED=true` and no valid credential | `401` |

Details:

- Passwords: PBKDF2-HMAC-SHA256, 260 000 iterations, random 16-byte salt.
- API tokens: random URL-safe value shown once; only the SHA-256 hash is
  stored; optional expiry; `last_used_at` is updated on use.
- Token listing is self-service. Token revocation is self-service for
  non-admins; a tenant `ADMIN` can revoke any token belonging to a user in
  their tenant, and a superadmin can revoke any token.
- `ALLOW_PUBLIC_REGISTRATION=false` disables self-registration; bootstrap the
  first admin with `scripts.seed_admin.py`.

### 7.2 Role matrix

Roles are hierarchical (`VIEWER < RESPONDER < ADMIN`).

| Capability | VIEWER | RESPONDER | ADMIN | Superadmin |
|---|---|---|---|---|
| Read incidents/runbooks/rules | ✅ | ✅ | ✅ | ✅ |
| Create/update/delete incidents | — | ✅ | ✅ | ✅ |
| Send webhook test (`/webhooks/test`) | — | ✅ | ✅ | ✅ |
| Approve/reject investigations | — | ✅ | ✅ | ✅ |
| Approve/reject remote jobs | — | ✅ | ✅ | ✅ |
| Read remote agents/jobs | ✅ | ✅ | ✅ | ✅ |
| Create/rotate/enable/disable/revoke remote agents | — | — | ✅ (own tenant) | ✅ |
| Write automation rules | — | — | ✅ | ✅ |
| Write/delete/reindex runbooks | — | — | ✅ | ✅ |
| User management | — | — | ✅ (own tenant) | ✅ |
| Tenant management | — | — | — | ✅ |
| Outbox listing/replay | — | — | — | ✅ |
| Audit-log read/write | — | — | — | ✅ |

Additional checks:

- Tenant admins can only create users in their own tenant.
- Only a superadmin can create or modify another superadmin.
- Audit-log endpoints are superadmin-only in the current API.

### 7.3 Tenant isolation

- Every tenant-facing business query filters by `principal.tenant_id`.
  Superadmin-only surfaces (tenants, outbox, audit log) are intentionally
  global.
- Vector retrieval passes `where={"tenant_id": …}`.
- The investigation API validates `workflow_states.tenant_id` against the
  principal before returning or approving.
- Remote agents, jobs, results, and approvals are tenant-scoped. An agent token
  resolves to exactly one agent/tenant, and poll/ack/result queries include both
  IDs. A tenant admin cannot see or rotate another tenant's agent.
- The remote job approval endpoint re-reads the job and investigation state
  under the caller's tenant before deciding.
- Webhook ingestion rejects empty or unknown `X-Tenant-Slug` values and uses
  the default tenant only when the slug is omitted; a per-tenant secret scopes
  the incident to the matching tenant.

### 7.4 Webhook security

- `X-Webhook-Secret` is mandatory for public adapters.
- Per-tenant secrets are stored as SHA-256 hashes and compared in constant time
  (`hmac.compare_digest`). A supplied tenant slug must resolve; a tenant with a
  hash must present its own secret, while only the legacy default tenant may
  use the global secret with an explicit slug. With no slug, the global secret
  routes to the default tenant. Invalid slugs/secrets return `401`; inactive
  tenants return `403`.
- The browser tester uses the authenticated `/webhooks/test` endpoint, so the
  secret is never shipped to the client bundle.

### 7.5 Abuse controls

- Fixed 60-second window rate limit keyed by client IP + request path
  (`RATE_LIMIT_PER_MIN`, default 60/min). Login is stricter at 10/min.
- Redis failure **fails open** so a metrics outage cannot block incident
  ingestion.
- CORS allows `FRONTEND_URL` plus comma-separated `CORS_ORIGINS`.

### 7.6 Execution safety

- Agent allowlist: `log` safe, `webhook` destructive/approval-gated.
- Agent blocklist: `script`, `slack` are never executed by the agent.
- The allowlist/blocklist covers built-in action names. Custom actions
  registered in `app/automation/registry.py` are trusted code; review them
  before enabling matching rules in an environment where the agent can execute
  automation.
- Script automation rejects shell metacharacters and runs `subprocess.run([path])`
  without a shell.
- Destructive actions require a fresh human approval in the current run.
- Remote remediation is separate from severity-based automation: an LLM can
  only propose a catalog action, the server validates exact parameters, and a
  per-job `RESPONDER+` approval is bound to the tenant, incident, agent,
  action, parameters, risk level, expiry, and approver. The agent also requires
  a local remediation opt-in and validates service/PID allowlists.
- Remote agents authenticate with hashed, expiring credentials whose token is
  shown once at creation/rotation and reused until rotated/expired/revoked.
  can only call the agent-facing heartbeat/poll/ack/result endpoints.

---

## 8. Observability

### 8.1 Metrics

All application counters live in Redis and are mirrored to Prometheus **gauges**
on every scrape. This keeps metrics shareable across API/worker processes and
avoids double-counting when Celery retries. The trade-off is documented in
`IMPLEMENTATION.md`: gauges are snapshots, not monotonic counters.

| Metric | Labels | Meaning |
|---|---|---|
| `incidents_created_total` | `severity` | Incidents created |
| `incidents_completed_total` | `severity` | Incidents that completed processing |
| `incidents_failed_total` | `severity` | Failed incidents |
| `incident_resolution_total_seconds` | `severity` | Cumulative resolution time (reserved) |
| `incident_resolution_average_seconds` | `severity` | Reserved; exporter currently mirrors the total, not an average |
| `ai_requests_total` | — | AI analysis requests |
| `ai_failures_total` | — | AI analysis failures |
| `analysis_count_total` | — | Completed analyses |
| `analysis_total_seconds` | — | Cumulative analysis time |
| `analysis_average_seconds` | — | Average analysis time |
| `llm_tokens_total` | `model`, `type` (`input`/`output`) | Token usage |
| `llm_request_latency_seconds` | `model` | Cumulative LLM latency (reserved) |
| `retrieval_requests_total` | `backend` | RAG retrievals (reserved) |
| `retrieval_failures_total` | `backend` | RAG failures (reserved) |
| `retrieval_latency_seconds` | `backend` | Cumulative RAG latency (reserved) |
| `queue_wait_total_seconds` | `queue` | Cumulative Celery wait (reserved) |
| `queue_wait_average_seconds` | `all` | Average of per-queue totals (reserved) |
| `automation_runs_total` | `action` | Automation executions |
| `automation_failures_total` | `action` | Failed automation executions |
| `automation_total_seconds` | — | Cumulative automation time |
| `automation_average_seconds` | — | Average automation time |
| `webhook_success_total` | — | Successful automation webhook sends |
| `webhook_failure_total` | — | Failed automation webhook sends |
| `webhook_requests_total` | `source` | Inbound webhook receptions |
| `webhook_failures_total` | `source` | Failed inbound webhooks |

Instrumentation note: incident, analysis, automation, and webhook series are
incremented by application code. The resolution-time, LLM, RAG-retrieval, and
queue-wait series are currently exposed as reserved gauges and remain zero
until their call sites are wired.

Scrape endpoint: `GET /metrics` (Prometheus text exposition format).

### 8.2 Tracing

- OpenTelemetry is initialized in `app/core/tracing.py` with a
  `service.name` resource taken from `OTEL_SERVICE_NAME` (or the process
  default).
- When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, spans are batched and exported via
  OTLP HTTP. Without it, spans remain local (trace IDs still appear in logs).
- FastAPI requests are auto-instrumented. Celery workers are instrumented in
  `app/celery_app.py`, so task spans are created in the worker.
- Helper functions expose trace/span IDs.
- `CorrelationIdMiddleware` accepts or generates `X-Request-ID`, stores it on
  the request, attaches it to the active FastAPI span, and echoes it in the
  response.

### 8.3 Logging

- `LOG_JSON=false` → human-readable lines.
- `LOG_JSON=true` → JSON lines with `time`, `level`, `logger`, `message`,
  `correlation_id`, `trace_id`/`span_id` when a span is active, and `exception`
  when present.
- In JSON mode, application logs emitted during a request carry the
  incoming/generated `X-Request-ID` plus the request span's trace/span IDs.
  Uvicorn's own access log is separate. Celery worker logs are configured by
  the `worker_init` signal and, when tracing is active, carry their own task
  trace/span IDs and Celery task IDs. The request ID is not automatically
  forwarded into the queued task payload. The beat process shares the tracing
  setup but uses Celery's scheduler logger.

### 8.4 Health

`GET /health` performs live checks:

```json
{"status": "healthy", "checks": {"database": "ok", "redis": "ok"}}
```

A failing dependency makes `status` equal `degraded`; the endpoint still
returns HTTP 200 so it remains a liveness probe and the dashboard can render
the per-dependency checks. The Compose healthcheck is therefore liveness-only;
for readiness gating, inspect `checks` or add a separate strict endpoint. The
root endpoint `GET /` returns project name/version.

### 8.5 Observability stack (Compose)

- `otel-collector`: OTLP HTTP `4318`, gRPC `4317`, Prometheus exporter `9464`.
  Traces are currently written to the collector log; add an OTLP trace backend
  (Jaeger/Tempo/etc.) when you need a trace UI. The Prometheus exporter is
  metrics-only.
- `prometheus`: scrapes `api:8000/metrics` and `otel-collector:9464`, UI `9090`.
- `grafana`: UI `3001` (admin/admin by default), depends on Prometheus.

---

## 9. API reference

Base URL: `http://localhost:8000/api/v1`

Interactive docs: `http://localhost:8000/docs`

All protected routes honour the optional-auth rules described in §7.

### 9.1 Auth

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/auth/login` | public | Exchange email/password for a bearer token |
| POST | `/auth/register` | public (if enabled) | Self-registration; first user becomes ADMIN + superadmin |
| GET | `/auth/me` | any | Current principal |
| POST | `/auth/tokens` | VIEWER+ (user principal) | Issue an API token for the current user |
| GET | `/auth/tokens` | VIEWER+ (user principal) | List own tokens |
| DELETE | `/auth/tokens/{token_id}` | VIEWER+ (user principal) | Revoke own token; tenant admins can revoke tenant tokens; superadmins any |
| GET | `/auth/users` | ADMIN | List users (tenant-scoped unless superadmin) |
| POST | `/auth/users` | ADMIN | Create a user |
| PATCH | `/auth/users/{user_id}` | ADMIN | Update role/active/password |

The anonymous demo principal has no user row, so `/auth/tokens` listing returns
an empty list and token creation returns `400`. Log in or bootstrap an admin
with `scripts.seed_admin.py` to issue tokens.

### 9.2 Incidents

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/incidents/` | RESPONDER+ | Create an incident (queues analysis) |
| GET | `/incidents/` | VIEWER+ | Paginated list; filters `status`, `severity`, `source`, `q`, `limit` (1–200), `offset` |
| GET | `/incidents/stats/summary` | VIEWER+ | Totals grouped by status/severity |
| GET | `/incidents/{id}` | VIEWER+ | Incident details |
| GET | `/incidents/{id}/runs` | VIEWER+ | Automation execution history |
| PATCH | `/incidents/{id}` | RESPONDER+ | Update title/message/status/severity |
| DELETE | `/incidents/{id}` | RESPONDER+ | Delete incident |

### 9.3 Webhooks

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/webhooks/grafana` | `X-Webhook-Secret` | Grafana alert payload |
| POST | `/webhooks/custom` | `X-Webhook-Secret` | Generic alert payload |
| POST | `/webhooks/test` | RESPONDER+ | In-app drill (no secret in browser) |

### 9.4 Automation rules

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/automation-rules/actions` | VIEWER+ | Registered action names |
| GET | `/automation-rules/` | VIEWER+ | List tenant rules |
| POST | `/automation-rules/` | ADMIN | Create rule (validates action and config) |
| PATCH | `/automation-rules/{id}` | ADMIN | Update rule |
| DELETE | `/automation-rules/{id}` | ADMIN | Delete rule |

### 9.5 Runbooks

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/runbooks/` | VIEWER+ | List runbook names/metadata |
| GET | `/runbooks/{name}` | VIEWER+ | Read a runbook |
| PUT | `/runbooks/{name}` | ADMIN | Create/update; increments version (requires explicit reindex) |
| DELETE | `/runbooks/{name}` | ADMIN | Delete (requires explicit reindex to prune vectors) |
| POST | `/runbooks/reindex` | ADMIN | Async reindex (`202`; synchronous fallback if the broker is down) |
| GET | `/runbooks/reindex/{task_id}` | VIEWER+ | Reindex task status |

### 9.6 Investigations

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/investigations/{incident_id}/start` | VIEWER+ | Start/reset a workflow asynchronously (`202`; `409` if already running) |
| GET | `/investigations` | VIEWER+ | Latest state per incident; `?status=waiting_for_approval` |
| GET | `/investigations/{incident_id}` | VIEWER+ (tenant-scoped) | Current state |
| POST | `/investigations/{incident_id}/approve` | RESPONDER+ | Approve/reject a `waiting_for_approval` remediation |

### 9.7 Tenants

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/tenants/me` | any | Caller's tenant |
| GET | `/tenants/` | superadmin | List tenants |
| POST | `/tenants/` | superadmin | Create tenant; returns the webhook secret shown once |
| PATCH | `/tenants/{id}` | superadmin | Update name/active |

### 9.8 Outbox

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/outbox/?status=&limit=&offset=` | superadmin | Inspect events |
| POST | `/outbox/{event_id}/replay` | superadmin | Replay a `FAILED` event |

### 9.9 Audit log

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/audit-log/?tenant_id=&action=&limit=&offset=` | superadmin | List entries |
| POST | `/audit-log/` | superadmin | Append an entry |

### 9.10 Health / metrics / root

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | public | DB + Redis health |
| GET | `/metrics` | public | Prometheus exposition |
| GET | `/` | public | Project name/version |

### 9.11 Remote agents and jobs

Admin agent management:

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/agents` | ADMIN | Register an agent; returns the token shown once |
| GET | `/agents` | VIEWER+ | List tenant agents (`include_revoked`) |
| GET | `/agents/{id}` | VIEWER+ | Agent details |
| PATCH | `/agents/{id}` | ADMIN | Update display name/hostname/capabilities |
| POST | `/agents/{id}/disable` | ADMIN | Disable polling/execution (re-enable with `enable`) |
| POST | `/agents/{id}/enable` | ADMIN | Re-enable a disabled agent |
| POST | `/agents/{id}/revoke` | ADMIN | Revoke agent and all credentials permanently |
| POST | `/agents/{id}/rotate-credential` | ADMIN | Revoke previous tokens and issue one new token |

Agent-facing API (agent credential only; not a user bearer token):

| Method | Path | Purpose |
|---|---|---|
| POST | `/agent/heartbeat` | Report version/hostname/capabilities; updates last seen |
| POST | `/agent/jobs/poll` | Atomically lease one approved job |
| POST | `/agent/jobs/{id}/ack` | Acknowledge the lease before execution |
| POST | `/agent/jobs/{id}/result` | Submit bounded/redacted result (duplicate-safe) |

Tenant-scoped inspection and approval:

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/remote-jobs?incident_id=&status=&limit=&offset=` | VIEWER+ | List jobs |
| GET | `/remote-jobs/{id}` | VIEWER+ | Job, result, and approval record |
| POST | `/remote-jobs/{id}/approve` | RESPONDER+ | Approve exact job (optional `action_hash`) |
| POST | `/remote-jobs/{id}/reject` | RESPONDER+ | Reject exact job |

### 9.12 Example requests

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"change-me-please"}'

# Create an incident (anonymous demo mode)
curl -X POST http://localhost:8000/api/v1/incidents/ \
  -H 'Content-Type: application/json' \
  -d '{"title":"High CPU","message":"CPU 95% for 5m","severity":"HIGH"}'

# Grafana-style webhook
curl -X POST http://localhost:8000/api/v1/webhooks/grafana \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: super-secret-key' \
  -d '{"alerts":[{"status":"firing","fingerprint":"fp-1",
       "labels":{"alertname":"HighCPU","instance":"api-1","severity":"critical"},
       "annotations":{"summary":"CPU above 95%"}}]}'

# Start an investigation (returns 202 immediately)
curl -X POST http://localhost:8000/api/v1/investigations/1/start \
  -H "Authorization: Bearer $TOKEN"

# Approve a pending remediation
curl -X POST http://localhost:8000/api/v1/investigations/1/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"approved":true,"reason":"Reviewed runbook steps"}'

# Register a remote agent (ADMIN). Save the returned token once.
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"display_name":"lab-target-1","hostname":"lab-target-1","agent_key":"lab-target-1"}'

# Approve one exact remote action (RESPONDER+)
curl -X POST http://localhost:8000/api/v1/remote-jobs/7/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"approved":true,"reason":"lab change window","action_hash":"<hash from the job>"}'
```

---

## 10. Frontend

React 19 + TypeScript + Vite SPA, styled with Tailwind CSS 4.

### 10.1 Pages

| Route | Page | Features |
|---|---|---|
| `/` | Dashboard | Stats, filters, recent incidents, health |
| `/incidents` | Incidents | Search/filter, create, delete |
| `/incidents/:id` | Incident detail | Edit, automation runs, audit timeline, investigation link |
| `/incidents/:id/investigation` | Investigation | Status, risk, evidence, plan, remote job timeline, per-job approval, 3 s polling |
| `/approvals` | Approvals | Local approval queue, pending remote actions, start-investigation shortcuts |
| `/agents` | Remote agents | Register agents, show online/offline, rotate/enable/disable/revoke, token shown once |
| `/rules` | Automation rules | CRUD, action registry, JSON config editor |
| `/runbooks` | Runbooks | Create/edit/delete, async reindex |
| `/webhooks` | Webhook tester | Grafana/custom drill without exposing secrets |
| `/login`, `/register` | Auth | Bearer token stored in `localStorage` |
| `/settings` | Settings | Profile, tokens, users, tenants (superadmin) |

### 10.2 Data layer

- Axios instance (`src/api/client.ts`) with:
  - `baseURL = VITE_API_URL ?? http://localhost:8000/api/v1`; the Compose
    image is built with `/api/v1`, which nginx proxies to the API service
  - optional `VITE_API_KEY` header
  - bearer token injection from `localStorage`
  - consistent error extraction (`detail` string or validation array)
- TanStack Query handles caching, invalidation, and polling.
- `useInvestigation` polls every 3 s while status is `in_progress`,
  `waiting_for_agent`, or `waiting_for_approval`.
- `usePendingApprovals` polls every 5 s.
- `useRemoteJobs` polls every 3 s while any job is pending/dispatched, and
  `usePendingRemoteJobs` polls the cross-incident remote approval queue every
  5 s.
- `src/api/remote.ts` owns agent provisioning, rotation, status changes, remote
  job listing, and per-job approve/reject mutations.

### 10.3 Frontend commands

```bash
cd frontend
npm install
npm run dev       # Vite dev server, default http://localhost:5173
npm run build     # tsc -b && vite build
npm run lint      # oxlint
npm run preview   # preview production build
```

---

## 11. Configuration

Settings are loaded from environment variables and `.env` via
`pydantic-settings`. Environment variables override `.env`.

### 11.1 Environment variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `APP_NAME` | `AI Incident Response System` | no | Display name |
| `APP_VERSION` | `0.1.0` | no | Version |
| `DEBUG` | `true` | no | Debug logging level |
| `DATABASE_URL` | — | **yes** | SQLAlchemy URL (psycopg driver) |
| `REDIS_URL` | — | **yes** | Celery broker/result backend + counters |
| `WEBHOOK_SECRET` | — | **yes** | Global webhook secret |
| `GEMINI_API_KEY` | `""` | for Gemini | Google AI key |
| `AI_MODEL` | `gemini-2.5-flash` | no | Model name |
| `AI_PROVIDER` | `gemini` | no | `gemini\|openai\|ollama\|vllm\|lmstudio\|mock` |
| `OPENAI_API_KEY` | `""` | for OpenAI | OpenAI-compatible key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | no | Compatible endpoint |
| `OPENAI_MODEL` | `gpt-4o-mini` | no | Compatible model |
| `RAG_THRESHOLD` | `1.2` | no | Max cosine distance kept |
| `RAG_BACKEND` | `chroma` | no | `chroma\|pgvector\|both` |
| `CHUNK_OVERLAP_CHARS` | `200` | no | Overlap between split chunks |
| `API_KEY` | `""` | no | Legacy shared key (ADMIN principal) |
| `AUTH_REQUIRED` | `false` | no | Require credentials on protected routes |
| `AUTH_TOKEN_TTL_HOURS` | `24` | no | Bearer token lifetime |
| `ALLOW_PUBLIC_REGISTRATION` | `true` | no | Enable `/auth/register` |
| `BOOTSTRAP_ADMIN_EMAIL` | `""` | no | Used once by seed script |
| `BOOTSTRAP_ADMIN_PASSWORD` | `""` | no | Used once by seed script |
| `DEFAULT_TENANT_SLUG` | `default` | no | Bootstrap tenant slug |
| `DEFAULT_TENANT_NAME` | `Default` | no | Bootstrap tenant name |
| `RATE_LIMIT_PER_MIN` | `60` | no | POST writes per IP per minute (0 disables) |
| `REMOTE_AGENT_TOKEN_TTL_DAYS` | `90` | no | Agent credential lifetime |
| `REMOTE_JOB_DEFAULT_TTL_SECONDS` | `900` | no | Default job/approval expiry |
| `REMOTE_MAX_INVESTIGATION_ROUNDS` | `3` | no | Maximum diagnostic planning rounds |
| `REMOTE_MAX_ACTIONS_PER_ROUND` | `3` | no | Cap per planner round |
| `REMOTE_MAX_TOTAL_ACTIONS` | `10` | no | Total action budget per run |
| `REMOTE_VERIFICATION_MEMORY_PERCENT` | `80` | no | Pass threshold for post-remediation memory |
| `REMOTE_VERIFICATION_MEMORY_DROP` | `10` | no | Alternative pass: memory dropped by this percent |
| `FRONTEND_URL` | `http://localhost:5173` | no | Primary CORS origin |
| `CORS_ORIGINS` | `""` | no | Extra comma-separated origins |
| `LOG_JSON` | `false` | no | JSON log lines |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `""` | no | OTLP HTTP trace endpoint; empty = local spans only |
| `OTEL_SERVICE_NAME` | `""` | no | `service.name` resource; falls back to API/worker defaults |

### 11.2 Frontend environment

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000/api/v1` | API base URL baked at build/dev time; Compose uses `/api/v1` + nginx proxy |
| `VITE_API_KEY` | unset | Optional legacy API key header; Compose forwards it as a build arg |

### 11.3 Example `.env`

```dotenv
APP_NAME=AI Incident Response System
DEBUG=True
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/airs
REDIS_URL=redis://localhost:6379/0
WEBHOOK_SECRET=super-secret-key
GEMINI_API_KEY=
AI_PROVIDER=gemini
AI_MODEL=gemini-2.5-flash
RAG_BACKEND=chroma
RAG_THRESHOLD=1.2
AUTH_REQUIRED=false
API_KEY=
FRONTEND_URL=http://localhost:5173
LOG_JSON=false
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
# OTEL_SERVICE_NAME=airs-api
```

---

## 12. Local development

### 12.1 Prerequisites

- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 14+ with the `vector` extension available
- Redis 7+
- Node.js 24+ / npm
- Optional: Docker + Compose

### 12.2 Setup

```bash
git clone https://github.com/<username>/ai-incident-response-system.git
cd ai-incident-response-system

uv venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv sync

cp .env.example .env             # fill DATABASE_URL, REDIS_URL, WEBHOOK_SECRET

# 1. Database schema (must include the workflow_states revision)
uv run alembic upgrade head

# 2. Seed runbooks into PostgreSQL (idempotent)
uv run python -m scripts.import_runbooks

# 3. Build the vector index
uv run python -m app.rag.ingest --backend chroma

# 4. Optional: first admin for protected deployments
BOOTSTRAP_ADMIN_EMAIL=admin@example.com \
BOOTSTRAP_ADMIN_PASSWORD='change-me-please' \
uv run python -m scripts.seed_admin
```

### 12.3 Run the stack

```bash
# Terminal 1 — API
uv run uvicorn app.main:app --reload

# Terminal 2 — worker
uv run celery -A app.celery_app.celery_app worker --loglevel=info

# Terminal 3 — beat (outbox poller)
uv run celery -A app.celery_app.celery_app beat --loglevel=info

# Terminal 4 — frontend
cd frontend && npm run dev

# Terminal 5 — optional remote agent (after registering it and copying its token)
cd remote-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env           # set AIRS_BASE_URL + AIRS_AGENT_TOKEN
set -a; . ./.env; set +a
.venv/bin/python -m app.main
```

Open:

- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Metrics: `http://localhost:8000/metrics`
- Frontend: `http://localhost:5173`

### 12.4 Verify the pipeline

```bash
curl -X POST http://localhost:8000/api/v1/incidents/ \
  -H 'Content-Type: application/json' \
  -d '{"title":"Smoke test","message":"CPU 95% for 5m","severity":"HIGH"}'

# Watch status move PENDING -> RUNNING -> COMPLETED
curl http://localhost:8000/api/v1/incidents/1

# Outbox should reach PUBLISHED
curl http://localhost:8000/api/v1/outbox/   # superadmin in protected mode
```

If `AUTH_REQUIRED=true`, add
`-H "Authorization: Bearer <token>"` (or `-H "X-API-Key: <API_KEY>"`) to the
incident and outbox calls. The example `.env` leaves auth disabled for the demo.

Remote demo flow:

1. Open **Agents** (or `POST /api/v1/agents` as ADMIN) and create an agent whose
   `agent_key`/`hostname` is `lab-target-1`.
2. Start the agent from `remote-agent/` with the returned token.
3. Send a Grafana alert with `labels.agent_id=lab-target-1` (or `instance`).
4. Start the investigation. The page shows diagnostic jobs and polls while the
   agent works.
5. When a destructive action is proposed, approve or reject that exact job from
   the investigation page or **Approvals**. With
   `AIRS_ENABLE_REMEDIATION=false` the agent refuses destructive actions and
   reports a clear failure instead of executing them.

### 12.5 Useful scripts

| Script | Command | Purpose |
|---|---|---|
| Import runbooks | `uv run python -m scripts.import_runbooks [--overwrite]` | Seed markdown into PostgreSQL |
| Seed admin | `uv run python -m scripts.seed_admin` | Create/promote bootstrap admin |
| Seed rules | `uv run python -m scripts.seed_automation_rules` | Idempotent baseline automation rules |
| Playground | `uv run python -m scripts.playground` | Create/list demo incidents |
| RAG evaluation | `uv run python -m scripts.rag_eval --backend chroma --k 3 --k 5` | Retrieval quality report |

---

## 13. Docker Compose

The Compose stack lives in `docker/`.

```bash
cd docker
docker compose up --build
```

The base Compose file uses `${GEMINI_API_KEY:-dummy}` so no real secret is
baked into the image. Analysis therefore falls back to the heuristic analyzer
unless you export `GEMINI_API_KEY` (or set `AI_PROVIDER=openai` and the matching
OpenAI-compatible variables) before `docker compose up`. Compose reads
`docker/.env`; create it with only the Compose overrides you need (for example
`GEMINI_API_KEY`, `AI_PROVIDER`, or `WEBHOOK_SECRET`). The same `docker/.env`
is used when invoking Compose from the repository root with
`-f docker/docker-compose.yml`, because the Compose project directory is
`docker/`. Do not copy the root development `.env` verbatim: its
`DATABASE_URL`, `REDIS_URL`, and `FRONTEND_URL` targets are for the host, while
Compose supplies in-cluster values and defaults `FRONTEND_URL` to
`http://localhost:3000`. A shell export works in either location; use
`--env-file` only if you keep overrides in a different file.

### 13.1 Services

| Service | Image | Port | Notes |
|---|---|---|---|
| `db` | `pgvector/pgvector:pg16` | `5432` | Healthcheck, persistent `pgdata` |
| `redis` | `redis:7` | `6379` | Healthcheck |
| `migrate` | same API image | — | One-shot `alembic upgrade head`; gates API/worker/beat |
| `api` | `docker/Dockerfile.api` | `8000` | Liveness healthcheck via Python `urllib` (`/health`) |
| `worker` | same image | — | Celery worker; persists Chroma in `chroma_data` |
| `beat` | same image | — | Outbox poller |
| `frontend` | `frontend/Dockerfile` | `3000` → nginx 80 | Production build |
| `agent` | `remote-agent/Dockerfile` | — | Optional `remote-demo` profile; diagnostics-only, polls outbound |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.108.0` | `4317`, `4318` | OTLP receiver; metrics on `9464`; traces logged |
| `prometheus` | `prom/prometheus:v2.53.0` | `9090` | Scrapes API + collector |
| `grafana` | `grafana/grafana:11.0.0` | `3001` → 3000 | admin/admin default |

Hardening:

- `restart: unless-stopped` on long-running services.
- CPU/memory limits and reservations.
- `stop_grace_period` 5–15 s.
- `depends_on` with health conditions.
- A one-shot `migrate` service gates API/worker/beat on
  `service_completed_successfully`.
- JSON logs and OTLP tracing enabled for API and worker; beat shares the same
  environment and tracing setup.
- The API image syncs the locked dependency graph (which includes the CUDA
  PyTorch packages), then replaces `torch` with the CPU-only wheel in the same
  image layer. The final image omits the CUDA runtime, but a clean build still
  downloads the CUDA wheel set and needs roughly 25–30 GB of free Docker disk
  (30–40 GB is comfortable) before the layer is committed.

### 13.2 Migrations and optional seed data

The one-shot `migrate` service runs `alembic upgrade head` before the API,
worker, and beat start. Migrations are therefore applied automatically on a
fresh database:

```bash
docker compose up --build
```

To re-run migrations manually:

```bash
docker compose run --rm migrate
```

Optional demo seed data:

```bash
docker compose run --rm api python -m scripts.import_runbooks

# Chroma lives on the worker's chroma_data volume; build it in the worker
# container so analysis/reindex tasks can see it.
docker compose run --rm worker python -m app.rag.ingest --backend chroma

# Optional admin
docker compose run --rm \
  -e BOOTSTRAP_ADMIN_EMAIL=admin@example.com \
  -e BOOTSTRAP_ADMIN_PASSWORD=change-me-please \
  api python -m scripts.seed_admin
```

For `RAG_BACKEND=pgvector`, run the ingest against the API/database instead
(`docker compose run --rm api python -m app.rag.ingest --backend pgvector`);
the pgvector table lives in PostgreSQL.

Optional Compose demo agent:

```bash
# 1. Register an agent in the UI/API and copy its token (shown once).
# 2. Export the token for Compose.
export AIRS_AGENT_TOKEN='...'
# 3. Start only the optional diagnostics-only agent profile.
docker compose --profile remote-demo up -d agent
docker compose logs -f agent
```

This agent inspects its own container (memory, processes, disk, load) and is
honest about its limits: there is no systemd inside the container, so
`restart_service` is not available. Use a disposable Linux VM with the systemd
unit for remediation demos.

### 13.3 Port conflicts

If local PostgreSQL/Redis already bind `5432`/`6379`, Compose will fail to
start. Either stop the local services or remap the host ports in
`docker/docker-compose.yml`.

### 13.4 Validate configuration

```bash
docker compose -f docker/docker-compose.yml config -q
docker compose -f docker/docker-compose.yml config --services
```

### 13.5 Chroma persistence

- The `worker` service mounts the named volume `chroma_data` at
  `/app/app/rag/chroma_db`. Reindex tasks run in the worker, so edits survive
  worker/container recreation.
- The API does not mount that volume. Its broker-down synchronous reindex
  fallback writes to the API container filesystem; normal reindexing goes
  through the worker.
- The API and worker share the `hf_cache` volume at
  `/root/.cache/huggingface`, so the `all-MiniLM-L6-v2` model is downloaded
  once and survives container recreation.
- If you scale to multiple worker replicas, use `pgvector` instead of sharing
  one embedded Chroma volume across replicas.

### 13.6 Named volumes and data retention

Compose declares `pgdata`, `chroma_data`, `hf_cache`, and `agent_state` as
named volumes and creates them automatically on the first `docker compose up`.
With the default project name (`docker` for this Compose project), Docker names
them `docker_pgdata`, `docker_chroma_data`, `docker_hf_cache`, and
`docker_agent_state`. If you set `COMPOSE_PROJECT_NAME`, that prefix changes. Do
not pre-create volumes with different names expecting Compose to reuse them.

`docker compose down` keeps the volumes. `docker compose down -v` deletes
PostgreSQL data, the embedded Chroma index, the Hugging Face model cache, and
the optional agent's local execution store. Back up PostgreSQL before using
`-v` outside a disposable demo environment.

---

## 14. Database migrations

The migration chain is:

```text
64aa69a79934 (initial schema)
      │
      ▼
4ff6a5f6da7a (runbook version column)
      │
      ▼
6cd48e3599e7 (workflow_states table)
      │
      ▼
8d1c0a7b2f34 (remote agents, credentials, jobs, results, approvals)
```

Common commands:

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic history
uv run alembic revision --autogenerate -m "describe change"
```

Important implementation details:

- `migrations/env.py` imports the model metadata; new models must be imported
  there (directly or through `app.models`) to appear in autogenerate.
- `app/celery_app.py` explicitly imports every model module so SQLAlchemy can
  resolve foreign keys during worker flushes (for example
  `incidents.tenant_id → tenants.id`). Missing imports cause
  `NoReferencedTableError` at task runtime.
- The initial migration creates the `vector` extension and baseline tables.
- The `workflow_states` revision must be applied before using investigations;
  otherwise every investigation request fails with an unhandled 500.

---

## 15. Testing and quality

### 15.1 Commands

```bash
uv run pytest -q
uv run ruff check app tests migrations scripts
uv run ruff check remote-agent/app remote-agent/tests
cd frontend && npm run build && npm run lint
cd remote-agent && uv run --no-project --with pytest --with httpx python -m pytest -q
```

Latest local result:

```text
122 passed, 2 warnings
remote-agent: 10 passed
ruff: All checks passed!
frontend: build + oxlint clean
```

### 15.2 Test coverage map

| Test file | Focus |
|---|---|
| `test_api.py` | Incident API, CRUD, pagination, filters |
| `test_dedup.py` | Fingerprint dedup, occurrence counting, severity escalation |
| `test_webhook_adapters.py`, `test_webhook_action.py` | Grafana/custom parsing and webhook delivery |
| `test_outbox.py` | Atomic enqueue, dispatch, retry state |
| `test_outbox_dlq.py` | Jitter, stale recovery, DLQ listing/replay |
| `test_automation.py`, `test_engine.py`, `test_custom_action.py` | Rule execution, fail-fast, custom actions |
| `test_auth.py`, `test_security.py` | Login, tokens, roles, rate limits |
| `test_cross_tenant.py` | Tenant isolation across resources |
| `test_tenant_isolation.py` | API-level incidents/investigations/runbooks/rules/webhooks with real token principals |
| `test_rag_tenant_isolation.py` | Direct Chroma/pgvector/tool/analyzer tenant filtering |
| `test_reliability.py` | Broker outage recovery, duplicate delivery, retry, completed-work skip |
| `test_audit_log.py` | Append-only audit trail |
| `test_runbooks.py`, `test_rag.py`, `test_rag_backend.py`, `test_chroma_store.py` | Runbook CRUD, chunking, retrieval, backends |
| `test_hardening.py` | Retry/timeout/reliability knobs |
| `test_metrics_resilience.py` | Metrics survive Redis outages |
| `test_investigation.py` | Graph compilation, persistence, start/approve, tenant scoping, loop guard |
| `test_agent_tools.py` | Tenant-scoped runbook search and tool input bounds |
| `test_ai_provider.py`, `test_ai_user_choice.py`, `test_ai_fallback.py` | Provider selection and fallback |
| `test_remote_agents.py` | Agent credentials/revocation, tenant isolation, job lease/ack/duplicate result, exact approval binding, remote e2e, destructive lease recovery |
| `remote-agent/tests/test_actions.py` | Agent allowlists, remediation opt-in, idempotent execution, crash-safe destructive refusal, redaction/caps |

### 15.3 RAG evaluation

```bash
uv run python -m scripts.rag_eval --backend chroma --k 3 --k 5
```

The evaluation set covers CPU, disk, filesystem, memory, network, PostgreSQL,
and Redis runbooks. The latest run reported **MRR 0.843** and **citation
accuracy 1.0**.

---

## 16. Operations and troubleshooting

### 16.1 Symptom → cause → fix

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser shows “Network Error” on investigation/approve | Missing `workflow_states` table (500 without CORS headers), or server down | `uv run alembic upgrade head`; check API logs; verify `/health` |
| `401 Not authenticated` | `AUTH_REQUIRED=true` and no/expired token | Log in, pass `Authorization: Bearer …`, or set `AUTH_REQUIRED=false` for the demo |
| `NoReferencedTableError: incidents.tenant_id` | Worker imported models before `tenants` was registered | Import all model modules in `app/celery_app.py`; restart worker |
| `Received unregistered task of type 'run_investigation'` | Stale worker started before the task existed | Stop all workers, start one fresh worker |
| Analysis stuck `PENDING` | Beat/worker down, broker down, event not dispatched | Check `outbox_events`; start beat/worker; replay failed events |
| Outbox event `FAILED` | 10 publish attempts exhausted | `GET /outbox/?status=FAILED`, then `POST /outbox/{id}/replay` |
| Gemini `429 RESOURCE_EXHAUSTED` | Free-tier daily quota | Automatic heuristic fallback; or set `AI_PROVIDER=mock` / use a new key |
| Analysis completed with `model="fallback"` | Provider quota/network/auth failure | Expected degradation; fix the provider key/endpoint or set `AI_PROVIDER=mock` |
| Analysis `FAILED` | Non-provider exception (DB/schema/task bug), or the fallback itself failed | Inspect worker logs for the exception; the task retries a bounded number of times |
| `retrieve_runbooks failed: String should have at most 500 characters` | Alert payload longer than tool limit | Fixed by clipping the query to 500 chars |
| Investigation stuck `in_progress` | Worker died mid-run, or old state | Restart worker; start the investigation again; inspect `workflow_states` |
| No pending approvals | No investigation is `waiting_for_approval` | Start an investigation on a HIGH/CRITICAL incident |
| Approve returns 400 | Investigation does not require approval, or already approved | Check `requires_approval`/`approved` via `GET /investigations/{id}` |
| Approve returns 409 | The latest state is not `waiting_for_approval` | Poll until the workflow pauses, or re-start the investigation |
| Start returns 409 | A non-stale investigation is already `in_progress` | Wait for it to finish; a crashed run becomes restartable after 10 minutes |
| CORS error in browser | Origin not in `FRONTEND_URL`/`CORS_ORIGINS` | Match the browser origin exactly (scheme/host/port) |
| Ports 5432/6379 already in use | Local PostgreSQL/Redis running | Stop them or remap Compose ports |
| Chroma results stale after runbook edit | Index not rebuilt | `POST /runbooks/reindex` or run ingest |
| Agent never appears online | Wrong `AIRS_BASE_URL`, token revoked/expired, or agent cannot reach the API | Check `journalctl -u airs-agent`; test `/api/v1/agent/heartbeat`; rotate the credential |
| Investigation stays `waiting_for_agent` | Agent offline, heartbeat not active, or jobs not polled | Check **Agents** last-seen; ensure worker/beat and agent are running |
| Remote approval returns 409 | Job changed, expired, already decided, or belongs to a superseded run | Refresh the investigation; create a fresh run if needed |
| Remote remediation reports FAILED immediately | Agent has `AIRS_ENABLE_REMEDIATION=false`, service not allowlisted, or PID revalidation failed | Set the opt-in only on a lab host; update `AIRS_ALLOWED_SERVICES`; re-investigate |
| Destructive job becomes `UNKNOWN` | Agent acknowledged then lost its lease/crashed | Reconcile the host manually; AIRS will not replay destructive work automatically |

### 16.2 Celery operations

```bash
# Inspect
uv run celery -A app.celery_app.celery_app inspect registered
uv run celery -A app.celery_app.celery_app inspect active

# Graceful shutdown of all workers
uv run celery -A app.celery_app.celery_app control shutdown

# Flower UI
uv run celery -A app.celery_app.celery_app flower
```

Rules:

- After deploying new tasks or models, restart **every** worker. Prefork
  workers do not hot-reload, and a stale worker that predates a task will
  reject it as `Received unregistered task`.
- Multiple workers are safe when they run the same image/code and register the
  same tasks. Avoid leaving an old worker fleet running alongside a new one.
- `task_acks_late=True` plus `worker_prefetch_multiplier=1` trades throughput
  for at-least-once safety.
- Hard time limit: 300 s; soft time limit: 270 s; up to 5 retries. Celery
  autoretry handles the configured transient exceptions with exponential
  backoff and jitter; generic analysis failures use a fixed 30 s countdown.

### 16.3 Stale investigation state cleanup

The API always reads the latest `workflow_states` row per incident. If an old
run is stuck and you do not want to wait for the task timeout:

```sql
-- Inspect the latest state per incident
SELECT w.*
FROM workflow_states w
JOIN (
  SELECT incident_id, MAX(id) AS mid
  FROM workflow_states
  GROUP BY incident_id
) x ON w.id = x.mid
ORDER BY w.incident_id;
```

Once the 10-minute stale window has passed, start the investigation again from
the UI/API; the start endpoint resets approval, execution, evidence, and plan
fields and dispatches a fresh run.

### 16.4 Rebuilding the vector index

```bash
# Chroma
uv run python -m app.rag.ingest --backend chroma

# pgvector
uv run python -m app.rag.ingest --backend pgvector

# Both
uv run python -m app.rag.ingest --backend both
```

The ingest script prunes stale chunks and stores a `chunk_hash` for
change detection.

### 16.5 Database backup/restore

```bash
# libpq does not understand SQLAlchemy's +psycopg driver suffix.
export PG_URL="${DATABASE_URL/postgresql+psycopg/postgresql}"
pg_dump -Fc "$PG_URL" > airs.dump
pg_restore -d "$PG_URL" --clean --if-exists airs.dump
```

`workflow_states`, `audit_logs`, and `automation_runs` are append-mostly; they
grow over time and should be included in retention/archival planning.

---

## 17. Design decisions and trade-offs

### 17.1 At-least-once, not exactly-once

The outbox publishes at least once. Duplicate deliveries are absorbed by:

- PostgreSQL advisory lock per incident in `analyze_incident`.
- `processing_plan()` status checks (skip completed analysis/automation).
- Fingerprint uniqueness at ingestion.
- A separate advisory lock in `run_investigation`, plus guards that skip
  duplicate deliveries when the latest run is `completed` or still
  `waiting_for_approval`.
- A per-dispatch `run_id`: if a newer start/approval supersedes a slow worker,
  the old worker discards its result instead of overwriting the new state.

This avoids distributed transactions while keeping failure recovery simple.

### 17.2 Append-only workflow snapshots

The start endpoint, approval endpoint, and each Celery task invocation persist
full state snapshots instead of mutating one row. The graph itself does not
write after every node; the worker persists the final result (including the
`waiting_for_approval` pause). Benefits: auditability, replay/debug, and safe
concurrent reads. Cost: table growth; queries must select the latest row by
`id` (ties in `updated_at` are possible within one second).

### 17.3 Gauges mirrored from Redis

Prometheus counters do not aggregate correctly across multiple API/worker
processes when each process exposes its own counter. AIRS keeps the source of
truth in Redis and mirrors values into gauges on scrape. The trade-off is that
gauges are snapshots, not monotonic counters; rate calculations should use
`increase()`-style queries with care, or derive deltas from the Redis values.

### 17.4 Shadow-mode agent

For the built-in actions, the agent never executes `script` or `slack`, and
`webhook` requires approval. Custom actions are trusted code and sit outside
this policy. This keeps the blast radius small for the default registry while
still demonstrating autonomous investigation and policy enforcement.

### 17.5 Single agent, not a swarm

A single stateful graph is easier to audit, reason about, and persist than a
multi-agent system. Tool calls are explicit and node progress is captured in
the persisted `steps_completed` list.

### 17.6 Chroma vs pgvector

- Chroma is the default because it is zero-config and ideal for the demo.
- pgvector is the production path when you want a single PostgreSQL dependency
  and SQL-native backups.
- Both share the same retrieval interface, so switching is a configuration
  change plus a reindex.

### 17.7 Optional auth

The demo experience is open by default (`AUTH_REQUIRED=false`). Production
deployments should set `AUTH_REQUIRED=true`, disable public registration, seed
an admin, and use per-tenant webhook secrets.

### 17.8 Polling over WebSockets

Investigation status is polled every 3 s while running. This is simpler and
works through proxies/CDNs; the cost is modest extra requests. A WebSocket/SSE
upgrade is a possible future improvement.

### 17.9 Durable remote jobs, not inbound SSH

The remote path uses outbound polling and PostgreSQL-backed jobs instead of
inbound SSH or a long-running worker per incident. This avoids opening inbound
management ports, keeps every step restartable, and makes the UI's pending
remote action the database source of truth. The cost is polling latency
(configurable, default 5 s), at-least-once delivery, and the need for an agent
on each target. The agent is a constrained action runner, not a general shell.

### 17.10 Remote remediation is separate from severity automation

The existing `AutomationEngine` is severity/rule-driven and runs inside the
AIRS worker. Remote remediation cannot reuse it safely because it must target a
specific host, use a different action catalog, and bind approval to one exact
job. Keeping the layers separate avoids giving the LLM a path to arbitrary
automation rules and makes the remote approval record auditable on its own.

---

## 18. Performance characteristics

Measured on the local development stack (PostgreSQL + Redis + Chroma + Celery):

| Operation | Observed |
|---|---|
| `POST /investigations/{id}/start` | ~0.1 s (`202 Accepted`) |
| `POST /investigations/{id}/approve` | ~0.08 s (`200 OK`) |
| Investigation to `waiting_for_approval` | ~25 s (includes RAG + LLM call/fallback) |
| Approve → `completed` | ~15 s |
| `GET /investigations/{id}` (warm) | 30–50 ms |
| Analysis task | dominated by LLM latency; 2+ minutes on slow providers |
| Incident list/stats | single-digit ms after warm-up |

Concurrency and limits:

- Celery worker concurrency defaults to the host CPU count; pass
  `--concurrency=N` (or add it to the Compose worker command) to cap it. The
  Compose worker has a 1-CPU limit but does not pin Celery concurrency, so set
  `--concurrency=1` or `2` explicitly for predictable resource use.
- `worker_prefetch_multiplier=1` prevents one worker from hoarding tasks.
- Task hard limit 300 s / soft limit 270 s.
- Chroma embedding model loads once per process; first request after a cold
  start is slower (tens of seconds).
- The first request after a code reload can take 6–14 s while Uvicorn/Vite
  re-imports and recompiles; subsequent requests are fast.

Cost controls:

- No LLM call when RAG evidence is below threshold (abstention).
- `k=3` retrieval by default.
- Deterministic fallback avoids repeated paid retries when the provider is
  down.
- Analysis and automation already marked terminal are skipped on redelivery.

---

## 19. Known limitations and roadmap

### Real vs mock integrations

| Area | Current behavior | Status |
|---|---|---|
| PostgreSQL persistence, migrations, tenant FKs | Real PostgreSQL schema and Alembic migrations | Real |
| Redis broker/counters, Celery outbox | Real Redis + Celery; at-least-once delivery | Real |
| Tenant-scoped incidents/rules/runbooks/investigations | Enforced in queries and services; tested through real token principals | Real |
| RAG retrieval | Real Chroma and pgvector backends with tenant filters | Real |
| Webhook authentication | Per-tenant SHA-256 secret hashes; global secret only for default/no-slug flow | Real |
| Auth/RBAC | Bearer tokens, PBKDF2 passwords, `VIEWER < RESPONDER < ADMIN` | Real |
| Audit log | Append-only at the application layer, stored in PostgreSQL | Real (app-level) |
| OpenTelemetry | OTLP traces to collector logs; correlation IDs in logs | Real |
| `get_service_metrics` | Deterministic placeholder values | **Mock** |
| `get_recent_logs` | Deterministic placeholder lines | **Mock** |
| `get_deployment_history` | Deterministic placeholder deployments | **Mock** |
| Prometheus/Grafana | Metrics endpoint and stack exist; agent tools do not query Prometheus | Partial |
| LLM provider | Gemini/OpenAI-compatible adapters; heuristic fallback; tests use mocks | Real adapters, mock-tested |
| Investigation execution | Read-only tools; `log` safe, `webhook` approval-gated, `script`/`slack` blocked | Shadow mode |
| Remote agent | Outbound poll/ack/result, local allowlist, idempotent execution store | Real |
| Remote diagnostics | Memory, CPU, disk, process, systemd status/journal | Real on a Linux host |
| Remote remediation | `restart_service`, `terminate_process`, approval-gated, local opt-in | Real, v1 catalog only |
| Remote agent Compose profile | Diagnostics-only container; no systemd inside | Optional demo |

### Reliability and consistency

- Delivery is **at-least-once**, not exactly-once. The outbox and Celery can
  redeliver after a broker/worker failure. Duplicate work is absorbed by the
  PostgreSQL advisory lock, persisted status checks, and `processing_plan()`.
- Remote job delivery is also at-least-once. Diagnostic work may be retried; a
  destructive job that was acknowledged and then lost becomes `UNKNOWN` and is
  never replayed automatically. The agent-authored result is unique per job,
  so duplicate posts return the stored outcome.
- The remote agent is not a sandbox. It is a constrained action runner with a
  small allowlist, but it must still run with enough privilege to inspect
  `/proc` and, when enabled, restart allowlisted systemd services.
- PostgreSQL advisory locks are exercised in production PostgreSQL. The
  SQLite test suite emulates the lock as a no-op so task logic can be tested
  without a database server. Remote restart/approval/result paths also use a
  PostgreSQL row-lock order (latest workflow state row, then job row); SQLite
  tests exercise the state machine but not true concurrent lock contention.
- A definitive `automation_status=FAILED` is terminal on redelivery. Re-sending
  external side effects requires explicit operator action.
- A generic analysis failure requests a bounded Celery retry; after the retry
  budget is exhausted the analysis remains `FAILED` for inspection.
- Concurrent duplicate delivery relies on the PostgreSQL advisory lock. The
  focused tests cover sequential duplicate delivery, retry recovery, broker
  outage recovery, and completed-work skip.

### Operational limitations

- `POST /runbooks/reindex` is global: a tenant admin can trigger a rebuild of
  the shared vector index. Reindexing is not yet tenant-scoped.
- Runbook edits require an explicit reindex before retrieval reflects them.
- Embedded Chroma is persisted on a single worker volume. Scaling to multiple
  workers requires `pgvector` (or a shared, concurrency-safe vector service).
- The audit-log API is superadmin-only; tenant admins cannot inspect their own
  audit trail yet. Append-only is enforced by application code, not a database
  trigger.
- The investigation agent's allowlist/blocklist covers built-in action names.
  Custom actions registered in `app/automation/registry.py` are trusted code
  and are not filtered by the agent policy.
- Several `/metrics` series (resolution time, LLM tokens/latency, RAG
  retrieval, and queue wait) are exposed as reserved gauges but are not yet
  incremented by application code; they remain zero until instrumented.
- Investigation status uses polling, not WebSockets/SSE.
- The default Gemini free tier can exhaust its daily quota; the fallback keeps
  the pipeline green but produces heuristic analysis.
- Only the default tenant is auto-provisioned; additional tenants are created
  via the superadmin API.
- Webhook adapters currently cover Grafana and a generic custom schema; GitHub
  and Prometheus sources are modeled but not adapter-complete.
- Lower-severity investigations are plan-only. Built-in destructive actions
  remain shadow-mode/approval-gated.
- Remote v1 remediation is intentionally limited to `restart_service` and
  `terminate_process`. There is no arbitrary shell, package manager, file
  editing, or multi-host fan-out.
- Remote agents need outbound network access to the AIRS API. TLS termination
  and certificate rotation are the deployment's responsibility; the agent can
  verify a custom CA bundle.
- Grafana dashboards and alert rules are not provisioned as code.
- The demo defaults to optional auth (`AUTH_REQUIRED=false`); production
  deployments must enable auth, disable public registration, and use per-tenant
  webhook secrets.
- The frontend does not bundle a Content-Security-Policy; deployment proxies
  should add one.

Roadmap:

- Real Prometheus/Loki/CI adapters for investigation tools.
- Provisioned Grafana dashboards and alert rules.
- Tenant-scoped reindex and audit-log views for tenant admins.
- Streaming investigation updates over SSE/WebSockets.
- Durable human-approval inbox with SLA/escalation policies.
- Per-tenant SSO/OIDC and SCIM.
- Kubernetes manifests/Helm chart.
- Hybrid search + reranking for pgvector.
- Multi-agent investigation with explicit hand-off contracts.
- Audit-log retention, export, and tamper-evident hashing.

---

Built as a learning and portfolio project demonstrating the integration of AI,
Retrieval-Augmented Generation, policy-controlled automation, agentic
investigation, multi-tenancy, and production-grade observability in a modern
incident-response platform.
