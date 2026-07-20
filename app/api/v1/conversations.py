from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.deps import get_db
from app.db.models import (
    User,
    Report,
    Message,
    Conversation,
    UserSetting,
    ConversationType,
    ConversationMember,
)
from app.core.security import get_current_user
from app.api.v1.schemas import (
    MessageRead,
    MessageCreate,
    ConversationDetailRead,
    MarkConversationRead,
    ReportConversationCreate,
    DirectConversationCreate,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "/direct",
    response_model=ConversationDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_direct_conversation(
    conversation_in: DirectConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationDetailRead:
    if conversation_in.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create a direct conversation with yourself",
        )

    other_user = db.get(User, conversation_in.user_id)
    if other_user is None or not other_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    conversation = _find_direct_conversation(
        db=db,
        user_id=current_user.id,
        other_user_id=conversation_in.user_id,
    )
    if conversation is None:
        _ensure_user_accepts_incoming_messages(db, conversation_in.user_id)

        conversation = Conversation(conversation_type=ConversationType.DIRECT)
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                ConversationMember(
                    conversation_id=conversation.id,
                    user_id=current_user.id,
                ),
                ConversationMember(
                    conversation_id=conversation.id,
                    user_id=conversation_in.user_id,
                ),
            ]
        )
        db.commit()
        db.refresh(conversation)

    return _conversation_detail(db, conversation)


@router.post(
    "/reports",
    response_model=ConversationDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_report_conversation(
    conversation_in: ReportConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationDetailRead:
    report = db.get(Report, conversation_in.report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    conversation = Conversation(
        conversation_type=ConversationType.REPORT,
        title=conversation_in.title,
        report_id=conversation_in.report_id,
    )
    db.add(conversation)
    db.flush()
    db.add(
        ConversationMember(
            conversation_id=conversation.id,
            user_id=current_user.id,
        )
    )
    db.commit()
    db.refresh(conversation)
    return _conversation_detail(db, conversation)


@router.get("", response_model=list[ConversationDetailRead])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationDetailRead]:
    conversations = db.scalars(
        select(Conversation)
        .join(ConversationMember)
        .where(ConversationMember.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    ).all()
    return [_conversation_detail(db, conversation) for conversation in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailRead)
def read_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationDetailRead:
    conversation = _get_user_conversation(db, conversation_id, current_user.id)
    return _conversation_detail(db, conversation)


@router.get("/{conversation_id}/messages", response_model=list[MessageRead])
def list_messages(
    conversation_id: UUID,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Message]:
    _get_user_conversation(db, conversation_id, current_user.id)
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(min(limit, 100))
            .offset(offset)
        ).all()
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    conversation_id: UUID,
    message_in: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    conversation = _get_user_conversation(db, conversation_id, current_user.id)
    if conversation.conversation_type == ConversationType.DIRECT:
        _ensure_direct_recipients_accept_incoming_messages(
            db=db,
            conversation_id=conversation.id,
            sender_id=current_user.id,
        )

    message = Message(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        body=message_in.body,
    )
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _ensure_direct_recipients_accept_incoming_messages(
    db: Session,
    conversation_id: UUID,
    sender_id: UUID,
) -> None:
    recipient_ids = db.scalars(
        select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id != sender_id,
        )
    ).all()

    for recipient_id in recipient_ids:
        _ensure_user_accepts_incoming_messages(db, recipient_id)


def _ensure_user_accepts_incoming_messages(db: Session, user_id: UUID) -> None:
    user_settings = db.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
    if user_settings is not None and not user_settings.allow_incoming_messages:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not accepting incoming messages",
        )


@router.post("/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: UUID,
    read_in: MarkConversationRead,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    _get_user_conversation(db, conversation_id, current_user.id)
    message = db.scalar(
        select(Message).where(
            Message.id == read_in.message_id,
            Message.conversation_id == conversation_id,
        )
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    member = _get_conversation_member(db, conversation_id, current_user.id)
    member.last_read_message_id = read_in.message_id
    db.commit()
    return {"message": "Conversation marked as read"}


def _find_direct_conversation(
    db: Session,
    user_id: UUID,
    other_user_id: UUID,
) -> Conversation | None:
    member_counts = (
        select(
            ConversationMember.conversation_id,
            func.count(ConversationMember.user_id).label("member_count"),
        )
        .group_by(ConversationMember.conversation_id)
        .subquery()
    )
    conversation_ids = (
        select(ConversationMember.conversation_id)
        .where(ConversationMember.user_id.in_([user_id, other_user_id]))
        .group_by(ConversationMember.conversation_id)
        .having(func.count(ConversationMember.user_id) == 2)
        .subquery()
    )
    return db.scalar(
        select(Conversation)
        .join(
            member_counts,
            member_counts.c.conversation_id == Conversation.id,
        )
        .where(
            Conversation.id.in_(select(conversation_ids.c.conversation_id)),
            Conversation.conversation_type == ConversationType.DIRECT,
            member_counts.c.member_count == 2,
        )
    )


def _get_user_conversation(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .join(ConversationMember)
        .where(
            Conversation.id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


def _get_conversation_member(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> ConversationMember:
    member = db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation member not found",
        )
    return member


def _conversation_detail(
    db: Session,
    conversation: Conversation,
) -> ConversationDetailRead:
    members = list(
        db.scalars(
            select(ConversationMember)
            .where(ConversationMember.conversation_id == conversation.id)
            .order_by(ConversationMember.created_at.asc())
        ).all()
    )
    last_message = db.scalar(
        select(Message)
        .where(
            and_(
                Message.conversation_id == conversation.id,
                Message.deleted_at.is_(None),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return ConversationDetailRead(
        id=conversation.id,
        conversation_type=conversation.conversation_type,
        title=conversation.title,
        report_id=conversation.report_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        members=members,
        last_message=last_message,
    )
