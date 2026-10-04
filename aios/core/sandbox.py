import ast
import asyncio
import logging
import os
import resource
import shutil
import signal
import subprocess
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
# Two independent layers, because the first one is defeatable on its own:
#   1. this AST check -- an import ALLOWLIST plus a denied-name bind guard
#   2. `run_isolated` -- executes inside a container when the docker CLI is
#      available (--network=none --read-only --cap-drop=ALL, unprivileged uid)
#      and falls back to a resource-limited subprocess with the whole process
#      group killed on timeout.
# The AST check used to be a bare denylist over call names, so `e = exec` or
# `o = open` aliased a banned name and sailed past it, and the child shared the
# app's uid, filesystem and network. A name denylist is not a boundary; it
# raises the cost only.
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

# Import ALLOWLIST. The sandbox exists so agents can do data analysis, not so
# they can reach the host: only the stdlib needed for that is importable. An
# allowlist cannot be walked past by inventing a new name for `os`.
_ALLOWED_MODULES = frozenset({
    "math", "statistics", "json", "re", "datetime", "decimal", "fractions",
    "random", "itertools", "functools", "collections", "heapq", "bisect",
    "string", "textwrap", "unicodedata", "operator", "copy", "types",
    "numbers", "abc", "enum", "dataclasses", "typing", "uuid", "base64",
    "csv", "io", "array", "struct", "zlib", "gzip", "hashlib", "hmac",
    "statistics", "pprint", "reprlib", "keyword", "tokenize", "ast",
    "unicodedata", "locale", "calendar", "time", "zoneinfo",
    # third-party, present because the sandbox documents pandas/plot support
    "pandas", "numpy", "matplotlib", "scipy", "sklearn", "polars",
})

# Names that must never be *bound* to a name, whatever the right-hand side is.
# This is the hole that made `e = exec; e("...")` work.
_UNBINDABLE = _DENIED_BUILTINS | {"__builtins__", "__loader__", "__spec__"}


