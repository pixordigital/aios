"""supply-level-monitor: read weekly-supply-check.json, return/exit when risk."""
import json
import os
import sys


def supply_check(path: str) -> dict:
    if not os.path.isfile(path):
        return {"risk": False, "level": 0, "file": path, "missing": True}
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    level = int(d.get("supply_level", 0) or 0)
    return {"risk": level >= 2, "level": level, "file": path, "missing": False}


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "..", "templates", "business_os", "Money", "weekly-supply-check.json")
    r = supply_check(path)
    print(f"supply_level={r['level']} risk={r['risk']} file={path}")
    return 1 if r["risk"] else 0


if __name__ == "__main__":
    sys.exit(main())
