# Page Pulse

A production-grade **URL Audit Service** built with FastAPI, Redis,
httpx, and SlowAPI. Given a URL, it fetches it and reports status
code, response timing, redirect chain length, content metadata, and
the presence of common security response headers — with caching,
per-client rate limiting, bounded concurrency, SSRF protection, and
structured JSON logging built in from the start.

Built as the SDE qualification submission for the Digital Heroes Job
Task Kit.

## Quick start

```bash
docker compose up --build
```

Then open `http://localhost:8000/docs` for the interactive API docs,
or:

```bash
curl -X POST http://localhost:8000/api/v1/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Without Docker, see [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md#1-local-development-no-docker)
for a local virtualenv setup.

## Features

- ✅ URL validation (scheme allow-list, length limits) + an SSRF
  guard that resolves DNS and blocks private/loopback/reserved
  networks, including DNS-rebinding style attacks
- ✅ Independent connect/read timeouts on every outbound fetch
- ✅ Structured JSON error responses with a stable `error.code` per
  failure mode
- ✅ Bounded concurrency (async semaphore) that fails fast (`503`)
  under saturation instead of queuing unboundedly
- ✅ Configurable Redis-backed caching with TTL, fail-open on Redis
  outage
- ✅ Per-client rate limiting (SlowAPI + Redis), fail-open on storage
  outage
- ✅ Structured JSON logging correlated by request id
  (`X-Request-ID`, generated or propagated)
- ✅ `GET /health` reporting overall + per-dependency status
- ✅ `POST /api/v1/audit` — the core audit endpoint
- ✅ Auto-generated OpenAPI docs (`/docs`, `/redoc`)
- ✅ 44 unit + integration tests, 93% coverage, `respx`/`fakeredis`
  mocked — no real network/Redis required to run the suite
- ✅ GitHub Actions CI: lint → type-check → test matrix (Redis
  service container) → Docker build + smoke test
- ✅ Multi-stage, non-root Dockerfile + Docker Compose for local dev

## Project structure

```
page-pulse/
├── app/
│   ├── main.py                 # FastAPI app factory + lifespan wiring
│   ├── config.py               # Settings (env-driven)
│   ├── logging_config.py       # Structured JSON logging + request-id contextvar
│   ├── dependencies.py         # FastAPI DI providers
│   ├── api/routes/
│   │   ├── health.py            # GET /health
│   │   └── audit.py             # POST /api/v1/audit (+ rate limit)
│   ├── core/
│   │   ├── exceptions.py        # Exception hierarchy + JSON error handlers
│   │   ├── middleware.py        # Request-ID + access-log middleware
│   │   ├── concurrency.py       # Async semaphore-based limiter
│   │   ├── cache.py             # Redis-backed audit-result cache
│   │   └── rate_limit.py        # SlowAPI limiter construction
│   ├── models/schemas.py       # Pydantic request/response models
│   └── services/
│       ├── url_validator.py     # Structural validation + SSRF guard
│       └── audit_service.py     # Core business logic
├── tests/
│   ├── conftest.py              # Shared fixtures (fakeredis, respx, settings)
│   ├── unit/                    # Fast, isolated tests
│   └── integration/              # End-to-end tests via FastAPI TestClient
├── docs/                        # Full documentation set (see below)
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt / requirements-dev.txt
└── pyproject.toml               # ruff + mypy configuration
```

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Component diagram, sequence diagram (Mermaid), data flow, queue strategy, SOLID rationale |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | Full request/response spec for every endpoint and error code |
| [`docs/TECHNOLOGY_DECISION_RECORD.md`](docs/TECHNOLOGY_DECISION_RECORD.md) | Why FastAPI/httpx/Redis/SlowAPI/Pydantic, with alternatives considered |
| [`docs/FAILURE_MODE_ANALYSIS.md`](docs/FAILURE_MODE_ANALYSIS.md) | 9 failure modes: trigger, detection, mitigation, residual risk |
| [`docs/MONITORING_ALERTING.md`](docs/MONITORING_ALERTING.md) | Log schema, derivable metrics, dashboards, alerting rules |
| [`docs/ROLLBACK_STRATEGY.md`](docs/ROLLBACK_STRATEGY.md) | Deployment strategy, manual rollback per platform, cache-versioning safety |
| [`docs/SCALING_STRATEGY.md`](docs/SCALING_STRATEGY.md) | Capacity math for 10k audits/day, 500 concurrent users, SLA targets |
| [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md) | Local, Docker, Render, Railway, and Kubernetes deployment steps |
| [`docs/AI_USAGE_STATEMENT.md`](docs/AI_USAGE_STATEMENT.md) | What was AI-generated vs. independently verified |
| [`docs/LOOM_SCRIPT.md`](docs/LOOM_SCRIPT.md) | Walkthrough video script |

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v --cov=app --cov-report=term-missing
ruff check app tests
mypy app --ignore-missing-imports
```

All 44 tests run against `respx`-mocked HTTP responses and
`fakeredis` — no live network access or Redis instance required.

## Configuration

All configuration is environment-variable driven; see
[`.env.example`](.env.example) for the full list with defaults and
[`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md#7-required-environment-variables-all-platforms)
for which values must be set in a real deployment.

## License

MIT (or as specified by the Digital Heroes Job Task Kit submission
requirements).
