"""Обфускация секретов (пароль MikroTik) ключом из SESSION_SECRET.

Использует HMAC-SHA256 в режиме счётчика как потоковый шифр — это защита
от чтения plaintext в БД, а не криптографическое шифрование. Формат хранения:
"enc:<base64>" или legacy plaintext.
"""

import base64
import hashlib
import hmac

from .config import settings


def _key() -> bytes:
    return hashlib.sha256((settings.session_secret or "change-me").encode("utf-8")).digest()


def _keystream(key: bytes, n: int) -> bytes:
    out = b""
    c = 0
    while len(out) < n:
        out += hmac.new(key, c.to_bytes(8, "big"), hashlib.sha256).digest()
        c += 1
    return out[:n]


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    data = plain.encode("utf-8")
    key = _key()
    enc = bytes(a ^ b for a, b in zip(data, _keystream(key, len(data))))
    return "enc:" + base64.urlsafe_b64encode(enc).decode("ascii")


def decrypt(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("enc:"):
        return value
    try:
        enc = base64.urlsafe_b64decode(value[4:])
    except Exception:  # noqa: BLE001
        return value
    key = _key()
    return bytes(a ^ b for a, b in zip(enc, _keystream(key, len(enc)))).decode("utf-8", "replace")
