"""Business OS MCP runner: executes the commands declared in the mcp.json files."""
import json
import subprocess
from pathlib import Path


class BusinessOSMCPRunner:
    def __init__(self, root="aios/templates/business_os"):
        self.root = Path(root)

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

    def _exec(self, command, *args):
        proc = subprocess.run(["python", command, *args], capture_output=True, text=True)
        return {
            "ok": proc.returncode == 0,
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }

    def run(self, command):
        entry = self._entry(command)
        if entry is None:
            return {"ok": False, "command": command, "error": "command not found"}
        if command == "money-update":
            return self.money_update()
        if command == "supply-level-monitor":
            return self.supply_level_monitor()
        if command == "generate-suggestions":
            return self.generate_suggestions()
        if command == "direct_send":
            return self.direct_send(entry.get("channel", ""), entry.get("msg", ""))
        return self._exec(command)

    def money_update(self):
        return self._exec("money-update")

    def supply_level_monitor(self):
        return self._exec("supply-level-monitor")

    def generate_suggestions(self):
        return self._exec("generate-suggestions")

    def direct_send(self, channel, msg):
        return self._exec("direct_send", channel, msg)
