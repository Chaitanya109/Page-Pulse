# AI Usage Statement

## Tool used

Claude (Anthropic), used as an AI pair-programmer / architecture
assistant for the full lifecycle of this submission: code
generation, test authoring, debugging, and documentation drafting.

## What the AI generated

- The complete application source (`app/`): configuration, logging,
  middleware, exception handling, caching, rate limiting, concurrency
  control, URL validation/SSRF guard, the audit service, Pydantic
  schemas, and FastAPI route wiring.
- The full test suite (`tests/`): unit tests for the URL validator,
  audit service, and cache; integration tests for the health and
  audit endpoints.
- Supporting infrastructure files: `Dockerfile`, `docker-compose.yml`,
  `requirements*.txt`, the GitHub Actions CI workflow, `pytest.ini`,
  and `pyproject.toml` (ruff/mypy configuration).
- All documentation under `docs/`, plus this `README.md`.

## What was verified, not just generated

Every claim of "working" in this submission was checked, not
assumed:

- The full test suite (44 tests) was **actually executed** in a real
  Python 3.12 virtual environment with real dependencies installed
  (`pytest`, `respx`, `fakeredis`) — not just written and assumed
  correct.
- **A real bug was found and fixed during this process**: combining
  Python's `from __future__ import annotations` with SlowAPI's
  rate-limit decorator broke FastAPI's ability to detect the request
  body parameter (it was silently reinterpreted as a query
  parameter), causing every audit request to fail with `422`. This
  was diagnosed by reproducing the failure, reading SlowAPI's source
  to understand the decorator's signature-inspection behavior, and
  fixing it — this is exactly the kind of integration issue that
  only surfaces by actually running the code.
- `ruff check` and `mypy --ignore-missing-imports` were run against
  the full codebase and all findings (line-length violations, an
  unused loop variable, a third-party typing mismatch) were resolved,
  not just noted.
- The application was booted with a live `uvicorn` process and
  smoke-tested against `/health` and `/openapi.json` to confirm the
  ASGI app actually starts and serves traffic, independent of the
  test suite.
- Test coverage (93% line coverage on `app/`) was measured with
  `pytest-cov`, not estimated.

## What was not independently verified

- The GitHub Actions workflow was authored to standard, well-known
  patterns (matrix testing, service containers, Buildx caching) but
  was **not** executed against a live GitHub Actions runner as part
  of this submission — CI syntax correctness was reviewed manually
  (the YAML was parsed and validated), not run end-to-end on GitHub's
  infrastructure.
- The `Dockerfile` and `docker-compose.yml` were **not** built or run
  in this environment, because the sandbox used to prepare this
  submission has no Docker daemon available. Both files' YAML/syntax
  were validated (the compose file was parsed with PyYAML), and the
  Dockerfile follows a standard, previously-proven multi-stage
  pattern, but "the image actually builds and the container actually
  starts" was not directly observed here — this should be the first
  thing verified in an environment with Docker available, before
  relying on it for a real deployment.
- The Render and Railway deployment instructions describe the
  standard, documented workflow for each platform as of this
  writing, but a live deployment to either platform was not
  performed as part of this exercise; exact UI labels/menu paths may
  drift as those platforms evolve their dashboards.
- Outbound network calls to arbitrary real-world URLs were not
  exercised in this sandboxed environment (network egress here is
  restricted to a fixed allow-list); all HTTP-fetch behavior was
  validated via `respx`-mocked transports, which faithfully exercise
  the same `httpx` code paths (timeouts, connection errors, redirect
  handling) without requiring live internet access.

## Human role in this submission

The AI operated based on the assignment brief provided; the person
supervising this session reviewed the AI's plan, its intermediate
outputs, and the final deliverable set, and directed follow-up work
(e.g., "continue" prompts) to drive the submission to completion. No
part of this codebase or documentation was represented as
human-authored without AI involvement — this statement exists
precisely to make that involvement explicit and specific, rather than
a generic disclosure.
