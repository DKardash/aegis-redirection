import hmac
import hashlib
import secrets
import time
import base64
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

from .config import settings
from .db import (
    delete_all_sessions,
    delete_session,
    get_setting,
    load_session,
    save_session,
    set_setting,
)

_tokens: Dict[str, float] = {}
_hits: Dict[str, Deque[float]] = defaultdict(lambda: deque())
ADMIN_PASSWORD_HASH_KEY = "admin_password_hash"
PASSWORD_ITERATIONS = 310_000


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    expires = time.time() + 60 * 60 * 12
    _tokens[token] = expires
    save_session(token, expires)
    return token


def delete_token(token: str) -> None:
    _tokens.pop(token, None)
    delete_session(token)


def verify_credentials(username: str, password: str) -> bool:
    stored_hash = get_setting(ADMIN_PASSWORD_HASH_KEY, "") or ""
    if not stored_hash and not settings.requires_password:
        return hmac.compare_digest(username, settings.admin_username)
    if not hmac.compare_digest(username, settings.admin_username):
        return False
    if stored_hash:
        return _verify_password_hash(password, stored_hash)
    return hmac.compare_digest(password, settings.admin_password)


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "$".join((
        "pbkdf2_sha256",
        str(PASSWORD_ITERATIONS),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ))


def _verify_password_hash(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def change_admin_password(current_password: str, new_password: str) -> tuple[bool, str]:
    if not verify_credentials(settings.admin_username, current_password):
        return False, "неверный текущий пароль"
    if len(new_password) < 8:
        return False, "новый пароль должен содержать минимум 8 символов"
    if len(new_password) > 128:
        return False, "новый пароль слишком длинный"
    if hmac.compare_digest(current_password, new_password):
        return False, "новый пароль должен отличаться от текущего"
    set_setting(ADMIN_PASSWORD_HASH_KEY, _password_hash(new_password))
    _tokens.clear()
    delete_all_sessions()
    return True, "пароль изменён"


def check_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    now = time.time()
    window = _hits[key]
    while window and window[0] < now - settings.rate_limit_window:
        window.popleft()
    if len(window) >= settings.rate_limit_max:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    window.append(now)


def _token_valid(token: str) -> bool:
    """Проверка токена: сначала in-memory, затем (после рестарта) — БД."""
    expires = _tokens.get(token)
    if expires is None:
        expires = load_session(token)
        if expires is not None:
            _tokens[token] = expires
    return expires is not None and expires > time.time()


def require_auth(request: Request) -> None:
    if not settings.requires_password and not get_setting(ADMIN_PASSWORD_HASH_KEY, ""):
        return
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token or not _token_valid(token):
        raise HTTPException(status_code=401, detail="unauthorized")
