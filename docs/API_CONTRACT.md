# API Contract

Base URL (local): `http://localhost:8000`
Interactive docs: `GET /docs` (Swagger UI), `GET /redoc` (ReDoc),
raw schema at `GET /openapi.json`.

All responses are `application/json`. Every response — success or
error — includes an `X-Request-ID` response header for support
correlation.

---

## `GET /health`

Liveness/readiness check. No authentication required. Not rate
limited.

### Response `200 OK`

```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "production",
  "components": {
    "cache": {
      "status": "ok",
      "detail": null
    }
  }
}
```

`status` is `"ok"` only if every component is `"ok"`; otherwise
`"degraded"`. A `"degraded"` cache component means the service is
still serving requests, just without the caching speedup — see
`FAILURE_MODE_ANALYSIS.md` (FM-03).

---

## `POST /api/v1/audit`

Audits a single URL. **Rate limited** per client (default
`10/minute`; see Rate Limiting section below).

### Request body

```json
{
  "url": "https://example.com",
  "use_cache": true
}
```

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `url` | string | yes | — | Must be `http://` or `https://`. Max length 2048 chars (configurable). Private/loopback/reserved-network targets are rejected (SSRF guard). |
| `use_cache` | boolean | no | `true` | If `true`, a cached result (within TTL) may be returned instead of a live fetch. Set `false` to force a live audit. |

### Success response `200 OK`

```json
{
  "request_id": "3fa7c9e2-8b1e-4b0a-9b0f-2b6a1e9d4c11",
  "result": {
    "url": "https://example.com",
    "final_url": "https://example.com/",
    "status_code": 200,
    "is_reachable": true,
    "response_time_ms": 142.31,
    "redirect_count": 1,
    "content_type": "text/html; charset=UTF-8",
    "content_length_bytes": 1256,
    "server": "ECS",
    "security_headers": {
      "strict_transport_security": true,
      "content_security_policy": false,
      "x_content_type_options": true,
      "x_frame_options": false,
      "referrer_policy": true
    },
    "checked_at": "2026-07-25T10:15:30.123456+00:00",
    "from_cache": false
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `result.url` | string | The (normalized) URL that was requested. |
| `result.final_url` | string | URL after following redirects. |
| `result.status_code` | integer | HTTP status returned by the **target** site. |
| `result.is_reachable` | boolean | `true` if `status_code < 500`. A `404` is "reachable" (the server responded); a `503` is not. |
| `result.response_time_ms` | float | Wall-clock time for the live fetch. `0`-ish for cache hits is not implied — this reflects the *original* fetch time even when served from cache. |
| `result.redirect_count` | integer | Number of redirects followed (`0` if none). |
| `result.content_type` | string \| null | From the target's `Content-Type` header. |
| `result.content_length_bytes` | integer \| null | From the target's `Content-Length` header, if present and numeric. |
| `result.server` | string \| null | From the target's `Server` header. |
| `result.security_headers.*` | boolean | Presence (not validity/correctness) of each common security header. |
| `result.checked_at` | string (ISO-8601, UTC) | Timestamp of the underlying fetch (not necessarily "now" for a cache hit). |
| `result.from_cache` | boolean | `true` if this result was served from cache rather than a live fetch. |

### Error responses

All errors share this envelope:

```json
{
  "error": {
    "code": "URL_VALIDATION_ERROR",
    "message": "Human-readable summary.",
    "details": { "...optional structured context..." }
  },
  "request_id": "3fa7c9e2-8b1e-4b0a-9b0f-2b6a1e9d4c11",
  "path": "/api/v1/audit"
}
```

| HTTP Status | `error.code` | Meaning |
|---|---|---|
| `400` | `URL_NOT_ALLOWED` | URL resolves to a private/loopback/reserved network (SSRF guard). |
| `422` | `URL_VALIDATION_ERROR` | URL is empty, too long, or uses a disallowed scheme. |
| `422` | `REQUEST_VALIDATION_ERROR` | Request body failed schema validation (e.g., missing `url` field). |
| `429` | *(SlowAPI default body)* | Rate limit exceeded for this client. `Retry-After` header included. |
| `503` | `CONCURRENCY_LIMIT_EXCEEDED` | Service is at maximum audit concurrency; retry shortly. |
| `502` | `UPSTREAM_CONNECTION_ERROR` | Could not connect to (or otherwise communicate with) the target URL. |
| `504` | `UPSTREAM_TIMEOUT` | Target URL did not respond within the configured timeout. |
| `500` | `INTERNAL_ERROR` | Unexpected server error; logged internally with the same `request_id`. |

**Important distinction**: a target site returning `404` or `503`
is reported as a **`200`** from this API (inside `result.status_code`)
— that is a successful audit that *discovered* the target is
erroring. The error codes above (`UPSTREAM_TIMEOUT`,
`UPSTREAM_CONNECTION_ERROR`) mean *we* could not complete the audit
at all (no response to report), which is a different situation.

---

## Rate Limiting

- Identification: `X-API-Key` header if present, else source IP.
- Default limit: `10/minute` on `POST /api/v1/audit` (configurable
  via `RATE_LIMIT_AUDIT`).
- Response headers on every rate-limited route:
  `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
- On exceeding the limit: `429 Too Many Requests` with a
  `Retry-After` header indicating the number of seconds to wait.

## Request ID propagation

Send an `X-Request-ID` header to correlate a request with your own
systems' tracing — it will be echoed back verbatim. If omitted, the
service generates one (UUID4) and returns it the same way.
