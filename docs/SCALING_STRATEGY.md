# Scaling Strategy

Target load: **10,000 audits/day** sustained, **500 concurrent
users** at peak, with a defined SLA (see §5).

## 1. Translating daily volume into request rates

10,000 audits/day is not evenly spread — real traffic is bursty
(business-hours skew, occasional batch-triggered spikes). Sizing
against the average alone under-provisions for the peak.

| Assumption | Value |
|---|---|
| Daily volume | 10,000 audits |
| Average rate (24h) | ~0.12 req/s (~7/min) |
| Business-hours concentration (8h window, 70% of volume) | ~0.24 req/s (~14.6/min) |
| Peak burst multiplier (typical for bursty API traffic) | 5–10x average |
| **Design target peak** | **~10–15 req/s sustained, bursts to ~30 req/s** |

500 concurrent *users* does not mean 500 concurrent *in-flight audit
requests* — a user issues a request, waits ~1-3s (mostly upstream
fetch time), and issues the next one. Modeling this as an M/M/c-style
arrival process: 500 users each issuing a request roughly every
10-20s of active use translates to **25-50 concurrent in-flight
requests** at any instant under realistic usage, not 500. Sizing for
500 truly simultaneous in-flight requests would be a ~10-20x
over-provision versus realistic behavior — the correct target is
concurrent *in-flight requests*, not concurrent *logged-in/active
users*, and this document sizes for both a realistic estimate and a
padded worst case.

## 2. Capacity plan

| Layer | Sizing decision | Rationale |
|---|---|---|
| **App replicas** | 3-4 replicas minimum (production), each `MAX_CONCURRENT_AUDITS=25` | 3-4 replicas × 25 = 75-100 concurrent in-flight audits — comfortably covers the realistic 25-50 estimate with headroom for the padded worst case, and gives N+1 redundancy for rolling deploys |
| **Per-replica concurrency limit** | `MAX_CONCURRENT_AUDITS=25` | Each in-flight audit holds one outbound TCP connection + one async task; 25 is conservative for a single small container (512Mi-1Gi RAM, 0.5-1 vCPU) — see §3 for the httpx connection-pool math |
| **httpx connection pool** | `max_connections = 2x MAX_CONCURRENT_AUDITS`, `max_keepalive = MAX_CONCURRENT_AUDITS` | Matches the concurrency limiter so the pool is never the bottleneck ahead of the semaphore |
| **Redis** | Single managed instance (e.g., Render Redis, Railway Redis, or AWS ElastiCache `cache.t3.micro`/`small`) | At 10-15 req/s with a healthy cache-hit ratio, Redis load is trivial (a few hundred ops/sec at most) — this is not the bottleneck at this scale. Redis Cluster is not warranted until traffic is an order of magnitude higher. |
| **Rate limit** | `RATE_LIMIT_AUDIT=10/minute` per client (default) | Tuned per API key/IP, not global — the global capacity plan above assumes many distinct clients, each individually rate-limited; revisit if a single high-volume partner needs a higher per-key limit |

## 3. Why 25 concurrent audits per replica

Each in-flight audit holds, for its duration (bounded by
`request_timeout_seconds`, default 8s worst case):
- One async task (~cheap; Python coroutines are lightweight)
- One pooled httpx connection
- Negligible memory (a few KB of response body metadata; full body
  is streamed and discarded unless needed for future features)

With `request_timeout_seconds=8s` as the worst case and Little's Law
(`concurrency = arrival_rate × service_time`): to sustain 15 req/s
system-wide with an average real-world audit latency of ~0.5-1s
(most target sites respond well under a second; the 8s figure is a
timeout ceiling, not a typical latency), required concurrency is
`15 × 0.75s ≈ 11` in-flight requests system-wide under steady state.
Setting per-replica capacity to 25 (with 3-4 replicas) provides
roughly 7-9x headroom over the steady-state estimate, absorbing
bursts and slow-target outliers without triggering the 503
load-shedding path under normal conditions.

## 4. Horizontal scaling triggers

Because the service is stateless, horizontal scaling is
straightforward — add replicas behind the platform's load balancer
(Render/Railway/Kubernetes all support this natively). Recommended
autoscaling signals:

| Signal | Scale-out trigger | Scale-in trigger |
|---|---|---|
| CPU utilization | > 65% sustained 5 min | < 30% sustained 15 min |
| `503` rate (concurrency saturation) | > 1% of requests over 5 min | N/A (scale-in shouldn't be latency-triggered) |
| p95 latency | > 2x baseline sustained 5 min | N/A |

Minimum replica count should stay at **2** even at lowest traffic, to
maintain availability during rolling deploys and single-node
failures (see Rollback Strategy).

## 5. SLA considerations

Proposed SLA targets for this workload profile:

| Metric | Target | Notes |
|---|---|---|
| **Availability** | 99.5% monthly | Achievable with 2+ replicas, health-checked rolling deploys, and Redis in a managed (auto-failover) configuration. 99.9%+ would require multi-region and is not warranted at this traffic scale. |
| **p50 latency** | < 500 ms | Dominated by target-site response time on a cache miss; cache hits return in low single-digit ms. |
| **p95 latency** | < 3 s | Bounded primarily by `request_timeout_seconds` (8s) as a ceiling; most real targets respond well under this. |
| **p99 latency** | < 8 s (= `request_timeout_seconds`) | By construction — no request should exceed the configured timeout, since it's enforced by httpx itself. |
| **Error budget (5xx from our service, excluding upstream-reported statuses)** | < 0.5% monthly | Distinguishes "Page Pulse's own bug/outage" 5xx from the *audited site's* status code (which is reported inside a `200` from our API's perspective — see Failure Mode Analysis FM-01/02). |

**What the SLA explicitly does not cover**: the responsiveness or
uptime of *target* websites being audited — a `200` response
reporting that a target returned `503` is Page Pulse operating
correctly, not an SLA breach. This distinction should be called out
explicitly in any customer-facing SLA document to avoid confusion.

## 6. Cost/scale trade-off notes

At this traffic tier (10k/day, low tens of req/s peak), the
dominant cost driver is compute replicas, not Redis or bandwidth.
3-4 small (0.5 vCPU / 512Mi-1Gi) replicas plus one small managed
Redis instance is sufficient — this is a "single small deployment
plus a managed cache" architecture, not one requiring a service
mesh, dedicated queueing infrastructure, or multi-region failover.
Revisit this document if traffic grows past ~100k audits/day or
5,000 truly concurrent in-flight requests, at which point the Queue
Strategy's bulk-audit worker pool (see `ARCHITECTURE.md` §5) and
Redis Cluster become worth evaluating.
