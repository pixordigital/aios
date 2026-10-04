"""Narrow Starlette form fields to the type the handler means.

`request.form().get(name)` returns `UploadFile | str`, so every
`(form.get("x") or "").strip()` in this codebase is a union-attr error mypy is
right about: if that field ever arrives as a file upload, `.strip()` raises.
These two helpers are the single place that decision lives, instead of forty
inline `isinstance` checks that would each rot independently.
"""

from starlette.datastructures import FormData
from starlette.datastructures import UploadFile as StarletteUploadFile


def fstr(form: FormData, name: str, default: str = "") -> str:
    """A form field as text, exactly as `(form.get(name) or default).strip()`.

    A file upload in a text field is treated as missing rather than crashing:
    the handler asked for text and got a file, so the default wins.
    """
    value = form.get(name)
    if not isinstance(value, str):
        return default
    return (value or default).strip()


def ffile(form: FormData, name: str) -> StarletteUploadFile | None:
    """A form field as an upload, or None when it is not one."""
    value = form.get(name)
    return value if isinstance(value, StarletteUploadFile) else None
