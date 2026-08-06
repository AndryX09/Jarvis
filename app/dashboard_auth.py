from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from pathlib import Path
import secrets
import struct


def load_totp_secret(path_text: str) -> bytes:
    path = Path(path_text)
    if path.is_symlink():
        raise ValueError("JARVIS_DASHBOARD_TOTP_SECRET_FILE must not be a symbolic link")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > 256:
        raise ValueError("JARVIS_DASHBOARD_TOTP_SECRET_FILE must be a small regular file")
    encoded = resolved.read_bytes().rstrip(b"\r\n")
    if not encoded or b"\n" in encoded or b"\r" in encoded:
        raise ValueError("JARVIS_DASHBOARD_TOTP_SECRET_FILE must contain one Base32 secret")
    try:
        secret = base64.b32decode(encoded, casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "JARVIS_DASHBOARD_TOTP_SECRET_FILE must contain valid Base32"
        ) from exc
    if len(secret) < 20:
        raise ValueError(
            "JARVIS_DASHBOARD_TOTP_SECRET_FILE must contain at least 160 bits"
        )
    return secret


def _totp_code(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def matching_totp_counter(
    secret: bytes,
    code: str,
    *,
    now: int,
    window: int = 1,
) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current_counter = now // 30
    for delta in range(-window, window + 1):
        counter = current_counter + delta
        if counter >= 0 and hmac.compare_digest(_totp_code(secret, counter), code):
            return counter
    return None


def verify_totp(
    secret: bytes,
    code: str,
    *,
    now: int,
    window: int = 1,
) -> bool:
    return matching_totp_counter(secret, code, now=now, window=window) is not None


def _session_signature(secret: bytes, payload: str) -> str:
    key = hmac.new(secret, b"jarvis-dashboard-session-v1", hashlib.sha256).digest()
    return hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()


def create_session_token(secret: bytes, *, now: int) -> str:
    payload = f"{now}.{secrets.token_urlsafe(24)}"
    return f"{payload}.{_session_signature(secret, payload)}"


def validate_session_token(
    secret: bytes,
    token: str,
    *,
    now: int,
    max_age_seconds: int,
) -> bool:
    if len(token) > 512:
        return False
    try:
        issued_text, nonce, signature = token.split(".", 2)
        issued_at = int(issued_text)
    except (TypeError, ValueError):
        return False
    if not nonce or str(issued_at) != issued_text:
        return False
    age = now - issued_at
    if age < 0 or age > max_age_seconds:
        return False
    payload = f"{issued_text}.{nonce}"
    return hmac.compare_digest(_session_signature(secret, payload), signature)
