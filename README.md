# AI Incident Response System

An AI-powered Incident Response Platform that automatically receives alerts from monitoring systems, analyzes incidents using Google Gemini with Retrieval-Augmented Generation (RAG), executes automated remediation workflows, and provides complete observability through Prometheus and Grafana.

The project demonstrates how modern AI can be integrated into an incident management pipeline to reduce manual effort, improve response time, and provide context-aware recommendations using organization-specific runbooks.

---

# Features

* 🚨 Grafana webhook integration
* 🔍 Fingerprint-based incident deduplication
* 📊 Incident lifecycle management
* 🤖 AI-powered incident analysis with Google Gemini
* 📚 Retrieval-Augmented Generation (RAG)
* ⚡ Background processing with Celery
* 🔄 Redis-backed task queue
* 🛠 Configurable automation engine
* 📈 Prometheus metrics
* 📉 Grafana dashboards
* 🗄 PostgreSQL persistence
* 📜 Automation execution logs
* 📖 Explainable AI with retrieved knowledge sources

---

# Tech Stack

## Backend

* FastAPI
* SQLAlchemy
* PostgreSQL
* Alembic
* Pydantic

## AI

* Google Gemini 2.5 Flash
* Sentence Transformers
* ChromaDB

## Background Processing

* Celery
* Redis

## Monitoring

* Grafana
* Prometheus
* Node Exporter

---

# System Architecture

```text
                                ┌─────────────────────┐
                                │    Prometheus       │
                                │ Collects Metrics    │
                                └─────────┬───────────┘
                                          │
                                          ▼
                                ┌─────────────────────┐
                                │      Grafana        │
                                │ Dashboards & Alerts │
                                └─────────┬───────────┘
                                          │
                                   Webhook Notification
                                          │
                                          ▼
                            ┌─────────────────────────────┐
                            │       FastAPI API           │
                            │     Webhook Endpoints       │
                            └─────────────┬───────────────┘
                                          │
                                          ▼
                           Fingerprint Deduplication
                                          │
                     ┌────────────────────┴───────────────────┐
                     │                                        │
              Existing Incident                       New Incident
                     │                                        │
             Update Lifecycle                     Create Incident
                     │                                        │
                     └────────────────────┬───────────────────┘
                                          ▼
                                 Celery Background Task
                                          │
                 ┌────────────────────────┴─────────────────────┐
                 ▼                                              ▼
          RAG Retrieval                                  AI Analysis
                 │                                              │
          ChromaDB Vector DB                           Google Gemini
                 ▲                                              │
                 │                                              │
        Internal Runbooks (.md)                                │
                 └────────────────────────┬─────────────────────┘
                                          ▼
                              Summary • Severity • Recommendation
                                          │
                                          ▼
                                Automation Engine
                                          │
              ┌──────────────┬──────────────┬──────────────┐
              ▼              ▼              ▼
         Log Action     Execute Script   HTTP Webhook
              │              │              │
              └──────────────┴──────────────┘
                             │
                             ▼
                        PostgreSQL
                             │
                             ▼
                     Prometheus Metrics
                             │
                             ▼
                      Grafana Dashboard
```

---

# Project Structure

```text
app/
├── ai/
├── automation/
├── core/
├── database/
├── monitoring/
├── pipelines/
├── rag/
├── repositories/
├── schemas/
├── services/
├── webhooks/
└── main.py

knowledge/
├── memory.md
├── cpu.md
├── disk.md
└── postgres.md
```

---

# Workflow

1. Grafana detects an infrastructure issue.
2. Grafana sends a webhook notification.
3. FastAPI validates and parses the webhook.
4. Incident fingerprint is checked.
5. Existing incidents are updated or new incidents are created.
6. Celery starts background processing.
7. Relevant runbooks are retrieved from ChromaDB.
8. Gemini analyzes the incident using retrieved context.
9. AI generates:

   * Summary
   * Severity
   * Recommendation
10. Automation rules execute.
11. Results are stored in PostgreSQL.
12. Prometheus collects metrics.
13. Grafana visualizes the entire pipeline.

