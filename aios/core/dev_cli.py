import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
TIMEOUT_CLAUDE = 180
TIMEOUT_CODEX = 180

def _validate_cwd(cwd: str) -> str:
    if not cwd:
        return str(REPO_ROOT)
    p = (REPO_ROOT / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
    try:
        p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        raise ValueError(f"cwd fora do repo: {cwd}")
    return str(p)

async def _run(cmd: list[str], cwd: str = "", timeout: int = 120) -> dict:
    cwd_valid = _validate_cwd(cwd) if cwd else str(REPO_ROOT)
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd_valid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": "timeout", "stdout": "", "stderr": "timeout", "duration": timeout}
        duration = round(time.time() - start, 2)
        out = stdout.decode(errors="ignore")[:80000]
        err = stderr.decode(errors="ignore")[:8000]
        return {"ok": proc.returncode == 0, "code": proc.returncode, "stdout": out, "stderr": err, "duration": duration}
    except Exception as e:
        return {"ok": False, "error": str(e), "stdout": "", "stderr": str(e), "duration": round(time.time()-start,2)}

async def run_claude(prompt: str, cwd: str = "", timeout: int = TIMEOUT_CLAUDE, allowed_tools: str = "Read,Grep,Glob,Bash(git *)") -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", allowed_tools]
    # opencode caveman plugin expects json output; fallback to text if fails
    res = await _run(cmd, cwd=cwd, timeout=timeout)
    if not res["ok"] and "output-format" in res["stderr"]:
        cmd = ["claude", "-p", prompt]
        res = await _run(cmd, cwd=cwd, timeout=timeout)
    # try parse json stdout
    try:
        j = json.loads(res["stdout"])
        if isinstance(j, dict) and "result" in j:
            res["result"] = j["result"]
            res["stdout"] = j.get("result", res["stdout"])
    except Exception:
        pass
    return res

async def run_codex(prompt: str, cwd: str = "", timeout: int = TIMEOUT_CODEX, model: str = "") -> dict:
    from aios.config import settings
    model = model or getattr(settings, "codex_model", "") or "gpt-5.4"
    cmd = ["codex", "exec", "--sandbox", "read-only", "-m", model, prompt]
    res = await _run(cmd, cwd=cwd, timeout=timeout)
    return res

async def run_codex_review(cwd: str = "") -> dict:
    cmd = ["codex", "exec", "review", "--sandbox", "read-only"]
    return await _run(cmd, cwd=cwd, timeout=TIMEOUT_CODEX)

async def dual_review(prompt: str, cwd: str = "") -> dict:
    claude_p = f"Review caveman: Uma linha por achado L<linha>: <severidade> <problema>. <fix>. Severidade 🔴/🟡/🟢. Código:\n{prompt[:12000]}"
    codex_p = f"Review conciso 1 linha por achado: L<linha>: severidade problema. fix. Código:\n{prompt[:12000]}"
    a, b = await asyncio.gather(
        run_claude(claude_p, cwd=cwd, timeout=120),
        run_codex(codex_p, cwd=cwd, timeout=120),
        return_exceptions=True,
    )
    def norm(x):
        if isinstance(x, Exception):
            return {"ok": False, "error": str(x)}
        return x
    return {"claude": norm(a), "codex": norm(b), "ok": True}

async def dual_build(prompt: str, cwd: str = "") -> dict:
    a, b = await asyncio.gather(
        run_claude(f"Construa: {prompt[:12000]}", cwd=cwd, timeout=180, allowed_tools="Read,Write,Edit,Grep,Glob,Bash(git :*)"),
        run_codex(f"Construa: {prompt[:12000]}", cwd=cwd, timeout=180),
        return_exceptions=True,
    )
    def norm(x):
        if isinstance(x, Exception):
            return {"ok": False, "error": str(x)}
        return x
    return {"claude": norm(a), "codex": norm(b), "ok": True}
