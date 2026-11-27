from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aios.api.deps import get_superadmin
from aios.core.dev_cli import run_claude, run_codex, dual_review, dual_build, run_codex_review

router = APIRouter(prefix="/api/dev", tags=["dev"])

from pydantic import Field

def _validate_cwd(cwd: str) -> str:
    if not cwd:
        return ""
    from pathlib import Path
    from aios.core.dev_cli import REPO_ROOT
    p = (REPO_ROOT / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
    try:
        p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        raise ValueError(f"cwd fora do repo: {cwd}")
    return str(p)

class PromptIn(BaseModel):
    prompt: str
    cwd: str = ""
    timeout: int = Field(default=120, ge=5, le=300)
    model: str = Field(default="", description="override model codex")

class ReviewIn(BaseModel):
    diff: str = ""
    prompt: str = ""
    cwd: str = ""

def _dev_subprocess_enabled() -> bool:
    import os
    raw = os.getenv("AIOS_DEV_SUBPROCESS_ENABLED")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from aios.config import settings

        return bool(getattr(settings, "dev_subprocess_enabled", False))
    except Exception:
        return False


def _audit_dev_api(action: str, details: dict) -> None:
    try:
        from aios.core.audit_sink import append as _audit_append

        _audit_append("system", action, {"component": "api.dev", **details})
    except Exception:
        pass


@router.get("/status")
async def status(user=Depends(get_superadmin)):
    import shutil
    enabled = _dev_subprocess_enabled()
    return {
        "enabled": enabled,
        "claude": {"path": shutil.which("claude"), "version": await _ver("claude") if enabled else "disabled"},
        "codex": {"path": shutil.which("codex"), "version": await _ver("codex") if enabled else "disabled"},
        "opencode": {"path": shutil.which("opencode")},
    }

async def _ver(cmd: str) -> str:
    import asyncio
    if not _dev_subprocess_enabled():
        return "disabled"
    try:
        _audit_dev_api("dev.subprocess.start", {"cmd": cmd, "mode": "version"})
        p = await asyncio.create_subprocess_exec(cmd, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=5)
        ver = out.decode().strip()[:80]
        _audit_dev_api("dev.subprocess.completed", {"cmd": cmd, "mode": "version", "rc": p.returncode})
        return ver
    except Exception:
        _audit_dev_api("dev.subprocess.failed", {"cmd": cmd, "mode": "version"})
        return ""

@router.post("/claude")
async def claude_run(body: PromptIn, user=Depends(get_superadmin)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    try:
        cwd = _validate_cwd(body.cwd)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res = await run_claude(body.prompt, cwd=cwd, timeout=min(body.timeout, 300))
    return res

@router.post("/codex")
async def codex_run(body: PromptIn, user=Depends(get_superadmin)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    try:
        cwd = _validate_cwd(body.cwd)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res = await run_codex(body.prompt, cwd=cwd, timeout=min(body.timeout, 300), model=body.model)
    return res

@router.post("/review")
async def review(body: ReviewIn, user=Depends(get_superadmin)):
    try:
        cwd = _validate_cwd(body.cwd)
    except ValueError as e:
        raise HTTPException(400, str(e))
    prompt = body.diff or body.prompt
    if not prompt.strip():
        import subprocess
        from aios.core.dev_cli import REPO_ROOT
        try:
            diff = subprocess.check_output(["git", "diff", "HEAD~1"], text=True, cwd=str(REPO_ROOT), timeout=5)[:15000]
            prompt = diff or "Review último commit"
        except Exception:
            prompt = "Review sem diff"
    res = await dual_review(prompt, cwd=cwd)
    return res

@router.post("/review/codex")
async def codex_review_only(user=Depends(get_superadmin)):
    res = await run_codex_review()
    return res

@router.post("/build")
async def build(body: PromptIn, user=Depends(get_superadmin)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    try:
        cwd = _validate_cwd(body.cwd)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res = await dual_build(body.prompt, cwd=cwd)
    return res
