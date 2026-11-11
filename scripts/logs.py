#!/usr/bin/env python3
"""Pretty-print AIOS JSON logs for local debugging.

Usage:
    docker logs app-... 2>&1 | python scripts/logs.py
    python scripts/logs.py --level WARNING --grep telegram app.log
    python scripts/logs.py --trace abc123

Reads a file or stdin, ignores non-JSON lines, and prints one compact line per
record with the fields that matter for scanning.
"""
import argparse
import json
import sys

_COLORS = {
    "DEBUG": "\033[90m",
    "INFO": "\033[36m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
_RESET = "\033[0m"
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _fmt(rec: dict, color: bool) -> str:
    level = str(rec.get("level", "INFO")).upper()
    ts = str(rec.get("timestamp", ""))[:19].replace("T", " ")
    trace = rec.get("trace_id", "-")
    req = rec.get("request_id", "-")
    name = rec.get("logger", "-")
    msg = rec.get("message", "")

    extras = {
        k: v for k, v in rec.items()
        if k not in {"timestamp", "level", "logger", "message", "trace_id",
                     "request_id", "module", "line", "exception"}
    }
    extra = " ".join(f"{k}={v}" for k, v in extras.items())
    if color:
        level = f"{_COLORS.get(level, '')}{level:<8}{_RESET}"
    else:
        level = f"{level:<8}"
    line = f"{ts} {level} {name} [trace={trace} req={req}] {msg}"
    if extra:
        line += f" {extra}"
    if rec.get("exception"):
        line += "\n" + str(rec["exception"])
    return line


def main() -> int:
    p = argparse.ArgumentParser(description="Pretty-print AIOS JSON logs")
    p.add_argument("file", nargs="?", help="log file (default: stdin)")
    p.add_argument("--level", default="DEBUG", help="minimum level (default: DEBUG)")
    p.add_argument("--grep", default="", help="only lines containing this text")
    p.add_argument("--trace", default="", help="only this trace_id")
    p.add_argument("--request", default="", help="only this request_id")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = p.parse_args()

    min_level = _LEVELS.get(args.level.upper(), 10)
    color = (not args.no_color) and sys.stdout.isatty()
    src = open(args.file, encoding="utf-8", errors="replace") if args.file else sys.stdin
    try:
        for raw in src:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                if args.grep and args.grep.lower() not in raw.lower():
                    continue
                print(raw)
                continue
            if _LEVELS.get(str(rec.get("level", "INFO")).upper(), 0) < min_level:
                continue
            if args.grep and args.grep.lower() not in raw.lower():
                continue
            if args.trace and rec.get("trace_id") != args.trace:
                continue
            if args.request and str(rec.get("request_id")) != args.request:
                continue
            print(_fmt(rec, color))
    finally:
        if args.file:
            src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
