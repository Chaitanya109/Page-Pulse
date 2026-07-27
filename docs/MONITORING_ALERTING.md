# Monitoring Strategy & Alerting

## 1. What we emit

### Structured logs (every request)
Each request produces at least one `http_request` access-log line
(from `RequestIDMiddleware`) with:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "logger": "pagepulse.access",
  "message": "http_request",
  "request_id": "...",
  "method": "POST",
  "path": "/api/v1/audit",
  "status_code": 200,
  "duration_ms": 142.3,
  "client_ip": "..."
}
```

Plus domain-specific lines from the service layer:
`audit_completed`, `audit_cache_hit`, `audit_timeout`,
`audit_connect_error`, `cache_get_failed`, `cache_set_failed`,
`handled_application_error`, `unhandled_exception`.

Because every line is a single JSON object, no custom parser is
needed — ship stdout directly to CloudWatch Logs, Datadog Agent,
Loki (via Promtail), or the ELK stack, and index on `request_id`,
`status_code`, `path`, and `error_code`.

### `/health` endpoint
Reports `status` (`ok`/`degraded`) and per-component status
(currently: `cache`). Poll this from your uptime checker and from
Kubernetes/Render/Railway liveness+readiness probes.

### Rate-limit headers
SlowAPI emits `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and
`Retry-After` on every rate-limited response — visible to clients
and gateways for their own backoff logic, and scrapeable from access
logs.

## 2. Metrics to derive (from logs, or via a metrics exporter)

Page Pulse doesn't ship a Prometheus exporter in this exercise, but
every metric below is directly derivable from the structured logs
above, and is the recommended first addition (`prometheus-fastapi-
instrumentator` or a small custom middleware) for a real production
rollout:

| Metric | Source | Why it matters |
|---|---|---|
| `http_requests_total{path,status_code}` | access log | Traffic volume & error rate by endpoint |
| `http_request_duration_ms` (p50/p95/p99) | access log `duration_ms` | Latency SLA tracking |
| `audit_upstream_duration_ms` | `audit_completed.response_time_ms` | Isolates target-side latency from our own overhead |
| `audit_cache_hit_ratio` | `audit_cache_hit` count / total audits | Cache effectiveness; low ratio → review TTL/traffic pattern |
| `concurrency_limiter_rejections_total` | `ConcurrencyLimitExceededError` (503) count | Signals under-provisioned concurrency |
| `rate_limit_rejections_total` | 429 count | Signals abusive client or too-strict a limit |
| `upstream_error_rate{code}` | `UPSTREAM_TIMEOUT` / `UPSTREAM_CONNECTION_ERROR` count | Distinguishes "the internet is having a bad day" from "we have a bug" |
| `cache_backend_errors_total` | `cache_get_failed` / `cache_set_failed` | Redis cache health, independent of `/health` polling cadence |
| `unhandled_exceptions_total` | `unhandled_exception` count | Should be ~zero; any nonzero rate pages someone |

## 3. Dashboards (recommended layout)

1. **Golden Signals** — request rate, error rate (4xx vs 5xx split),
   p50/p95/p99 latency, saturation (concurrency limiter in-flight /
   capacity).
2. **Dependency Health** — Redis cache hit ratio, Redis
   cache/rate-limit error rates, `/health` component status over
   time.
3. **Upstream Behavior** — breakdown of audited targets' status
   codes, timeout rate, connection-error rate — this tells you
   whether a spike in errors is "our service" or "the websites people
   are auditing."

## 4. Alerting rules

| Alert | Condition | Severity | Rationale |
|---|---|---|---|
| High 5xx rate | `5xx rate > 5%` over 5 min | Page | Likely our bug or Redis/network outage, not target-site behavior (5xx here means *our* handling, not the audited site's status code, which is reported inside a 200) |
| Health degraded | `/health` reports `degraded` for > 2 min | Page | Cache dependency down — service still up, but slower and worth investigating |
| Concurrency saturation | `503 rate > 10%` over 5 min | Warn → Page if sustained > 15 min | Either a genuine traffic spike (scale up) or a stuck/slow upstream tying up slots |
| Rate-limit storage errors | `cache_backend_errors_total` (DB1) > 0 for > 5 min | Warn | Rate limiting is failing open; not urgent alone, but should not persist |
| Unhandled exception spike | `unhandled_exceptions_total` rate > 0.1% of requests | Page | Should be near-zero; any sustained rate indicates a real bug |
| p99 latency regression | `p99 > 2x 7-day baseline` for 10 min | Warn | Early signal of upstream slowness or resource contention before it becomes an incident |
| Elevated upstream timeout rate | `UPSTREAM_TIMEOUT rate > 20%` over 15 min | Info/Warn | Usually reflects target-site behavior, not our bug — informational unless sustained and broad-based (suggesting our own network egress issue) |

**Notes on severity**: "Page" alerts should wake someone up; "Warn"
alerts go to a team channel for business-hours triage. The
distinction above intentionally keeps target-site misbehavior
(timeouts, non-2xx from audited sites) out of the paging path — that
is expected, routine input to this service, not an incident.

## 5. Correlation & debugging workflow

Every response carries `X-Request-ID` (and the JSON body includes
`request_id`). Support workflow: take the id from a user report or
error toast, grep/query logs for that id, and see the full lifecycle
of that one request — validation outcome, cache hit/miss, upstream
timing, and final status — in one correlated trace, without a
distributed tracing system required for a service this size. If/when
Page Pulse grows multiple internal services, propagate the same
`X-Request-ID` (already read from inbound headers, not just
generated) into OpenTelemetry trace context for full distributed
tracing.
