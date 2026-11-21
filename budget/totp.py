"""Second facteur : code à 6 chiffres qui change toutes les 30 secondes (TOTP, RFC 6238).

Bibliothèque standard uniquement. Compatible Google Authenticator, Aegis, 2FAS, etc.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def code_at(secret: str, when: float | None = None) -> str:
    return _code(secret, int((when if when is not None else time.time()) // STEP))


def verify(secret: str, code: str, last_step: int = 0, when: float | None = None) -> int | None:
    """Renvoie le pas de temps accepté, ou None.

    Tolère 30 s de décalage d'horloge de chaque côté. Un pas déjà utilisé est refusé :
    un code intercepté ne peut pas resservir.
    """
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = int((when if when is not None else time.time()) // STEP)
    for step in (now, now - 1, now + 1):
        if step > last_step and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def uri(secret: str, account: str = "Fred", issuer: str = "Budget") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def new_recovery_codes(n: int = 8) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]


def hash_recovery(code: str) -> str:
    return hashlib.sha256("".join(code.lower().split()).encode()).hexdigest()
