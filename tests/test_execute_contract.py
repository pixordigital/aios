"""DatabaseBackend.execute() call-shape tests.

Regression: DatabaseBackend.execute(self, stmt) takes a single argument, but
several call sites passed a params dict positionally. That raised TypeError at
runtime — and where it sat inside `except Exception: pass`, the guarded code
silently never ran (the registration blacklist was never enforced).
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "aios"


def _wrapper_execute_calls():
    """Yield (file, line) of execute(<raw sql>, <params>) inside wrapper files.

    Only files that use our DatabaseBackend are scanned: a real SQLAlchemy
    AsyncSession legitimately accepts (stmt, params), so a blind scan flags
    those as false positives.
    """
    out = []
    for p in sorted(SRC.rglob("*.py")):
        text = p.read_text()
        if "DatabaseBackend" not in text and "get_db_backend" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr != "execute" or len(n.args) < 2 or n.keywords:
                continue
            a = n.args[0]
            raw = (isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id == "text") or (
                isinstance(a, ast.Constant) and isinstance(a.value, str)
            )
            if raw:
                out.append((p, n.lineno))
    return out


def test_no_wrapper_execute_with_positional_params():
    """No execute(<text>, <dict>) may remain in aios/.

    Every hit must either be a raw DB-API connection (renamed away below) or
    have been converted to .bindparams().
    """
    offenders = []
    for p, line in _wrapper_execute_calls():
        src = p.read_text().splitlines()
        # raw DB-API connections (conn.execute / c.execute) are valid
        snippet = "\n".join(src[max(0, line - 12) : line])
        if ".execute(" in snippet and any(
            f"{r}.execute(" in snippet for r in ("conn", "cur", "c", "raw")
        ):
            continue
        offenders.append(f"{p.relative_to(SRC)}:{line}")
    assert not offenders, "execute() called with positional params:\n" + "\n".join(offenders)


@pytest.mark.parametrize("mod", ["aios.core.limits", "aios.api.auth", "aios.api.license"])
def test_module_uses_bindparams(mod):
    import importlib

    m = importlib.import_module(mod)
    src = Path(m.__file__).read_text()
    assert ".bindparams(" in src, f"{mod} should bind params instead of passing a dict"


def test_backend_execute_takes_one_arg():
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

    import inspect

    params = list(inspect.signature(SQLAlchemyBackend.execute).parameters)
    # self, stmt -> exactly two entries, one positional beyond self
    assert len(params) == 2, f"execute() signature changed: {params}"
