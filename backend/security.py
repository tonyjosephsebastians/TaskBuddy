from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from backend.config import JWT_ALGORITHM, JWT_EXPIRATION_HOURS, JWT_SECRET, PBKDF2_ITERATIONS
from backend.errors import AppError
from backend.models import UserAccount


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return password_hash.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    computed_hash, _ = hash_password(password, bytes.fromhex(password_salt))
    return hmac.compare_digest(computed_hash, password_hash)


def create_access_token(user: UserAccount) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role,
        "exp": expires_at,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as error:
        raise AppError("AUTH_INVALID", "Authentication token is invalid.", 401) from error
    return payload
