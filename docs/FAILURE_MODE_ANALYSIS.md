# Failure Mode Analysis

For each failure mode: **Trigger → Detection → Blast Radius → Mitigation
(built) → Residual Risk**.

---

## FM-01: Target URL is unreachable / connection refused

- **Trigger**: DNS resolves, but the target host actively refuses the
  TCP connection, or drops it mid-handshake.
- **Detection**: `httpx.ConnectError` raised from the outbound call.
- **Blast Radius**: Single request only.
- **Mitigation (built)**: Caught explicitly in `AuditService`, mapped
  to `UpstreamConnectionError` → HTTP `502 Bad Gateway` with a
  structured error body. The concurrency slot is released in a
  `finally` block regardless of outcome, so one bad target cannot
  leak capacity.
- **Residual Risk**: Low. The caller sees an accurate, actionable
  error.

## FM-02: Target URL is slow (approaching or exceeding timeout)

- **Trigger**: Target responds slower than `request_timeout_seconds`
  (default 8s) or the connect phase exceeds `connect_timeout_seconds`
  (default 3s).
- **Detection**: `httpx.TimeoutException`.
- **Blast Radius**: Single request, but a burst of slow targets can
  hold concurrency slots for up to the full timeout window.
- **Mitigation (built)**: Independent connect/read timeouts (not one
  combined timeout) so a slow-to-connect host fails fast at 3s rather
  than waiting the full 8s. Mapped to `UpstreamTimeoutError` → `504
  Gateway Timeout`. The concurrency limiter caps how many such slow
  requests can be in flight simultaneously.
- **Residual Risk**: Medium — a coordinated burst of slow targets
  (or a single very popular slow target being audited repeatedly)
  can still saturate the concurrency limit and cause `503`s for
  unrelated callers. Mitigated by cache (a slow target's *first*
  audit is slow; subsequent identical requests within the TTL are
  instant) and by tuning `max_concurrent_audits` relative to expected
  target latency.

## FM-03: Redis (cache) becomes unavailable

- **Trigger**: Redis process/network partition, OOM eviction,
  maintenance restart.
- **Detection**: `redis.exceptions.RedisError` on `get`/`set`/`ping`.
- **Blast Radius**: Service-wide, but degraded rather than down.
- **Mitigation (built)**: `AuditCache.get`/`set` catch `RedisError`
  and log a warning, returning a cache miss / no-op respectively —
  **the service continues serving live audits**, just without the
  speedup. `/health` reports `components.cache.status = "down"` so
  this is visible to monitoring without paging on its own.
- **Residual Risk**: Low functionally, medium operationally — if
  Redis stays down, every request becomes a live fetch, raising
  outbound request volume and latency. This is the expected,
  acceptable degradation mode; the residual risk is under-scaled
  `max_concurrent_audits` for a "no-cache" traffic pattern (see
  Scaling doc).

## FM-04: Redis (rate-limit storage) becomes unavailable

- **Trigger**: Same as FM-03, different Redis logical DB.
- **Detection**: SlowAPI's internal limiter-storage check.
- **Blast Radius**: Service-wide.
- **Mitigation (built)**: `Limiter(..., swallow_errors=True)` — a
  storage outage causes rate limiting to fail *open* (allow the
  request) rather than fail closed (reject everything) or crash.
- **Residual Risk**: Medium — during a rate-limit-storage outage, the
  service has no per-client throttling at all, relying solely on the
  concurrency limiter and target-side reachability to bound load.
  This is a deliberate choice (availability over strict fairness) but
  should be paired with alerting (see Monitoring doc) so the outage
  is short-lived.

## FM-05: SSRF — malicious or accidental internal-network target

- **Trigger**: Caller supplies a URL that resolves to a private,
  loopback, link-local, or reserved address (including via DNS
  rebinding, where a public-looking hostname resolves to a private
  IP at request time).
- **Detection**: `enforce_ssrf_guard` performs the DNS resolution and
  IP-range check synchronously, before any outbound request is made.
- **Blast Radius**: Would otherwise be service-wide (internal network
  exposure) if unmitigated.
- **Mitigation (built)**: Every resolved address for the hostname is
  checked against `ipaddress.*.is_private/is_loopback/is_link_local
  /is_reserved/is_multicast/is_unspecified`; any match raises
  `URLNotAllowedError` → `400`. This runs at request time (not just
  URL-string inspection), specifically to catch DNS rebinding.
- **Residual Risk**: Low-medium. A theoretical TOCTOU (time-of-check
  to time-of-use) gap exists between our resolution and httpx's own
  connection (an attacker-controlled DNS server could serve a public
  IP to our check and a private IP to httpx's own resolver
  moments later). Full closure requires resolving once and
  connecting to the resolved IP directly (pinning), which is a
  documented hardening follow-up, not yet implemented.

## FM-06: Concurrency limiter saturation (thundering herd)

- **Trigger**: A burst of audit requests exceeds
  `max_concurrent_audits` in-flight capacity simultaneously.
- **Detection**: `ConcurrencyLimiter.acquire()` sees the semaphore
  already locked.
- **Blast Radius**: New requests during the saturation window.
- **Mitigation (built)**: Fail-fast `503` (load shedding) instead of
  unbounded queuing, keeping accepted requests' latency predictable.
  Clients are expected to retry with backoff (standard for `503`).
- **Residual Risk**: Low. This is working as intended; the residual
  risk is choosing too low a `max_concurrent_audits` for real traffic
  (see Scaling doc for sizing guidance).

## FM-07: Malformed / oversized request body

- **Trigger**: Caller sends invalid JSON, a missing `url` field, or
  an excessively long URL string.
- **Detection**: Pydantic schema validation (`RequestValidationError`)
  or `URLValidationError` for length/scheme checks.
- **Blast Radius**: Single request.
- **Mitigation (built)**: Both are caught by dedicated exception
  handlers and returned as structured `422`/`400` JSON, never as an
  unhandled `500`.
- **Residual Risk**: Very low.

## FM-08: Unhandled exception anywhere in the stack

- **Trigger**: Any bug or unexpected library exception not covered by
  the specific handlers above.
- **Detection**: Global `Exception` handler in
  `register_exception_handlers`.
- **Blast Radius**: Single request (the process itself keeps running
  — FastAPI/Starlette isolate the exception to the request that
  raised it).
- **Mitigation (built)**: Caught, logged with full traceback
  (`logger.exception`), and returned as a generic `500` with **no
  internal details leaked** to the client — only a generic message
  and the request id for support correlation.
- **Residual Risk**: Low for security (no leakage); the actual bug
  still needs a human to look at the logged traceback and ship a fix.

## FM-09: Process crash / restart (deploy, OOM, node failure)

- **Trigger**: Any of the above.
- **Detection**: Kubernetes/Render/Railway readiness+liveness probes
  hitting `/health`; orchestrator-level restart counters.
- **Blast Radius**: In-flight requests on that replica are dropped;
  other replicas continue serving.
- **Mitigation (built)**: The service is fully stateless (all shared
  state lives in Redis) — any replica can be killed and restarted, or
  a fresh replica added, with zero data migration and no sticky
  sessions required. See Rollback Strategy for deploy-time specifics.
- **Residual Risk**: Low, assuming the orchestrator is configured
  with a sane restart policy and multiple replicas (single-replica
  deployments have an availability gap during restart — acceptable
  for a dev/staging environment, not for production SLA targets).
