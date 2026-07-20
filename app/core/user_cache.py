import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import UserRead
from app.core.redis import create_sync_redis_client
from app.db.models import User, UserSetting


USER_CACHE_TTL_SECONDS = 60 * 60
logger = logging.getLogger(__name__)


def get_or_create_user_settings(db: Session, user: User) -> UserSetting:
    user_settings = db.scalar(select(UserSetting).where(UserSetting.user_id == user.id))
    if user_settings is None:
        user_settings = UserSetting(user_id=user.id)
        db.add(user_settings)
        db.commit()
        db.refresh(user_settings)

    return user_settings


def build_user_read(db: Session, user: User) -> UserRead:
    user_settings = get_or_create_user_settings(db, user)
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        allow_incoming_messages=user_settings.allow_incoming_messages,
        hide_me=user_settings.hide_me,
    )


def cache_user_read(user: UserRead) -> None:
    redis_client = create_sync_redis_client()
    try:
        redis_client.set(
            user_cache_key(user.id),
            user.model_dump_json(),
            ex=USER_CACHE_TTL_SECONDS,
        )
    finally:
        redis_client.close()


def try_cache_user_read(user: UserRead) -> None:
    try:
        cache_user_read(user)
    except Exception:
        logger.exception("Failed to cache user %s in Redis", user.id)
        return


def cache_user(db: Session, user: User) -> UserRead:
    user_out = build_user_read(db, user)
    cache_user_read(user_out)
    return user_out


def try_cache_user(db: Session, user: User) -> UserRead:
    user_out = build_user_read(db, user)
    try_cache_user_read(user_out)
    return user_out


def user_cache_key(user_id: object) -> str:
    return f"users:{user_id}"
