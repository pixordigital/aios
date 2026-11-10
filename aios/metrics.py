"""Prometheus metrics integration for AIOS.

Provides a minimal /metrics endpoint exposing counters for:
- total HTTP requests
- request latency histogram
- token usage (input/output) if available via request context

Uses `aioprometheus` which is lightweight and compatible with async frameworks.
"""

from fastapi import APIRouter, Request, Response
from aioprometheus import Counter, Histogram, Service

router = APIRouter()

# Global Prometheus service (started on first request)
_service: Service | None = None

# Define metrics
REQUEST_COUNT = Counter("aios_http_requests_total", "Total HTTP requests processed")
REQUEST_LATENCY = Histogram(
    "aios_http_request_duration_seconds",
    "HTTP request latency in seconds",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5]
)
TOKEN_INPUT = Counter("aios_tokens_input_total", "Total input tokens processed")
TOKEN_OUTPUT = Counter("aios_tokens_output_total", "Total output tokens generated")

async def _ensure_service():
    global _service
    if _service is None:
        _service = Service()
        await _service.start(addr="0.0.0.0", port=8000)  # bound to localhost; metrics endpoint will proxy
        # Register metrics
        _service.register(REQUEST_COUNT)
        _service.register(REQUEST_LATENCY)
        _service.register(TOKEN_INPUT)
        _service.register(TOKEN_OUTPUT)

@router.middleware("http")
async def metrics_middleware(request: Request, call_next):
    await _ensure_service()
    REQUEST_COUNT.inc({"path": request.url.path, "method": request.method})
    with REQUEST_LATENCY.time({"path": request.url.path, "method": request.method}):
        response: Response = await call_next(request)
        # If response includes token usage headers, increment counters (optional)
        if "x-token-input" in response.headers:
            try:
                TOKEN_INPUT.inc(float(response.headers["x-token-input"]))
            except ValueError:
                pass
        if "x-token-output" in response.headers:
            try:
                TOKEN_OUTPUT.inc(float(response.headers["x-token-output"]))
            except ValueError:
                pass
        return response

@router.get("/metrics")
async def get_metrics():
    """Expose Prometheus metrics.

    The aioprometheus service already serves its own /metrics endpoint on the port it
    was started on. To keep things simple we proxy that content.
    """
    global _service
    if _service is None:
        await _ensure_service()
    # Pull metrics from the service directly
    return Response(content=await _service.metrics(), media_type="text/plain; version=0.0.4")
