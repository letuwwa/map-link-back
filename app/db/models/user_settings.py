from uuid import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base_model import BaseModel


class UserSetting(BaseModel):
    __tablename__ = "user_settings"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    allow_incoming_messages: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
