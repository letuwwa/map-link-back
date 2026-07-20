from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import UserRead
from app.core.redis import create_sync_redis_client
from app.db.models import User, UserSetting


USER_CACHE_TTL_SECONDS = 60 * 60


def get_user_settings_value(db: Session, user: User) -> bool:
    user_settings = db.scalar(select(UserSetting).where(UserSetting.user_id == user.id))
    if user_settings is None:
        user_settings = UserSetting(user_id=user.id)
        db.add(user_settings)
        db.commit()
        db.refresh(user_settings)

    return user_settings.allow_incoming_messages


def build_user_read(db: Session, user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        allow_incoming_messages=get_user_settings_value(db, user),
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


def cache_user(db: Session, user: User) -> UserRead:
    user_out = build_user_read(db, user)
    cache_user_read(user_out)
    return user_out


def user_cache_key(user_id: object) -> str:
    return f"users:{user_id}"
