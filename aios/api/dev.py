from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aios.api.deps import get_current_user
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
        raise HTTPException(400, "cwd fora do repo")
    return str(p)

class PromptIn(BaseModel):
    prompt: str
    cwd: str = ""
    timeout: int = Field(default=120, ge=5, le=300)

class ReviewIn(BaseModel):
    diff: str = ""
    prompt: str = ""
    cwd: str = ""

@router.get("/status")
async def status(user=Depends(get_current_user)):
    import shutil
    return {
        "claude": {"path": shutil.which("claude"), "version": await _ver("claude")},
        "codex": {"path": shutil.which("codex"), "version": await _ver("codex")},
        "opencode": {"path": shutil.which("opencode")},
    }

async def _ver(cmd: str) -> str:
    import asyncio
    try:
        p = await asyncio.create_subprocess_exec(cmd, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=5)
        return out.decode().strip()[:80]
    except Exception:
        return ""

@router.post("/claude")
async def claude_run(body: PromptIn, user=Depends(get_current_user)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    cwd = _validate_cwd(body.cwd)
    res = await run_claude(body.prompt, cwd=cwd, timeout=min(body.timeout, 300))
    return res

@router.post("/codex")
async def codex_run(body: PromptIn, user=Depends(get_current_user)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    cwd = _validate_cwd(body.cwd)
    res = await run_codex(body.prompt, cwd=cwd, timeout=min(body.timeout, 300))
    return res

@router.post("/review")
async def review(body: ReviewIn, user=Depends(get_current_user)):
    cwd = _validate_cwd(body.cwd)
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
async def codex_review_only(user=Depends(get_current_user)):
    res = await run_codex_review()
    return res

@router.post("/build")
async def build(body: PromptIn, user=Depends(get_current_user)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    cwd = _validate_cwd(body.cwd)
    res = await dual_build(body.prompt, cwd=cwd)
    return res
