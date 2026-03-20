"""
JWT session service.
Token is stored in a single httponly cookie: `access_token`
Payload: { sub: user_id, name, email, exp, iat, auth_method }
"""

import os
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import Request
from sqlalchemy.orm import Session

SECRET_KEY     = os.getenv("JWT_SECRET_KEY", "change-this-secret-in-production-min-32-chars!!")
ALGORITHM      = "HS256"
COOKIE_NAME    = "access_token"

# Session duration — change as needed
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "8"))   # 8 hours default


def create_access_token(user_id: int, name: str, email: str, auth_method: str = "password") -> str:
    """Create a signed JWT token with expiry."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub":         str(user_id),
        "name":        name,
        "email":       email,
        "auth_method": auth_method,           # "password" | "microsoft_sso"
        "iat":         now,
        "exp":         now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Decode and validate token. Returns payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_token_from_request(request: Request) -> str | None:
    """Extract JWT from cookie."""
    return request.cookies.get(COOKIE_NAME)


def get_current_user_payload(request: Request) -> dict | None:
    """Get decoded payload from request cookie. Returns None if missing/invalid/expired."""
    token = get_token_from_request(request)
    if not token:
        return None
    return decode_token(token)


def set_token_cookie(response, token: str):
    """Set the JWT cookie on a response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,                          # JS cannot read it
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        samesite="lax",
        secure=False,                           # Set True in production with HTTPS
    )
    return response


def clear_token_cookie(response):
    """Delete the JWT cookie."""
    response.delete_cookie(COOKIE_NAME)
    return response


def get_user_from_token(request: Request, db: Session):
    """
    Resolve the current logged-in User from the JWT token.
    Returns User ORM object or None.
    Used as a drop-in replacement for the old cookie-based get_user_from_cookie().
    """
    from models import User  # local import to avoid circular
    payload = get_current_user_payload(request)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
        return db.query(User).filter(User.id == user_id).first()
    except Exception:
        return None