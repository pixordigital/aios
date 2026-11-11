"""Prometheus metrics integration for AIOS.

Provides a minimal /metrics endpoint exposing counters for:
- total HTTP requests
- request latency histogram
- token usage (input/output) if available via request context

Uses `aioprometheus` Registry directly; no background Service is started.
"""

from fastapi import APIRouter, Request, Response
from aioprometheus import Counter, Histogram, Registry

router = APIRouter()

# Global Prometheus registry
_registry: Registry | None = None

# Define metrics
REQUEST_COUNT = Counter("aios_http_requests_total", "Total HTTP requests processed")
REQUEST_LATENCY = Histogram(
    "aios_http_request_duration_seconds",
    "HTTP request latency in seconds",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5]
)
TOKEN_INPUT = Counter("aios_tokens_input_total", "Total input tokens processed")
TOKEN_OUTPUT = Counter("aios_tokens_output_total", "Total output tokens generated")

async def _ensure_registry():
    global _registry
    if _registry is None:
        _registry = Registry()
        _registry.register(REQUEST_COUNT)
        _registry.register(REQUEST_LATENCY)
        _registry.register(TOKEN_INPUT)
        _registry.register(TOKEN_OUTPUT)


@router.get("/metrics")
async def get_metrics() -> Response:
    """Expose Prometheus metrics in the text exposition format."""
    await _ensure_registry()
    return Response(content=await _registry.render(), media_type="text/plain; version=0.0.4")
