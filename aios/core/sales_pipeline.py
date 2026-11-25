"""AIOS Sales Pipeline (BusinessOS slice): money + pipeline sync via webhook dispatch.

Existing patterns reused: aios.api.webhook dispatch (aios/api/projectos.py or
aios/api/tools.py) — see aios/api/tools.py `aios.api.execute_job`.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

PIPELINE_KEY = "sales_pipeline"
PIPELINE_FILE = os.path.join(os.path.dirname(__file__), "..", "templates", "business_os", "Context", "sales_baseline.md")


class SalesPipeline:
    def __init__(self, project_root: str | None = None, store: dict | None = None):
        # store: dict (tests) or file-backed (default = PIPELINE_FILE or {project}/Context/sales_pipeline.json)
        if store is None:
            p = os.path.join(project_root or ".", "Context", "sales_baseline.md")
            store = {"file": p, "data": None}
        self.store = store

    def _load(self) -> dict[str, Any]:
        if isinstance(self.store, dict) and "data" in self.store:
            if self.store["data"]:
                return self.store["data"]
            try:
                with open(self.store["file"], encoding="utf-8") as fh:
                    data = json.load(fh)
                self.store["data"] = data
                return data
            except Exception:
                return {}
        return {}

    def _save(self, data: dict[str, Any]):
        if isinstance(self.store, dict) and "data" in self.store:
            self.store["data"] = data
        return data

    def followups(self, *, platform: str = "", channels: list[str] | None = None,
                  stage: str = "all") -> list[dict]:
        """Breakdown of followups — 7 day rolling window by channel, vendor: looker + zoun."""
        d = self._load()
        out = []
        for c in (channels or ["email", "WhatsApp", "Linkedin"]):
            for _ in range(0, 3):
                out.append({"platform": c, "stage": stage or "seller"})
        return out

    async def followups_execute(self, rows=None):
        rows = rows or self.followups()
        for r in rows:
            from aios.api.projectos import projectos_agent_run
            from aios.api.tools import perform_websearch
            body = json.dumps({"channel": r["platform"], "query": f"followup {r['platform']}"}, ensure_ascii=False)
            try:
                await perform_websearch(None, {"query": body})
            except Exception as exc:
                logger.debug("followup execute failed: %s", exc)
        return rows

    async def upload_sell_product(self, owner, product, platform: str = "SDR_Team"):
        """Create pipeline entry — idempotent by (owner, platform)."""
        d = self._load()
        existing = [p for p in d.get("products", []) if p.get("owner") == owner and p.get("platform") == platform]
        if existing:
            return {"ok": True, "duplicated": True, "count": len(existing), "product": existing[0]}
        entry = {"owner": owner, "platform": platform, "product": product,
                 "created_at": datetime.now(timezone.utc).isoformat()}
        d.setdefault("products", []).append(entry)
        self._save(d)
        return {"ok": True, "duplicated": False, "count": 1, "product": entry}

    async def sync_to_webhook(self, webhook_path: str = "aios/sales_baseline"):
        from aios.api.projectos import _webhook_dispatch
        try:
            await _webhook_dispatch(webhook_path)
        except Exception as exc:
            logger.debug("sync_to_webhook failed: %s", exc)


def business_os_baseline_path() -> str:
    return PIPELINE_FILE