def validate_code(code: str) -> str | None:
    """Return an error string if `code` may not run, else None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _DENIED_MODULES:
                    return f"import of '{alias.name}' is not allowed"
                if root not in _ALLOWED_MODULES:
                    return f"import of '{alias.name}' is not on the sandbox allowlist"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level:
                return "relative imports are not allowed"
            if root in _DENIED_MODULES:
                return f"import from '{node.module}' is not allowed"
            if root not in _ALLOWED_MODULES:
                return f"import from '{node.module}' is not on the sandbox allowlist"
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _DENIED_BUILTINS:
                return f"call to '{fn.id}' is not allowed"
            # __import__("os").system(...) and getattr(__builtins__, "open")
            if isinstance(fn, ast.Attribute) and fn.attr in _DENIED_BUILTINS:
                return f"call to '....{fn.attr}' is not allowed"
        elif isinstance(node, ast.Attribute):
            # Not just calls: reading os.environ / subprocess.Popen is the same
            # capability whether or not it is invoked in this expression.
            if node.attr in _DENIED_BUILTINS:
                return f"use of '....{node.attr}' is not allowed"
        elif isinstance(node, ast.Name):
            # Any *reference* to a denied builtin, not just a call. `f = lambda: open`
            # followed by `f("/etc/passwd")` never forms an ast.Call on `open`,
            # so the call-only check let it through.
            if node.id in _UNBINDABLE:
                return f"use of '{node.id}' is not allowed"
        elif isinstance(node, ast.Assign):
            # The bypass this closes: `e = exec` / `o = open` / `i = __import__`
            # bound a denied name and then called it through the alias, which the
            # old name-only checks never saw.
            targets = [t for t in node.targets]
            if isinstance(node.value, ast.Name) and node.value.id in _UNBINDABLE:
                targets = targets + [node.value]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id in _UNBINDABLE:
                        return f"binding '{n.id}' is not allowed"
        elif isinstance(node, (ast.For, ast.comprehension, ast.withitem, ast.Lambda)):
            # `for open in ...` / `[exec for ...]` rebind the same way.
            names: list = []
            if isinstance(node, ast.For):
                names = [node.target]
            elif isinstance(node, ast.comprehension):
                names = [node.target]
            elif isinstance(node, ast.Lambda):
                # ast.arg has no .id, so it needs checking by attribute.
                for a in list(node.args.args) + list(node.args.kwonlyargs) + list(node.args.posonlyargs):
                    if a.arg in _UNBINDABLE:
                        return f"binding '{a.arg}' is not allowed"
            for t in names:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id in _UNBINDABLE:
                        return f"binding '{n.id}' is not allowed"
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


# Container isolation. When the docker CLI is present the snippet runs with no
# network, a read-only rootfs, no capabilities and an unprivileged uid, which is
# what actually stops `os.system` / file writes / TCP egress. Without it we fall
# back to the resource-limited subprocess below -- still better than nothing, but
# that path shares the uid and is defence in depth, not a boundary.
# Empty by default, which means "no container" -- the snippet runs in a
# resource-limited subprocess behind the AST allowlist. That is defence in
# depth, not isolation. Set AIOS_SANDBOX_IMAGE to an image you built WITH the
# data stack to turn on real container isolation:
#
#   FROM python:3.12-slim
#   RUN pip install --no-cache-dir pandas numpy matplotlib
#
# It cannot be defaulted to a stock python image: --network=none means pip
# cannot run at request time, so a slim image would silently break the pandas
# and plotting support the sandbox documents.
SANDBOX_IMAGE = os.getenv("AIOS_SANDBOX_IMAGE", "")


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _image_present(image: str) -> bool:
    """Only use the container when its image is already on the host.

    Two reasons this is checked rather than assumed: `docker run` would try to
    pull mid-request (and --network=none is not the blocker, the registry fetch
    is), and the default image must be one an operator deliberately built with
    the data stack, because a network-less container cannot pip install pandas.
    """
    if not _docker_available():
        return False
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
    except Exception:
        return False
    if r.returncode != 0:
        logger.warning(
            "sandbox image %r not present locally; running without container "
            "isolation. Build it with the data stack, or set AIOS_SANDBOX_IMAGE.",
            image,
        )
        return False
    return True


async def _run_in_container(path: str, timeout: float, max_memory_mb: int) -> dict | None:
    """Run the snippet in a locked-down container. None if docker is unusable."""
    if not SANDBOX_IMAGE or not _image_present(SANDBOX_IMAGE):
        return None
    workdir = str(Path(path).parent)
    # The container runs as nobody:nogroup, so the snippet and its directory
    # have to be traversable by it.
    os.chmod(workdir, 0o755)
    os.chmod(path, 0o644)
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "64",
        "--memory", f"{max_memory_mb}m",
        "--cpus", "1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
        "--user", "65534:65534",  # nobody:nogroup
        "--workdir", "/w",
        "-v", f"{workdir}:/w:ro",
        SANDBOX_IMAGE,
        "python", "/w/" + Path(path).name,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "MPLBACKEND": "Agg"},
        )
    except Exception:
        return None
    return await _collect(proc, timeout)


async def run_isolated(
    code: str, timeout: float = 10.0, max_memory_mb: int = 512
) -> dict:
    # 512MB, not 128. pandas/numpy reserve far more *virtual* address space than
    # they use, so RLIMIT_AS=128 killed the interpreter at `import pandas` --
    # the data-analysis support this sandbox documents simply could not run at
    # the old default. 512 is the smallest value that actually loads it.
    def _preexec():
        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (max_memory_mb * 1024 * 1024, max_memory_mb * 1024 * 1024),
            )
            resource.setrlimit(
                resource.RLIMIT_CPU, (int(timeout) + 1, int(timeout) + 1)
            )
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
        except Exception:
            pass

    err = validate_code(code)
    if err:
        return {"ok": False, "error": err, "stdout": "", "stderr": err, "code": None}

    with tempfile.TemporaryDirectory(prefix="aios-sandbox-") as workdir:
        path = str(Path(workdir) / "snippet.py")
        Path(path).write_text(code)

        container = await _run_in_container(path, timeout, max_memory_mb)
        if container is not None:
            return container

        proc = await asyncio.create_subprocess_exec(
            sys.executable or "python3",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_preexec,
            cwd=workdir,
            env=_scrubbed_env(),
            # Own session, so _collect can signal the whole process group. A
            # forked grandchild used to survive the timeout and keep running
            # after the tool had already returned.
            start_new_session=True,
        )
        return await _collect(proc, timeout)


async def _collect(proc, timeout: float) -> dict:
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        # Kill the group, not just the direct child. A forked grandchild
        # inherits nothing useful from RLIMIT_CPU (it sleeps, it does not burn
        # CPU) and used to keep running after the caller already got `timeout`.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (TimeoutError, asyncio.TimeoutError):
            pass
        return {"ok": False, "error": "timeout", "stdout": "", "stderr": "timeout"}
    return {
        "ok": proc.returncode == 0,
        "stdout": stdout.decode()[:10000],
        "stderr": stderr.decode()[:5000],
        "code": proc.returncode,
    }
