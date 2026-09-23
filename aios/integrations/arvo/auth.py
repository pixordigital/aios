"""Ambiente de autenticação service-to-service ARVO. HMAC stdlib, sem novas deps.

Holder do serviço: a chave é por-peer (service_key_id + service_key).
Sign: assina requisições outbound. Verify: valida inbound.
"""

import hashlib
import hmac
import secrets
import threading
import time

_PATH = "/api/integrations"
_CLOCK_SKEW = 300  # segundos de tolerância de timestamp

# ponytail: in-memory nonce dedup, per-process; DB processed-events se precisar cross-instance
_seen_nonces: dict[str, float] = {}
_lock = threading.Lock()


def _register_nonce(nonce: str) -> bool:
    """Registra nonce; retorna False se replay. Expira após 2× skew."""
    now = time.time()
    with _lock:
        for k, exp in list(_seen_nonces.items()):
            if exp < now:
                del _seen_nonces[k]
        if nonce in _seen_nonces:
            return False
        _seen_nonces[nonce] = now + _CLOCK_SKEW * 2
        return True


def _clear_nonces() -> None:
    with _lock:
        _seen_nonces.clear()


def _forget_nonce(nonce: str) -> None:
    with _lock:
        _seen_nonces.pop(nonce, None)


def _body_hash(body: bytes | None) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def _canonical(key_id: str, ts: str, nonce: str, method: str, path: str, bhash: str) -> str:
    return f"{key_id}.{ts}.{nonce}.{method}.{path}.{bhash}"


def sign_request(method: str, path: str, body: bytes | None, key_id: str, key: str) -> dict[str, str]:
    """Headers de assinatura para request outbound."""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    sig = hmac.new(
        key.encode(), _canonical(key_id, ts, nonce, method, path, _body_hash(body)).encode(), hashlib.sha256
    ).hexdigest()
    return {
        "X-Service-Key-Id": key_id,
        "X-Service-Timestamp": ts,
        "X-Service-Nonce": nonce,
        "X-Service-Signature": sig,
    }


def verify_request(
    key_id: str,
    ts: str,
    nonce: str,
    method: str,
    path: str,
    body: bytes | None,
    signature: str,
    key: str,
) -> bool:
    """Valida assinatura inbound. Segurança:
    - comparação constante de tempo contra leak de canal lateral (hmac.compare_digest)
    - janela de timestamp contra replay
    - nonce dedup via _register_nonce (Fase 2); retorna False se replay."""
    if not all([key_id, ts, nonce, signature, key]):
        return False
    try:
        if abs(int(time.time()) - int(ts)) > _CLOCK_SKEW:
            return False
    except ValueError:
        return False

    expected = hmac.new(
        key.encode(),
        _canonical(key_id, ts, nonce, method, path, _body_hash(body)).encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    # só registra nonce se assinatura válida, evita encher com lixo
    if not _register_nonce(nonce):
        return False
    return True


if __name__ == "__main__":
    kid, key = "test-kid", "test-secret"
    _clear_nonces()
    hdr = sign_request("POST", _PATH, b"{}", kid, key)
    assert verify_request(
        kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "POST", _PATH, b"{}", hdr["X-Service-Signature"], key
    )
    # replay mesma nonce deve falhar
    assert not verify_request(
        kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "POST", _PATH, b"{}", hdr["X-Service-Signature"], key
    )
    _clear_nonces()
    assert not verify_request(
        kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "POST", _PATH, b"{}", hdr["X-Service-Signature"], "wrong-key"
    )
    assert not verify_request(
        kid, str(int(time.time()) - 9999), "n2", "POST", _PATH, b"{}", hdr["X-Service-Signature"], key
    )
    print("auth self-check OK")
