# Deployment Guide

## 1. Local development (no Docker)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # adjust as needed

# Redis is required for cache + rate limiting; run it locally:
docker run -d --name redis -p 6379:6379 redis:7-alpine

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000/docs` for interactive Swagger UI.

Run the test suite:

```bash
pytest -v --cov=app --cov-report=term-missing
ruff check app tests
mypy app --ignore-missing-imports
```

## 2. Local development with Docker Compose (recommended)

```bash
docker compose up --build
```

This starts both the app (port `8000`) and a Redis instance, wired
together via `docker-compose.yml`. Tear down with
`docker compose down` (add `-v` to also drop the Redis volume).

## 3. Building the production image standalone

```bash
docker build -t page-pulse:latest .
docker run -d --name page-pulse \
  -p 8000:8000 \
  -e REDIS_URL=redis://<your-redis-host>:6379/0 \
  -e RATE_LIMIT_STORAGE_URL=redis://<your-redis-host>:6379/1 \
  -e ENVIRONMENT=production \
  -e LOG_LEVEL=INFO \
  page-pulse:latest
```

## 4. Deploying to Render

Render can deploy directly from this repository using a Docker
runtime, plus its managed Redis add-on.

**Steps:**

1. **Create a Redis instance**: Render dashboard → *New* → *Redis*.
   Note the internal connection string (Render provides a private
   URL for services in the same region/project).
2. **Create a Web Service**: *New* → *Web Service* → connect this
   Git repository.
   - **Runtime**: Docker (Render auto-detects the `Dockerfile`).
   - **Region**: same as your Redis instance, to minimize latency.
   - **Instance type**: Start with the smallest paid tier that meets
     the concurrency sizing in `SCALING_STRATEGY.md` (roughly
     0.5 vCPU / 512Mi is sufficient at 10k audits/day).
   - **Health check path**: `/health` (Render pings this to decide
     readiness during deploys — this is what makes rollout failures
     auto-abort, per `ROLLBACK_STRATEGY.md`).
3. **Environment variables** (Render dashboard → Environment):

   | Key | Value |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `LOG_LEVEL` | `INFO` |
   | `LOG_JSON` | `true` |
   | `REDIS_URL` | `<Render Redis internal URL>/0` |
   | `RATE_LIMIT_STORAGE_URL` | `<Render Redis internal URL>/1` |
   | `CACHE_ENABLED` | `true` |
   | `RATE_LIMIT_ENABLED` | `true` |
   | `MAX_CONCURRENT_AUDITS` | `25` |
   | `REQUEST_TIMEOUT_SECONDS` | `8.0` |

4. **Scaling**: Render's dashboard lets you set a fixed replica count
   or (on relevant plans) autoscale by CPU. Start at 2 replicas
   minimum per the availability guidance in `SCALING_STRATEGY.md`.
5. **Deploys**: Render auto-deploys on push to the connected branch
   by default; each deploy is health-gated (see `ROLLBACK_STRATEGY.md`
   §2-3 for the rollback procedure specific to Render).

## 5. Deploying to Railway

Railway also builds directly from the `Dockerfile` and offers a
one-click managed Redis plugin.

**Steps:**

1. **Create a new project** from this GitHub repository in the
   Railway dashboard (*New Project* → *Deploy from GitHub repo*).
   Railway detects the `Dockerfile` automatically.
2. **Add Redis**: within the same project, *New* → *Database* →
   *Add Redis*. Railway injects connection variables automatically
   (typically `REDIS_URL` or similar — check the plugin's *Connect*
   tab for the exact variable name and reference it via Railway's
   variable-reference syntax, e.g. `${{Redis.REDIS_URL}}`).
3. **Configure environment variables** on the web service (Settings →
   Variables):

   | Key | Value |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `LOG_LEVEL` | `INFO` |
   | `LOG_JSON` | `true` |
   | `REDIS_URL` | `${{Redis.REDIS_URL}}/0` (adjust to the plugin's actual variable name) |
   | `RATE_LIMIT_STORAGE_URL` | `${{Redis.REDIS_URL}}/1` |
   | `CACHE_ENABLED` | `true` |
   | `RATE_LIMIT_ENABLED` | `true` |
   | `MAX_CONCURRENT_AUDITS` | `25` |
   | `PORT` | Railway sets this automatically; the Dockerfile's `CMD`
     binds to `0.0.0.0:8000` — if Railway's injected `PORT` differs,
     override the start command to
     `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
4. **Health checks**: Railway → Settings → Health Check Path →
   `/health`. This gates deploys the same way as Render's check.
5. **Scaling**: Railway's *Settings → Resources* lets you adjust
   replica count and instance size. Start at 2 replicas.
6. **Deploys**: Railway auto-deploys on push by default; failed
   health checks prevent the new deploy from receiving traffic,
   matching the rollback behavior described in
   `ROLLBACK_STRATEGY.md`.

## 6. Deploying to Kubernetes (reference, for completeness)

Not the primary target platform for this exercise, but since the
service is a standard stateless container, a minimal reference
manifest shape is:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: page-pulse
spec:
  replicas: 3
  selector:
    matchLabels: { app: page-pulse }
  template:
    metadata:
      labels: { app: page-pulse }
    spec:
      containers:
        - name: page-pulse
          image: page-pulse:latest
          ports: [{ containerPort: 8000 }]
          envFrom:
            - secretRef: { name: page-pulse-secrets }
          readinessProbe:
            httpGet: { path: /health, port: 8000 }
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /health, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 20
          resources:
            requests: { cpu: "250m", memory: "256Mi" }
            limits: { cpu: "500m", memory: "512Mi" }
```

Rollback: `kubectl rollout undo deployment/page-pulse` (see
`ROLLBACK_STRATEGY.md`).

## 7. Required environment variables (all platforms)

See `.env.example` for the full list with defaults. The only values
that **must** be set for a real deployment (no safe default):

- `REDIS_URL` — audit-result cache backend.
- `RATE_LIMIT_STORAGE_URL` — rate-limit counter backend.
- `ENVIRONMENT` — set to `production` so logs/behavior match
  production expectations (e.g., `LOG_JSON=true`).

Everything else has a sane default suitable for a small production
deployment and can be tuned per `SCALING_STRATEGY.md`.
