"""Business OS MCP runner: executes commands declared in mcp.json files.

Fail-closed: only explicitly allowlisted commands run. Side-effect commands
require explicit approval/allow flag and emit audit events.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

AuditCallback = Callable[[dict[str, Any]], None]

# command -> policy. Unknown commands are denied.
_COMMAND_POLICY: dict[str, dict[str, Any]] = {
    "money-update": {"risk": "read_internal", "side_effect": False},
    "supply-level-monitor": {"risk": "read_internal", "side_effect": False},
    "generate-suggestions": {"risk": "reversible_internal", "side_effect": False},
    # External message send: high-risk side effect.
    "direct_send": {"risk": "external_commitment", "side_effect": True},
}


class BusinessOSMCPRunner:
    def __init__(
        self,
        root="aios/templates/business_os",
        *,
        allow_side_effects: bool = False,
        approved: bool = False,
        audit_callback: AuditCallback | None = None,
        org_id: str = "",
        actor: str = "",
    ):
        self.root = Path(root)
        self.allow_side_effects = bool(allow_side_effects)
        self.approved = bool(approved)
        self.audit_callback = audit_callback
        self.org_id = str(org_id or "")
        self.actor = str(actor or "")

    def _audit(self, event: dict[str, Any]) -> None:
        payload = {"source": "mcp_business_os", "org_id": self.org_id, "actor": self.actor, **event}
        logger.info("mcp_business_os.audit %s", payload)
        if self.audit_callback is not None:
            try:
                self.audit_callback(payload)
            except Exception:
                logger.warning("mcp_business_os audit callback failed", exc_info=True)

    def _entries(self):
        entries = []
        for path in sorted(self.root.glob("*/mcp.json")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def _entry(self, command):
        return next((e for e in self._entries() if e.get("command") == command), None)

    def _policy(self, command: str) -> dict[str, Any] | None:
        return _COMMAND_POLICY.get(str(command or "").strip())

    def _deny(self, command: str, reason: str, *, entry: dict[str, Any] | None = None) -> dict[str, Any]:
        self._audit(
            {
                "event": "mcp_business_os.denied",
                "command": command,
                "reason": reason,
                "ok": False,
                "entry": entry or {},
            }
        )
        return {"ok": False, "command": command, "error": reason, "denied": True}

    def _exec(self, command, *args):
        policy = self._policy(command)
        if policy is None:
            return self._deny(command, f"command not allowlisted: {command}")
        if policy.get("side_effect") and not (self.allow_side_effects and self.approved):
            return self._deny(
                command,
                f"side-effect command requires explicit approval: {command}",
            )

        safe_args = [str(a) for a in args]
        for a in safe_args:
            if "\x00" in a or len(a) > 500:
                return self._deny(command, f"invalid arg for {command}")

        self._audit(
            {
                "event": "mcp_business_os.execute",
                "command": command,
                "args": safe_args,
                "risk": policy.get("risk"),
                "side_effect": bool(policy.get("side_effect")),
            }
        )
        proc = subprocess.run(
            ["python", command, *safe_args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        result = {
            "ok": proc.returncode == 0,
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "risk": policy.get("risk"),
        }
        self._audit({"event": "mcp_business_os.result", **result})
        return result

    def run(self, command):
        entry = self._entry(command)
        if entry is None:
            return self._deny(command, "command not found")
        policy = self._policy(command)
        if policy is None:
            return self._deny(command, f"command not allowlisted: {command}", entry=entry)
        if command == "money-update":
            return self.money_update()
        if command == "supply-level-monitor":
            return self.supply_level_monitor()
        if command == "generate-suggestions":
            return self.generate_suggestions()
        if command == "direct_send":
            return self.direct_send(entry.get("channel", ""), entry.get("msg", ""))
        return self._deny(command, f"command not allowlisted: {command}", entry=entry)

    def money_update(self):
        return self._exec("money-update")

    def supply_level_monitor(self):
        return self._exec("supply-level-monitor")

    def generate_suggestions(self):
        return self._exec("generate-suggestions")

    def direct_send(self, channel, msg):
        return self._exec("direct_send", channel, msg)
