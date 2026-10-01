"""Regression tests for the code sandbox.

The sandbox is a plain subprocess running as the app user, so anything that
reaches `run_isolated` with an escape is remote code execution: read /app/.env,
open the database, exfiltrate every tenant. The old guard was substring matching
on the source text, which `import os`, `importlib` and `ctypes` all walked past.

These tests pin the AST guard. They are deliberately written as "this exact escape
must stay closed" cases rather than general policy assertions, so a future
refactor that loosens the denylist fails loudly.
"""

import pytest

from aios.core.sandbox import _scrubbed_env, run_isolated, validate_code
from aios.tools.python_sandbox import PythonSandboxTool


# Every one of these executed successfully before the AST guard existed.
ESCAPES = {
    "plain os import": "import os\nprint(os.getcwd())",
    "from os import": "from os import getcwd\nprint(getcwd())",
    "os aliased": "import os as o\nprint(o.getcwd())",
    "subprocess": "import subprocess\nprint(subprocess.run(['id']))",
    "ctypes libc exec": "import ctypes\nprint(ctypes.CDLL(None).system('id'))",
    "importlib dynamic": "import importlib\nprint(importlib.import_module('os').getcwd())",
    "dunder import": "print(__import__('os').getcwd())",
    "socket": "import socket\nprint(socket.gethostname())",
    "http.client egress": (
        "import http.client\n"
        "c = http.client.HTTPConnection('127.0.0.1', 8777, timeout=4)\n"
        "c.request('GET', '/health')\n"
        "print(c.getresponse().status)\n"
    ),
    "urllib egress": "import urllib.request\nprint(urllib.request.urlopen('http://127.0.0.1:8777/health'))",
    "file read": "print(open('/etc/hosts').read())",
    "pathlib read": "import pathlib\nprint(pathlib.Path('/etc/hostname').read_text())",
    "eval chain": "print(eval('__import__(\"os\").getcwd()'))",
    "exec chain": "exec(\"import os\")",
    "globals access": "print(globals())",
    "builtins access": "print(__builtins__)",
    "pickle": "import pickle\nprint(pickle.loads(b''))",
}


@pytest.mark.parametrize("label", sorted(ESCAPES))
def test_escape_rejected_by_validator(label):
    """Every known escape must be refused before a process is spawned."""
    assert validate_code(ESCAPES[label]) is not None, f"{label} was allowed"


@pytest.mark.parametrize("label", sorted(ESCAPES))
@pytest.mark.asyncio
async def test_escape_returns_error_from_tool(label):
    """And the agent-facing tool must surface the refusal, not run the code."""
    res = await PythonSandboxTool().run(code=ESCAPES[label])
    assert not res.get("ok"), f"{label} ran: {res}"
    assert res.get("error") or res.get("stderr")


@pytest.mark.asyncio
async def test_nested_import_in_function_rejected():
    """Imports inside functions/classes are walked too, not just top level."""
    assert validate_code("def f():\n    import os\n    return os\n") is not None
    assert validate_code("class C:\n    import socket\n") is not None
    assert validate_code("try:\n    import ctypes\nexcept ImportError:\n    pass\n") is not None


@pytest.mark.asyncio
async def test_legitimate_data_analysis_still_runs():
    """The denylist must not break the pandas work the tool exists for."""
    res = await PythonSandboxTool().run(
        code="import pandas as pd\n"
             "df = pd.DataFrame({'a': [1, 2, 3]})\n"
             "print('sum', df['a'].sum())\n"
    )
    assert res.get("ok"), res
    assert "sum 6" in res["stdout"]


@pytest.mark.asyncio
async def test_stdlib_math_and_json_allowed():
    """Non-dangerous stdlib stays available."""
    res = await PythonSandboxTool().run(
        code="import math, json\nprint(json.dumps({'v': math.floor(3.7)}))"
    )
    assert res.get("ok"), res
    assert '"v": 3' in res["stdout"]


@pytest.mark.asyncio
async def test_syntax_error_reported_not_executed():
    res = await PythonSandboxTool().run(code="def broken(:\n")
    assert not res.get("ok")


def test_child_env_is_scrubbed(monkeypatch):
    """Sandboxed code must not inherit the app's secrets from os.environ."""
    monkeypatch.setenv("AIOS_ADMIN_MASTER_KEY", "leaked")
    monkeypatch.setenv("AIOS_JWT_SECRET", "leaked")
    monkeypatch.setenv("POSTGRES_PASSWORD", "leaked")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "leaked")
    env = _scrubbed_env()
    assert "AIOS_ADMIN_MASTER_KEY" not in env
    assert "AIOS_JWT_SECRET" not in env
    assert "POSTGRES_PASSWORD" not in env
    assert "STRIPE_SECRET_KEY" not in env
    assert env.get("PATH")


@pytest.mark.asyncio
async def test_run_isolated_enforces_validator_for_all_callers():
    """run_isolated itself guards, so code.py and core/tools.py are covered too."""
    res = await run_isolated("import os\nprint(os.getcwd())", timeout=10)
    assert not res.get("ok")
    assert "not allowed" in res.get("error", "")


@pytest.mark.asyncio
async def test_memory_limit_still_enforced():
    """The rlimit path must keep working after the refactor."""
    res = await run_isolated(
        "big = bytearray(400 * 1024 * 1024)\nprint('allocated')\n",
        timeout=20,
        max_memory_mb=128,
    )
    assert not res.get("ok")