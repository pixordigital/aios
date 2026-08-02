"""File validation — magic byte signatures and type enforcement."""

import logging

logger = logging.getLogger(__name__)

# (magic_bytes, offset, mime_type, is_blocked, extra_check)
_MAGIC_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", False),
    (b"\xff\xd8\xff", 0, "image/jpeg", False),
    (b"GIF87a", 0, "image/gif", False),
    (b"GIF89a", 0, "image/gif", False),
    (b"RIFF", 0, "image/webp", False, lambda d: d[8:12] == b"WEBP"),
    (b"<?xml ", 0, None, True),  # SVG blocked — XSS vector, no sanitizer yet
    (b"<svg", 0, None, True),
    (b"%PDF", 0, "application/pdf", False),
    (b"PK\x03\x04", 0, None, True),
    (b"MZ", 0, None, True),
    (b"#!/", 0, None, True),
    (b"#! ", 0, None, True),
    (b"\x7fELF", 0, None, True),
]

# Extensions blocked regardless of magic bytes
_BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif",
                       ".sh", ".bash", ".zsh", ".dll", ".so", ".dylib",
                       ".jar", ".class", ".wasm", ".app", ".xap"}


def validate_file(filename: str, content: bytes) -> tuple[bool, str]:
    """Validate file content and extension.

    Returns (is_valid, reason). If valid, reason is the detected content-type.
    """
    ext = _get_extension(filename)
    if ext in _BLOCKED_EXTENSIONS:
        logger.warning("Blocked file extension: %s", filename)
        return False, f"File type '{ext}' is not allowed"

    sig_result = _check_magic(content)
    if not sig_result:
        # Unknown type — allow but flag as generic
        logger.info("Unknown file type: %s (size=%d)", filename, len(content))
        return True, "application/octet-stream"

    detected_type, is_blocked = sig_result
    if is_blocked:
        logger.warning("Blocked file content: %s", filename)
        return False, "File content is not allowed"

    return True, detected_type


def _get_extension(filename: str) -> str:
    """Extract lowercase extension from filename."""
    if not filename or "." not in filename:
        return ""
    # Get the last extension only
    parts = filename.rsplit(".", 1)
    return "." + parts[-1].lower() if len(parts) > 1 else ""


def _check_magic(content: bytes) -> tuple[str, bool] | None:
    """Check content against magic byte signatures.

    Returns (mime_type, is_blocked) or None if unknown.
    """
    for sig in _MAGIC_SIGNATURES:
        magic = sig[0]
        offset = sig[1]
        mime = sig[2]
        if len(content) < offset + len(magic):
            continue
        if content[offset : offset + len(magic)] == magic:
            # extra validation function
            if len(sig) >= 5 and callable(sig[4]):
                if not sig[4](content):
                    continue
            blocked = len(sig) >= 4 and sig[3] is True
            return (mime or "application/octet-stream", blocked)
    return None
