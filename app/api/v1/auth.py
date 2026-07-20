from typing import Annotated
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status

from app.core import settings
from app.db.deps import get_db
from app.api.v1.schemas import UserRegister, UserRead
from app.core.user_cache import try_cache_user
from app.db.models import TokenBlocklist, User, UserRole, UserSetting
from app.api.v1.schemas import AccessToken, AuthResponse, TokenPair
from app.core.security import (
    decode_token,
    oauth2_scheme,
    require_admin,
    hash_password,
    get_refresh_token,
    get_token_user,
    verify_password,
    get_current_user,
    create_access_token,
    create_refresh_token,
)


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginForm:
    def __init__(
        self,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> None:
        self.username = username
        self.password = password


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    user_in: UserRegister,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, UserRead | TokenPair]:
    existing_user = db.scalar(
        select(User).where(
            or_(
                User.email == user_in.email,
                User.username == user_in.username,
            )
        )
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already exists",
        )

    user = User(
        email=user_in.email,
        username=user_in.username,
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        hashed_password=hash_password(user_in.password),
        role=UserRole.REGULAR,
    )

    db.add(user)
    try:
        db.flush()
        db.add(UserSetting(user_id=user.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already exists",
        ) from exc

    db.refresh(user)
    user_out = try_cache_user(db, user)
    tokens = _create_token_pair(user)
    _set_auth_cookies(response, tokens)
    return {
        "user": user_out,
        "tokens": tokens,
    }


@router.post("/login", response_model=AuthResponse)
def login_user(
    response: Response,
    form_data: LoginForm = Depends(),
    db: Session = Depends(get_db),
) -> dict[str, UserRead | TokenPair]:
    user = _authenticate_user(
        db=db,
        username=form_data.username,
        password=form_data.password,
    )
    user_out = try_cache_user(db, user)
    tokens = _create_token_pair(user)
    _set_auth_cookies(response, tokens)
    return {
        "user": user_out,
        "tokens": tokens,
    }


@router.post("/token", response_model=TokenPair)
def token_user(
    response: Response,
    form_data: LoginForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenPair:
    user = _authenticate_user(
        db=db,
        username=form_data.username,
        password=form_data.password,
    )
    tokens = _create_token_pair(user)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/refresh", response_model=AccessToken)
def refresh_token(
    response: Response,
    token: str = Depends(get_refresh_token),
    db: Session = Depends(get_db),
) -> AccessToken:
    payload = decode_token(token)
    user = get_token_user(db, payload, token_type="refresh")
    access_token = create_access_token(user)
    _set_access_token_cookie(response, access_token)
    return AccessToken(access_token=access_token)


@router.post("/logout")
def logout_user(
    response: Response,
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    revoked_tokens = 0
    for token in _get_logout_tokens(request, bearer_token):
        revoked_tokens += _add_token_to_blocklist(db, token)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

    _clear_auth_cookies(response)
    return {
        "message": "Logged out",
        "revoked_tokens": revoked_tokens,
    }


@router.get("/me", response_model=UserRead)
def read_current_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRead:
    return try_cache_user(db, current_user)


@router.get("/admin-only")
def read_admin_only(
    current_user: User = Depends(require_admin),
) -> dict[str, str]:
    return {
        "message": "Admin access granted",
        "user_id": str(current_user.id),
    }


def _create_token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


def _set_auth_cookies(response: Response, tokens: TokenPair) -> None:
    _set_access_token_cookie(response, tokens.access_token)
    response.set_cookie(
        key=settings.refresh_token_cookie_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _set_access_token_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.access_token_cookie_name,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )
    response.delete_cookie(
        key=settings.refresh_token_cookie_name,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _get_logout_tokens(request: Request, bearer_token: str | None) -> list[str]:
    tokens = [
        token
        for token in (
            bearer_token,
            request.cookies.get(settings.access_token_cookie_name),
            request.cookies.get(settings.refresh_token_cookie_name),
        )
        if token is not None
    ]
    return list(dict.fromkeys(tokens))


def _add_token_to_blocklist(db: Session, token: str) -> int:
    try:
        payload = decode_token(token)
        token_type = payload.get("type")
        if token_type not in {"access", "refresh"}:
            return 0

        user = get_token_user(db, payload, token_type=token_type)
    except HTTPException:
        return 0

    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    revoked_token = TokenBlocklist(
        jti=payload["jti"],
        token_type=payload["type"],
        user_id=str(user.id),
        expires_at=expires_at,
    )
    db.add(revoked_token)
    return 1


def _authenticate_user(db: Session, username: str, password: str) -> User:
    user = db.scalar(
        select(User).where(
            or_(
                User.email == username,
                User.username == username,
            )
        )
    )
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user
