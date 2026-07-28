import logging

logger = logging.getLogger(__name__)

import json
import zoneinfo
from datetime import datetime, timezone
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY


class CurrentDatetimeTool(BaseTool):
    name = "current_datetime"
    description = "Get the current UTC datetime, optionally with a timezone"
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "Optional IANA timezone (e.g. America/New_York). Returns UTC if omitted.",
                "default": ""
            }
        }
    }

    async def run(self, timezone: str = "") -> dict:
        utc = datetime.now(timezone.utc)
        if timezone:
            try:
                tz = zoneinfo.ZoneInfo(timezone)
                local = datetime.now(tz)
                return {"utc": utc.isoformat(), "local": local.isoformat(), "timezone": timezone}
            except zoneinfo.ZoneInfoNotFoundError:
                return {"utc": utc.isoformat(), "local": utc.isoformat(), "timezone": "UTC"}
        return {"utc": utc.isoformat(), "local": utc.isoformat(), "timezone": "UTC"}


TOOL_REGISTRY["current_datetime"] = {
    "code_reference": "aios.tools.current_datetime.CurrentDatetimeTool",
}
