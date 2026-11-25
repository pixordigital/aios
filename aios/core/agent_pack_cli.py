"""CLI for Agent Pack export/install/inspect.

Stdlib-only. No network/subprocess from bundle. Install keeps consent/trust/
capability-loss gates; CLI passes args only, never bypasses checks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aios.core.agent_pack import AgentPackValidationError, load_agent_pack
from aios.core.agent_pack_export import export_agent_pack
from aios.core.agent_pack_install import (
    InstallConsent,
    apply_install,
    inspect_bundle,
    plan_install,
)

_TARGETS = ("claude_code", "codex", "opencode", "openclaw")


def _jprint(data: Any) -> None:
    print(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def _loss_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "capability_loss: none"
    lines = [f"capability_loss: {len(items)} item(s)"]
    for item in items:
        lines.append(
            "- [{severity}/{status}] {field}: {reason}".format(
                severity=item.get("severity", "?"),
                status=item.get("status", "?"),
                field=item.get("field_path", "?"),
                reason=item.get("reason", ""),
            )
        )
    return "\n".join(lines)


def _plan_summary(plan) -> str:
    ops = plan.operations
    counts = {"create": 0, "modify": 0, "noop": 0}
    for op in ops:
        counts[op.op] = counts.get(op.op, 0) + 1
    lines = [
        f"target: {plan.target}",
        f"bundle_hash: {plan.bundle_hash}",
        f"plan_hash: {plan.plan_hash}",
        f"trust: {plan.trust}",
        f"target_root: {plan.target_root}",
        f"operations: create={counts['create']} modify={counts['modify']} noop={counts['noop']}",
        "trust_reasons:",
    ]
    for r in plan.trust_reasons:
        lines.append(f"- {r}")
    lines.append(_loss_summary(plan.capability_loss))
    if plan.requires_unsigned_ack:
        lines.append("UNSIGNED: requires --allow-unsigned and consent phrase containing UNSIGNED_RISK_ACCEPTED")
    if plan.requires_capability_loss_ack:
        lines.append("CAPABILITY LOSS: requires --accept-capability-loss")
    lines.append("APPLY: requires --confirm-install; nothing installed without explicit confirmation")
    return "\n".join(lines)


def cmd_inspect(args: argparse.Namespace) -> int:
    insp = inspect_bundle(args.bundle_dir)
    if args.target:
        manifest_target = (insp.get("manifest") or {}).get("target")
        if manifest_target and manifest_target != args.target:
            _eprint(f"target mismatch: bundle={manifest_target} requested={args.target}")
            return 2
    _jprint(insp)
    return 0 if insp.get("hashes_ok") else 2


def cmd_export(args: argparse.Namespace) -> int:
    manifest = load_agent_pack(args.manifest)
    result = export_agent_pack(
        manifest,
        target=args.target,
        output_dir=args.output,
        capability_loss=None,
    )
    _jprint(result.model_dump(mode="json"))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    plan = plan_install(
        args.bundle_dir,
        args.target,
        target_root=args.target_root,
        records_dir=args.records_dir,
    )

    # Always print plan + capability loss before any apply decision.
    if args.json:
        _jprint({"plan": plan.model_dump(mode="json")})
    else:
        print(_plan_summary(plan))

    missing: list[str] = []
    if plan.requires_capability_loss_ack and not args.accept_capability_loss:
        missing.append("--accept-capability-loss")
    if plan.requires_unsigned_ack and not args.allow_unsigned:
        missing.append("--allow-unsigned")
    if not args.actor:
        missing.append("--actor")
    if not args.consent:
        missing.append("--consent")
    if not args.confirm_install:
        missing.append("--confirm-install")

    if missing:
        _eprint("install blocked: missing required flags: " + ", ".join(missing))
        _eprint("no files were installed")
        return 2

    consent = InstallConsent(
        actor=args.actor,
        bundle_hash=plan.bundle_hash,
        target=plan.target,
        plan_hash=plan.plan_hash,
        capability_loss_ack=bool(args.accept_capability_loss),
        consent_phrase=args.consent,
        timestamp=args.timestamp or __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        allow_unsigned=bool(args.allow_unsigned),
        force=bool(args.force),
    )
    result = apply_install(
        plan,
        consent=consent,
        records_dir=args.records_dir,
        audit_log_path=args.audit_log,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _jprint(payload)
    else:
        _jprint(payload)
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aios pack", description="Agent Pack export/install/inspect")
    sub = parser.add_subparsers(dest="pack_cmd", required=True)

    p_inspect = sub.add_parser("inspect", help="Inspect bundle hashes, trust, capability loss")
    p_inspect.add_argument("bundle_dir", help="Bundle directory")
    p_inspect.add_argument("--target", choices=list(_TARGETS), help="Optional target assertion")
    p_inspect.add_argument("--json", action="store_true", help="JSON output")
    p_inspect.set_defaults(func=cmd_inspect)

    p_export = sub.add_parser("export", help="Export agent pack manifest to target bundle")
    p_export.add_argument("--manifest", required=True, help="Agent pack manifest path (.json/.yaml)")
    p_export.add_argument("--target", required=True, choices=list(_TARGETS))
    p_export.add_argument("--output", required=True, help="Output bundle directory")
    p_export.set_defaults(func=cmd_export)

    p_install = sub.add_parser("install", help="Guided local install; requires explicit consent/ack flags")
    p_install.add_argument("bundle_dir", help="Bundle directory")
    p_install.add_argument("--target", required=True, choices=list(_TARGETS))
    p_install.add_argument("--actor", help="Actor identity recorded in audit/install record")
    p_install.add_argument("--consent", help="Explicit consent phrase; unsigned requires UNSIGNED_RISK_ACCEPTED")
    p_install.add_argument("--accept-capability-loss", action="store_true", help="Acknowledge capability loss report")
    p_install.add_argument("--allow-unsigned", action="store_true", help="Allow unsigned bundle (still requires consent phrase)")
    p_install.add_argument("--confirm-install", action="store_true", help="Actually apply install; without this flag CLI only shows plan")
    p_install.add_argument("--force", action="store_true", help="Only for drift recovery paths where core allows; not a bypass")
    p_install.add_argument("--target-root", help="Override target root (must remain allowed by core checks)")
    p_install.add_argument("--records-dir", help="Override install records directory")
    p_install.add_argument("--audit-log", help="Override audit log path")
    p_install.add_argument("--timestamp", help="ISO8601 consent timestamp (default: now UTC)")
    p_install.add_argument("--json", action="store_true", help="JSON output")
    p_install.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except AgentPackValidationError as exc:
        _eprint(f"agent-pack error: {exc}")
        return 2
    except KeyboardInterrupt:
        _eprint("interrupted")
        return 130
    except Exception as exc:
        _eprint(f"agent-pack error: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
