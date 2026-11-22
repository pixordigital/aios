"""Canonical ARVO ↔ AIOS event envelope."""

import json

from pydantic import BaseModel, Field, field_validator

MAX_PAYLOAD_BYTES = 64 * 1024


class ArvoEnvelope(BaseModel):
    type: str = Field(..., max_length=64, pattern=r"^[a-z0-9_.-]+$")
    payload: dict = Field(default_factory=dict)
    business_trace_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    event_version: str = Field(default="1", min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")

    @field_validator("payload")
    @classmethod
    def _bounded_payload(cls, value: dict) -> dict:
        if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload too large")
        return value
