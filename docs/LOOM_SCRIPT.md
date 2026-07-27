# Loom Walkthrough Script

Target length: ~8-10 minutes. Timestamps are approximate guidance,
not strict cues.

---

## 0:00 - 0:45 — Intro

> "Hi, this is my submission for the Page Pulse SDE qualification
> task — a production-grade URL Audit Service built with FastAPI,
> Redis, httpx, and SlowAPI. In this walkthrough I'll cover the
> architecture, show the service running end-to-end, walk through
> the test suite, and touch on the key production-readiness
> decisions: caching, rate limiting, concurrency control, and
> observability."

*(Screen: show the project folder structure in an editor.)*

## 0:45 - 2:00 — Architecture overview

*(Screen: open `docs/ARCHITECTURE.md`, show the Mermaid diagrams
rendered.)*

> "Page Pulse follows clean architecture: routes are thin, the
> `AuditService` holds all business logic and depends only on
> injected interfaces — an httpx client, a Redis cache, and a
> concurrency limiter — never constructing them itself. That's what
> lets the test suite substitute mocks without touching the service
> code at all.
>
> Every request flows through: request-ID middleware, CORS, SlowAPI
> rate limiting, URL validation and an SSRF guard, an optional cache
> lookup, a concurrency-gated live fetch, then a cache write and
> response."

## 2:00 - 3:00 — SSRF guard and validation (a security highlight)

*(Screen: open `app/services/url_validator.py`.)*

> "Since this service fetches arbitrary caller-supplied URLs on the
> server's behalf, it's a textbook SSRF vector. I resolve the
> hostname via DNS at request time — not just inspecting the URL
> string — and reject anything that lands in a private, loopback,
> link-local, or reserved IP range. This also catches DNS-rebinding
> style attacks, where a public-looking hostname resolves to an
> internal IP."

## 3:00 - 4:30 — Running it locally

*(Screen: terminal.)*

```bash
docker compose up --build
```

> "This starts the app plus Redis together. Once it's up..."

*(Screen: browser, navigate to `http://localhost:8000/docs`.)*

> "...here's the auto-generated Swagger UI. Let's audit a real URL."

*(Trigger `POST /api/v1/audit` with `{"url": "https://example.com"}`
via the Swagger 'Try it out' button.)*

> "Notice the response: status code, timing, redirect count, content
> metadata, and a breakdown of which common security headers the
> target sends. And if I run the exact same request again..."

*(Run it a second time.)*

> "...`from_cache` flips to true — served from Redis, no second
> outbound fetch."

## 4:30 - 5:30 — Error handling and structured errors

*(Screen: trigger a request with an invalid or private-network URL,
e.g. `http://127.0.0.1/`.)*

> "Every error — validation failure, SSRF block, upstream timeout,
> rate limit — comes back in the same structured JSON envelope with
> an error code, a human message, and a request id for support
> correlation. Nothing is an unhandled stack trace leaking to the
> client."

## 5:30 - 7:00 — Test suite

*(Screen: terminal.)*

```bash
pytest -v --cov=app --cov-report=term-missing
```

> "44 tests, unit and integration, 93% coverage. Unit tests use
> `respx` to mock the httpx transport and `fakeredis` for Redis, so
> they run in milliseconds with no real network or Redis dependency.
> Integration tests exercise the actual FastAPI app end-to-end via
> `TestClient`.
>
> I'll be honest about something here: while building this, I hit a
> real bug — combining Python's postponed annotation evaluation with
> SlowAPI's rate-limit decorator broke FastAPI's body-parameter
> detection, and every audit request started failing with a 422. I
> caught that specifically *because* I ran the tests rather than just
> trusting the code looked right — that's detailed in the AI Usage
> Statement, along with everything else that was actually verified
> versus just generated."

*(Screen: `ruff check app tests` and `mypy app` — show clean output.)*

> "Lint and type-checking are both clean, and both run in CI."

## 7:00 - 8:00 — CI/CD and deployment

*(Screen: `.github/workflows/ci.yml`.)*

> "CI runs lint and type-check, then the test matrix against a real
> Redis service container on two Python versions, then builds and
> smoke-tests the Docker image itself. The Dockerfile is a
> multi-stage build running as a non-root user.
>
> Deployment guides are included for Render and Railway — both
> platforms build directly from this Dockerfile and support the
> `/health` endpoint as a rollout gate, which is what makes rollback
> effectively automatic on a failed deploy."

## 8:00 - 9:00 — Scaling and production considerations

*(Screen: `docs/SCALING_STRATEGY.md`, scroll through the capacity
table.)*

> "For the target load — 10,000 audits a day, 500 concurrent users —
> I worked through the actual arrival-rate math rather than just
> picking round numbers: that translates to roughly 10-15 requests
> per second at peak and 25-50 truly concurrent in-flight audits,
> which sizes to 3-4 small replicas at 25 concurrent audits each.
> The failure-mode analysis and monitoring docs cover what happens
> when Redis goes down, when a target site times out, and what
> alerts should page a human versus just go to a Slack channel."

## 9:00 - 9:30 — Wrap-up

> "That's Page Pulse — the full repo, all documentation, CI
> configuration, and an honest account of what was and wasn't
> independently verified are all included. Thanks for watching."

---

**Recording checklist:**
- [ ] Docker Compose stack running before recording starts (avoid
      dead air waiting for build).
- [ ] Have `docs/ARCHITECTURE.md` Mermaid diagrams pre-rendered
      (e.g., in a Markdown preview or GitHub's own renderer).
- [ ] Terminal font size large enough to read on a recording.
- [ ] Pre-run `pytest` once before recording so the module cache is
      warm and the on-camera run is fast.
