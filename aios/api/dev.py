from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aios.api.deps import get_current_user
from aios.core.dev_cli import run_claude, run_codex, dual_review, dual_build, run_codex_review

router = APIRouter(prefix="/api/dev", tags=["dev"])

class PromptIn(BaseModel):
    prompt: str
    cwd: str = ""
    timeout: int = 120

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
    res = await run_claude(body.prompt, cwd=body.cwd, timeout=min(body.timeout, 300))
    return res

@router.post("/codex")
async def codex_run(body: PromptIn, user=Depends(get_current_user)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    res = await run_codex(body.prompt, cwd=body.cwd, timeout=min(body.timeout, 300))
    return res

@router.post("/review")
async def review(body: ReviewIn, user=Depends(get_current_user)):
    prompt = body.diff or body.prompt
    if not prompt.strip():
        # auto diff
        import subprocess
        try:
            diff = subprocess.check_output(["git", "diff", "HEAD~1"], text=True)[:15000]
            prompt = diff or "Review último commit"
        except Exception:
            prompt = "Review sem diff"
    res = await dual_review(prompt)
    return res

@router.post("/review/codex")
async def codex_review_only(user=Depends(get_current_user)):
    res = await run_codex_review()
    return res

@router.post("/build")
async def build(body: PromptIn, user=Depends(get_current_user)):
    if not body.prompt.strip():
        raise HTTPException(400, "prompt vazio")
    res = await dual_build(body.prompt, cwd=body.cwd)
    return res
