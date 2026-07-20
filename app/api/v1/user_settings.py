from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.db.deps import get_db
from app.db.models import User, UserSetting
from app.core.user_cache import cache_user
from app.core.security import get_current_user
from app.api.v1.schemas import UserSettingRead, UserSettingUpdate


router = APIRouter(prefix="/users/settings", tags=["user-settings"])


@router.get("", response_model=UserSettingRead)
def read_user_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSetting:
    return _get_or_create_user_settings(db, current_user)


@router.patch("", response_model=UserSettingRead)
def update_user_settings(
    settings_in: UserSettingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSetting:
    user_settings = _get_or_create_user_settings(db, current_user)
    user_settings.allow_incoming_messages = settings_in.allow_incoming_messages
    db.commit()
    db.refresh(user_settings)
    cache_user(db, current_user)
    return user_settings


def _get_or_create_user_settings(db: Session, user: User) -> UserSetting:
    user_settings = db.scalar(select(UserSetting).where(UserSetting.user_id == user.id))
    if user_settings is not None:
        return user_settings

    user_settings = UserSetting(user_id=user.id)
    db.add(user_settings)
    db.commit()
    db.refresh(user_settings)
    return user_settings
