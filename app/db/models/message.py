import enum
from uuid import UUID
from datetime import datetime

from sqlalchemy import (
    Enum,
    Index,
    String,
    Text,
    Uuid,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base_model import BaseModel


class ConversationType(str, enum.Enum):
    DIRECT = "direct"
    GROUP = "group"
    REPORT = "report"


class MessageType(str, enum.Enum):
    TEXT = "text"
    SYSTEM = "system"


class Conversation(BaseModel):
    __tablename__ = "conversations"

    conversation_type: Mapped[ConversationType] = mapped_column(
        Enum(ConversationType, name="conversation_type"),
        default=ConversationType.DIRECT,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    )


class ConversationMember(BaseModel):
    __tablename__ = "conversation_members"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "user_id",
            name="uq_conversation_members_conversation_id_user_id",
        ),
        Index("ix_conversation_members_user_id", "user_id"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_read_message_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )


class Message(BaseModel):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_messages_sender_id", "sender_id"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type"),
        default=MessageType.TEXT,
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
