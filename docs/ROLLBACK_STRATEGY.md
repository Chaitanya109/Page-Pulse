# Rollback Strategy

## 1. Why rollback is low-risk for Page Pulse

The service is **fully stateless**: no local disk state, no
in-memory session data that matters across requests, and no
database migrations to reverse. All shared state (cache entries,
rate-limit counters) lives in Redis and is either TTL'd (cache) or
naturally self-healing (rate-limit windows expire). This means:

- Rolling back is just "run the previous container image again" —
  no data backfill, no schema downgrade, no cache invalidation
  required.
- Old and new versions can safely run **side by side** during a
  rollout, since neither version depends on the other's in-memory
  state, and both read/write the same simple Redis key formats
  (versioned by prefix if a cache-format change is ever introduced —
  see §4).

## 2. Deployment strategy

**Rolling deployment with health-gated replica replacement**
(the default on Render, Railway, and Kubernetes):

1. New replicas are started running the new image.
2. Each new replica must pass `/health` (readiness) before receiving
   traffic.
3. Old replicas are drained (stop receiving new requests, finish
   in-flight ones) and terminated only after enough new replicas are
   healthy to maintain capacity.
4. If new replicas fail to become healthy within a timeout, the
   platform automatically halts the rollout, leaving old replicas
   serving 100% of traffic — this **is** the automatic rollback path
   on Render/Railway for a bad deploy that fails its health check.

## 3. Manual rollback procedure

If a deploy passes health checks but exhibits a behavioral
regression (elevated error rate, latency regression, wrong output)
that isn't caught by `/health`:

1. **Detect** — via the alerting rules in `MONITORING_ALERTING.md`
   (elevated 5xx rate, latency regression) or a manual report.
2. **Decide** — if the blast radius is broad or user-facing, roll
   back immediately rather than attempting a forward-fix under
   pressure.
3. **Roll back**:
   - *Render*: redeploy the previous successful deploy from the
     Render dashboard's deploy history (one click), or `git revert`
     the merge commit and push — Render's auto-deploy picks it up.
   - *Railway*: same pattern — redeploy a previous build from the
     deployments list, or revert and push.
   - *Kubernetes*: `kubectl rollout undo deployment/page-pulse`.
   - *Docker Compose (single host)*: `docker compose pull && docker
     compose up -d` after re-tagging the previous image as `latest`,
     or pin `image: page-pulse:<previous-sha>` in the compose file.
4. **Verify** — confirm `/health` is `ok` and error-rate/latency
   metrics return to baseline within a few minutes.
5. **Postmortem** — since nothing here is destructive (no data
   loss possible from a bad deploy), the postmortem can focus
   entirely on the code/config regression itself, not on data
   recovery.

## 4. The one case that needs care: cache format changes

If a future change alters the *shape* of the cached `AuditResult`
JSON (e.g., renaming a field), an old replica reading a new replica's
cache entry (or vice versa) during a rolling deploy could hit a
`pydantic.ValidationError` on cache read. Two safe patterns, either
is sufficient:

- **Prefer additive changes** — add new optional fields with
  defaults; never rename or remove a field in the same release that
  also still has old replicas running.
- **Version the cache key prefix** — bump
  `CACHE_KEY_PREFIX` (e.g. `pagepulse:audit:v2:`) alongside a
  breaking schema change, so old and new versions simply miss each
  other's cache entries (a temporary cache-hit-rate dip, not an
  error) instead of colliding.

`AuditCache.get` already treats a JSON-decode failure as a cache miss
(logs a warning, returns `None`) rather than raising — this was a
deliberate defensive choice precisely to make cache-format skew
during a rollout non-fatal. A `pydantic.ValidationError` on the
*decoded* dict (schema mismatch, not JSON-parse failure) is the one
gap the versioned-prefix practice above is meant to close.

## 5. Database / migration rollback

Not applicable — Page Pulse has no database. If a future feature
(e.g., the bulk-audit job queue described in the Queue Strategy
section of `ARCHITECTURE.md`) adds a Postgres-backed job table, this
section should be revisited to include standard migration-rollback
practice (`alembic downgrade`, backward-compatible migrations
deployed one release ahead of the code that requires them).

## 6. Rollback checklist (quick reference)

- [ ] Confirm the regression is deploy-related (check the deploy
      timestamp against the metric/error onset).
- [ ] Roll back via platform redeploy or `kubectl rollout undo`.
- [ ] Confirm `/health` returns `ok` on the rolled-back replicas.
- [ ] Confirm error rate / latency return to baseline.
- [ ] If a cache-format change was involved, confirm the cache key
      prefix was versioned (no manual cache flush should ever be
      required).
- [ ] File a postmortem; no data-recovery steps needed (stateless
      service).
