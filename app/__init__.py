"""Page Pulse — a production-grade URL Audit Service.

Page Pulse fetches a target URL, times the response, inspects headers,
status codes and basic security posture, and returns a structured audit
report. Built with FastAPI, httpx, Redis-backed caching and rate
limiting, and structured JSON logging.
"""

__version__ = "1.0.0"
