from __future__ import annotations

import datetime as dt

import jwt
import bcrypt

from app.config import jwt_secret


def hash_password(password: str) -> str:
    # bcrypt stores algorithm + cost + salt in the resulting hash string.
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        # Invalid hash format.
        return False
    except Exception:
        return False


def create_access_token(*, user_id: int, role: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": int(now.timestamp())}
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, jwt_secret(), algorithms=["HS256"])