---

# Incident Lifecycle

```text
OPEN
 │
 ├── AI Analysis
 │
 ├── Automation
 │
 ▼
RESOLVED
 │
 ▼
CLOSED
```

Analysis status and automation status are tracked independently from the incident lifecycle.

---

# AI Analysis

Google Gemini analyzes every incident and produces structured JSON containing:

* Incident summary
* Severity classification
* Actionable recommendation

The application validates the AI response using a strict schema before storing the result.

---

# Retrieval-Augmented Generation (RAG)

The project uses RAG to ground AI responses in internal operational knowledge.

Workflow:

```text
Incident
    │
    ▼
Embedding
    │
    ▼
ChromaDB Similarity Search
    │
    ▼
Relevant Runbooks
    │
    ▼
Gemini
    │
    ▼
Recommendation
```

Retrieved runbook identifiers are stored alongside each incident to improve explainability.

---

# Automation Engine

Automation rules execute after AI analysis completes.

Supported actions:

* Log incident information
* Execute scripts
* Send HTTP webhooks

Each execution records:

* Action name
* Status
* Execution duration
* Success or failure
* Error details

---

# Background Processing

Celery executes long-running tasks asynchronously, including:

* AI analysis
* Automation execution

Redis acts as the Celery broker, ensuring webhook requests return immediately while processing continues in the background.

---

# Monitoring & Metrics

The application exports Prometheus metrics covering:

## Incident Metrics

* Total incidents
* Incident severity
* Incident lifecycle status
* Resolved incidents

## AI Metrics

* Analysis started
* Analysis completed
* Analysis failed
* Analysis duration

## Automation Metrics

* Automation started
* Automation completed
* Automation failed
* Execution duration

## Webhook Metrics

* Requests received
* Successful requests
* Failed requests

---

# Redis Metrics

Redis is also used to maintain lightweight application counters.

Tracked counters include:

* Total incidents
* AI analyses
* Successful AI analyses
* Failed AI analyses
* Automation executions
* Successful automations
* Failed automations
* Webhook successes
* Webhook failures

Metric Flow:

```text
Application Event
      │
      ▼
Redis Counter
      │
      ▼
Application Metrics
      │
      ▼
Prometheus
      │
      ▼
Grafana
```

---

# External Integrations

| Service       | Purpose                           |
| ------------- | --------------------------------- |
| Grafana       | Alert generation and dashboards   |
| Prometheus    | Metrics collection                |
| Node Exporter | Host metrics                      |
| Google Gemini | AI-powered analysis               |
| ChromaDB      | Vector database for RAG           |
| PostgreSQL    | Persistent storage                |
| Redis         | Celery broker and metric counters |
| Celery        | Background task execution         |

---

# Installation

Clone the repository

```bash
git clone https://github.com/<username>/ai-incident-response-system.git

cd ai-incident-response-system
```

Create a virtual environment

```bash
uv venv
```

Activate it

Linux/macOS

```bash
source .venv/bin/activate
```

Windows

```powershell
.venv\Scripts\activate
```

Install dependencies

```bash
uv sync
```

Run migrations

```bash
alembic upgrade head
```

Index the knowledge base

```bash
python -m app.rag.ingest
```

Start the application

```bash
uv run uvicorn app.main:app --reload
```

Interactive API documentation:

```text
http://localhost:8000/docs
```

---

# Docker (Planned)

The project is designed to be containerized using Docker Compose with services for:

* FastAPI
* PostgreSQL
* Redis
* Celery Worker
* Prometheus
* Grafana

---

# Future Improvements

* React dashboard
* Slack / Microsoft Teams notifications
* Email notifications
* Multi-provider LLM support
* Kubernetes deployment
* Authentication & Authorization
* Advanced automation workflows
* Role-based access control
* Incident timeline visualization

---

# License

This project is licensed under the MIT License.

---

# Author

Developed as a portfolio and learning project demonstrating the integration of Artificial Intelligence, Retrieval-Augmented Generation, Automation, and Observability into a modern incident response platform.
