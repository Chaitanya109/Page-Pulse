# Technology Decision Record (TDR)

Each decision below follows: **Context → Decision → Alternatives
considered → Consequences**.

---

## TDR-01: FastAPI as the web framework

**Context**: Need an async-native Python web framework with strong
request/response validation, auto-generated API docs, and low
boilerplate for a small-to-medium service.

**Decision**: FastAPI.

**Alternatives considered**:
- *Flask* — mature, huge ecosystem, but sync-first; async support is
  bolted on and less idiomatic. Would need Flask-async extensions to
  match FastAPI's native `async def` routes.
- *Django + DRF* — far more batteries (ORM, admin, auth) than this
  service needs; heavier startup cost and conceptual overhead for a
  single-purpose audit API.
- *Starlette directly* — FastAPI's own foundation; would save a thin
  layer of overhead but lose Pydantic-integrated validation and
  OpenAPI generation, both of which we use heavily.

**Consequences**: Free OpenAPI/Swagger docs from type hints, built-in
Pydantic validation, native `async def` throughout the request path
(important since the core operation is an outbound I/O-bound HTTP
call). Trade-off: FastAPI's dependency-injection style takes a little
onboarding for engineers coming from Flask/Django.

---

## TDR-02: httpx over requests/aiohttp for outbound fetches

**Context**: The audit's core operation is an outbound HTTP GET to an
arbitrary, caller-supplied URL, which must be async (to not block the
event loop) and support fine-grained timeout control.

**Decision**: httpx (`AsyncClient`).

**Alternatives considered**:
- *requests* — sync-only; would require running in a thread pool
  (`run_in_executor`), adding complexity and reducing concurrency
  headroom.
- *aiohttp* — also async-capable and mature, but httpx's API mirrors
  `requests` (lower learning curve) and has first-class, separate
  connect/read/write/pool timeout controls that map cleanly onto our
  `request_timeout_seconds` / `connect_timeout_seconds` settings.

**Consequences**: A single shared, connection-pooled `AsyncClient`
per process, sized via `httpx.Limits` to match the concurrency
limiter, avoiding per-request client construction overhead.

---

## TDR-03: Redis for both caching and rate-limit storage

**Context**: Need (a) a shared cache so repeated audits of the same
URL are fast, and (b) shared rate-limit counters that work correctly
across multiple replicas (an in-process cache/limiter would let each
replica give a client its own separate quota).

**Decision**: Redis, two logical databases (DB 0 for audit-result
cache, DB 1 for rate-limit counters) — logically separated so a
`FLUSHDB` on one never touches the other, while sharing a single
Redis deployment for operational simplicity at this scale.

**Alternatives considered**:
- *In-process (e.g. `cachetools`, in-memory dict)* — zero
  infrastructure, but breaks the moment there is more than one
  replica: cache hit rate craters and rate limits become
  per-replica instead of global.
- *Memcached* — fine for pure caching, but has no equivalent to
  Redis's atomic `INCR`/sliding-window primitives that SlowAPI's
  Redis storage backend relies on for rate limiting — would need a
  second technology just for limiting.
- *Postgres-backed cache/limiter* — durable, but far higher latency
  per operation than Redis for a cache that is explicitly ephemeral
  and best-effort.

**Consequences**: One more stateful dependency to run/monitor, but a
well-understood, cheap-to-operate one. Both the cache and the limiter
degrade gracefully (see Failure Mode Analysis) rather than taking the
whole service down if Redis is briefly unavailable.

---

## TDR-04: SlowAPI for rate limiting

**Context**: Need per-client rate limiting with pluggable storage
(Redis), FastAPI-native decorator syntax, and standard
`X-RateLimit-*` response headers.

**Decision**: SlowAPI.

**Alternatives considered**:
- *Hand-rolled middleware over `redis-py`* — full control, but
  reimplements sliding-window/fixed-window algorithms, retry-after
  computation, and header formatting that SlowAPI already provides
  and has tested.
- *API-gateway-level rate limiting (e.g., Kong, NGINX, cloud LB)* —
  a legitimate complementary layer for coarse, pre-application
  limiting, but doesn't give per-endpoint or per-API-key granularity
  as simply as an in-app decorator, and adds an infra dependency this
  service shouldn't assume.

**Consequences**: Rate limiting lives next to the route it protects
(`@limiter.limit(...)` on `audit_url`), is easy to reason about, and
reuses the same Redis instance already required for caching.

---

## TDR-05: Pydantic v2 + `pydantic-settings` for config and schemas

**Context**: Need runtime request/response validation and typed,
environment-driven configuration with sane defaults.

**Decision**: Pydantic v2 models for request/response schemas;
`pydantic-settings.BaseSettings` for configuration, sourced from
environment variables / `.env`.

**Alternatives considered**:
- *`os.environ` + manual parsing* — no validation, easy to typo an
  env var name and silently get a wrong default; no type coercion.
- *`dynaconf` / `python-decouple`* — capable config libraries, but
  Pydantic's tight integration with FastAPI (the same models power
  both settings and API schemas) reduces the total number of
  validation libraries in the stack to one.

**Consequences**: A single source of truth (`Settings`) for every
tunable, validated at process startup — a bad env var value (e.g. a
non-numeric timeout) fails fast at boot instead of causing a subtle
runtime bug.

---

## TDR-06: Structured JSON logging over plain-text logs

**Context**: Logs need to be machine-parseable for aggregation
(CloudWatch/Datadog/ELK/Loki) and must correlate every line for a
given request.

**Decision**: A custom `JSONFormatter` emitting one JSON object per
line, with a request id threaded through via `contextvars`.

**Alternatives considered**:
- *`structlog`* — a strong, popular choice; not used here only to
  keep the dependency footprint minimal for this exercise. The
  formatter here is intentionally small (~60 lines) and swappable for
  `structlog` without touching call sites, since all logging goes
  through the standard `logging` module's `extra={}` mechanism.
- *Plain-text logs* — human-friendly locally, but require a log
  parser (regex/grok) at the aggregation layer, and are lossy for
  structured fields like `duration_ms` or `error_code`.

**Consequences**: Every log line is `json.loads`-able. A
`PlainFormatter` is kept for local development ergonomics
(`LOG_JSON=false`).

---

## TDR-07: Docker multi-stage build, non-root runtime user

**Context**: Need a small, reproducible, secure production image.

**Decision**: Two-stage Dockerfile — a `builder` stage that compiles
wheels, and a slim `runtime` stage that installs only those wheels
and runs as an unprivileged `app` user.

**Alternatives considered**:
- *Single-stage build* — simpler Dockerfile, but ships build tools
  (`gcc`, headers) into the production image, increasing attack
  surface and image size for no runtime benefit.
- *Distroless base image* — smaller still and no shell at all, but
  complicates local debugging (`docker exec ... sh`) for this
  exercise; a reasonable follow-up hardening step for a real
  production rollout.

**Consequences**: Smaller image, no compiler toolchain in the
runtime layer, and a non-root user — directly addressing the most
common container security review findings.
