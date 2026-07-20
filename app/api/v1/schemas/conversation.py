from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ConversationType, MessageType


class DirectConversationCreate(BaseModel):
    user_id: UUID


class ReportConversationCreate(BaseModel):
    report_id: UUID
    title: str | None = Field(default=None, max_length=255)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_type: ConversationType
    title: str | None
    report_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ConversationMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    user_id: UUID
    last_read_message_id: UUID | None
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    sender_id: UUID
    message_type: MessageType
    body: str
    edited_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationDetailRead(ConversationRead):
    members: list[ConversationMemberRead]
    last_message: MessageRead | None = None


class MarkConversationRead(BaseModel):
    message_id: UUID
