import json
import re

_EXPR_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")

def _get_path(ctx: dict, path: str):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except Exception:
                return None
        else:
            return getattr(cur, part, None)
        if cur is None:
            return None
    return cur

def _eval_expr(expr: str, ctx: dict):
    expr = expr.strip()
    if expr.startswith("$"):
        return _get_path(ctx, expr[1:].lstrip("."))
    if "." in expr and not any(c in expr for c in " +-*/()[]'\""):
        v = _get_path(ctx, expr)
        if v is not None:
            return v
    try:
        import ast
        tree = ast.parse(expr, mode="eval")
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                return None
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("__import__","eval","exec","open","compile"):
                return None
        return eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, ctx)
    except Exception:
        return None

def render_template(template: str, ctx: dict) -> str:
    if not isinstance(template, str):
        return template
    if not _EXPR_RE.search(template):
        return template
    if re.fullmatch(r"\{\{\s*.+?\s*\}\}", template.strip()):
        inner = _EXPR_RE.search(template).group(1)
        v = _eval_expr(inner, ctx)
        if v is not None:
            return v if not isinstance(v, str) else v
        return template
    def repl(m):
        v = _eval_expr(m.group(1), ctx)
        if v is None:
            return m.group(0)
        return json.dumps(v) if isinstance(v, (dict, list)) else str(v)
    return _EXPR_RE.sub(repl, template)

def render_value(value, ctx: dict):
    if isinstance(value, str):
        rendered = render_template(value, ctx)
        return rendered
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    return value

def render_mapping(mapping: dict, ctx: dict) -> dict:
    return {k: render_value(v, ctx) for k, v in mapping.items()}
