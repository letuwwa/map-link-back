import jwt
from uuid import UUID
from uuid import uuid4
from typing import Any
from sqlalchemy import select
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, Request, status
from datetime import datetime, timedelta, timezone

from app.core import settings
from app.db.deps import get_db
from app.db.models import TokenBlocklist, User, UserRole


password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user: User) -> str:
    return _create_token(
        user=user,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user: User) -> str:
    return _create_token(
        user=user,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.InvalidTokenError as exc:
        raise _credentials_exception() from exc


def is_token_revoked(db: Session, jti: str) -> bool:
    token_id = db.scalar(select(TokenBlocklist.id).where(TokenBlocklist.jti == jti))
    return token_id is not None


def get_token_user(db: Session, payload: dict[str, Any], token_type: str) -> User:
    subject = payload.get("sub")
    jti = payload.get("jti")
    payload_token_type = payload.get("type")
    if subject is None or jti is None or payload_token_type != token_type:
        raise _credentials_exception()

    if is_token_revoked(db, jti):
        raise _credentials_exception()

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise _credentials_exception() from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_exception()

    return user


def _create_token(user: User, token_type: str, expires_delta: timedelta) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(expires_delta.total_seconds()),
    )
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "type": token_type,
        "jti": str(uuid4()),
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def get_access_token(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
) -> str:
    return _get_token_from_bearer_or_cookie(
        request=request,
        bearer_token=bearer_token,
        cookie_name=settings.access_token_cookie_name,
    )


def get_refresh_token(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
) -> str:
    return _get_token_from_bearer_or_cookie(
        request=request,
        bearer_token=bearer_token,
        cookie_name=settings.refresh_token_cookie_name,
    )


def _get_token_from_bearer_or_cookie(
    request: Request,
    bearer_token: str | None,
    cookie_name: str,
) -> str:
    if bearer_token is not None:
        return bearer_token

    cookie_token = request.cookies.get(cookie_name)
    if cookie_token is None:
        raise _credentials_exception()

    return cookie_token


def get_current_user(
    token: str = Depends(get_access_token),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    return get_token_user(db, payload, token_type="access")


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
