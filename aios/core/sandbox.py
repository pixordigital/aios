import asyncio
import logging
import resource
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_isolated(
    code: str, timeout: float = 10.0, max_memory_mb: int = 128
) -> dict:
    def _preexec():
        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (max_memory_mb * 1024 * 1024, max_memory_mb * 1024 * 1024),
            )
            resource.setrlimit(
                resource.RLIMIT_CPU, (int(timeout) + 1, int(timeout) + 1)
            )
        except Exception:
            pass

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_preexec,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": "timeout", "stdout": "", "stderr": "timeout"}
        return {
            "ok": proc.returncode == 0,
            "stdout": stdout.decode()[:10000],
            "stderr": stderr.decode()[:5000],
            "code": proc.returncode,
        }
    finally:
        try:
            Path(path).unlink()
        except Exception:
            pass
