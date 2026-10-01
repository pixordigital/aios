import ast
import asyncio
import logging
import os
import resource
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# The previous guard was substring matching on `code` (["os.system",
# "subprocess", "socket", "open(", ...]). It was trivially defeated: `import os`
# contains none of those substrings, and `importlib.import_module("os")` or
# `ctypes.CDLL(None).system(...)` never touch them at all. The sandbox is a
# plain subprocess running as the app user, so a bypass is full RCE: read
# /app/.env, reach the database, exfiltrate every tenant. This is an AST check
# instead, applied to every run_isolated() caller.
#
# It is defence in depth, NOT a hard boundary. `run_isolated` is not a
# container: the child shares the uid, the filesystem and the network. Real
# isolation needs a separate sandboxed container (--network=none, read-only
# rootfs, no capabilities); until then, treat this as raising the cost, not as
# a security guarantee.
_DENIED_MODULES = frozenset({
    # process, filesystem, network and introspection primitives
    "os", "sys", "subprocess", "socket", "ssl", "ctypes", "importlib", "shutil",
    "pathlib", "glob", "tempfile", "resource", "psutil", "mmap", "fcntl",
    "signal", "pty", "pwd", "grp", "posix", "nt", "termios", "platform",
    "getpass", "webbrowser", "code", "codeop", "runpy", "builtins", "gc",
    # network clients
    "http", "urllib", "requests", "httpx", "ftplib", "smtplib", "poplib",
    "imaplib", "telnetlib", "xmlrpc", "wsgiref", "asyncio", "concurrent",
    # deserialisation and concurrency
    "pickle", "marshal", "shelve", "multiprocessing", "threading", "queue",
    "sqlite3", "atexit", "logging", "io",
})

_DENIED_BUILTINS = frozenset({
    "open", "eval", "exec", "compile", "__import__", "globals", "locals",
    "vars", "dir", "getattr", "setattr", "delattr", "input", "breakpoint",
    "memoryview", "help", "exit", "quit",
})


def validate_code(code: str) -> str | None:
    """Return an error string if `code` may not run, else None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _DENIED_MODULES:
                    return f"import of '{alias.name}' is not allowed"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _DENIED_MODULES:
                return f"import from '{node.module}' is not allowed"
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _DENIED_BUILTINS:
                return f"call to '{fn.id}' is not allowed"
            # __import__("os").system(...) and getattr(__builtins__, "open")
            if isinstance(fn, ast.Attribute):
                if fn.attr in _DENIED_BUILTINS:
                    return f"call to '....{fn.attr}' is not allowed"
        elif isinstance(node, ast.Name):
            if node.id in ("__builtins__", "__loader__", "__spec__"):
                return f"use of '{node.id}' is not allowed"
    return None


def _scrubbed_env() -> dict:
    """Minimal child environment.

    run_isolated() previously inherited the app's full os.environ, so sandboxed
    code could read AIOS_ADMIN_MASTER_KEY, AIOS_JWT_SECRET, the Postgres
    password and every provider key straight out of /proc/self/environ. Hand the
    child only what an interpreter needs.
    """
    keep = ("PATH", "LANG", "LC_ALL", "TZ", "PYTHONHASHSEED", "PYTHONPATH",
            "HOME", "MPLBACKEND", "NUMEXPR_MAX_THREADS", "OMP_NUM_THREADS")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["PYTHONHASHSEED"] = "0"
    # Matplotlib/numexpr otherwise try to detect CPUs and spawns many threads
    # inside a 256MB rlimit.
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("OMP_NUM_THREADS", "1")
    env["HOME"] = env.get("HOME", "/tmp")
    return env


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

    err = validate_code(code)
    if err:
        return {"ok": False, "error": err, "stdout": "", "stderr": err, "code": None}

    with tempfile.TemporaryDirectory(prefix="aios-sandbox-") as workdir:
        path = str(Path(workdir) / "snippet.py")
        Path(path).write_text(code)
        proc = await asyncio.create_subprocess_exec(
            sys.executable or "python3",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_preexec,
            cwd=workdir,
            env=_scrubbed_env(),
        )
        return await _collect(proc, timeout)


async def _collect(proc, timeout: float) -> dict:
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
