from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.db.deps import get_db
from app.db.models import User, UserSetting
from app.core.user_cache import get_or_create_user_settings, try_cache_user
from app.core.security import get_current_user
from app.api.v1.schemas import UserSettingRead, UserSettingUpdate


router = APIRouter(prefix="/users/settings", tags=["user-settings"])


@router.get("", response_model=UserSettingRead)
def read_user_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSetting:
    return get_or_create_user_settings(db, current_user)


@router.patch("", response_model=UserSettingRead)
def update_user_settings(
    settings_in: UserSettingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSetting:
    user_settings = get_or_create_user_settings(db, current_user)

    if settings_in.allow_incoming_messages is not None:
        user_settings.allow_incoming_messages = settings_in.allow_incoming_messages

    if settings_in.hide_me is not None:
        user_settings.hide_me = settings_in.hide_me

    db.commit()
    db.refresh(user_settings)
    try_cache_user(db, current_user)
    return user_settings
