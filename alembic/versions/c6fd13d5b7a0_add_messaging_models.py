"""add messaging models

Revision ID: c6fd13d5b7a0
Revises: 98ce9d26d3e8
Create Date: 2026-07-20 17:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c6fd13d5b7a0"
down_revision: Union[str, Sequence[str], None] = "98ce9d26d3e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conversation_type = postgresql.ENUM(
        "DIRECT",
        "GROUP",
        "REPORT",
        name="conversation_type",
        create_type=False,
    )
    message_type = postgresql.ENUM(
        "TEXT",
        "SYSTEM",
        name="message_type",
        create_type=False,
    )
    postgresql.ENUM(
        "DIRECT",
        "GROUP",
        "REPORT",
        name="conversation_type",
    ).create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "TEXT",
        "SYSTEM",
        name="message_type",
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "conversations",
        sa.Column("conversation_type", conversation_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversation_members",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_message_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "user_id",
            name="uq_conversation_members_conversation_id_user_id",
        ),
    )
    op.create_index(
        "ix_conversation_members_user_id",
        "conversation_members",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", message_type, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_conversation_id_created_at",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_messages_sender_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id_created_at", table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        "ix_conversation_members_user_id",
        table_name="conversation_members",
    )
    op.drop_table("conversation_members")
    op.drop_table("conversations")
    sa.Enum(name="message_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="conversation_type").drop(op.get_bind(), checkfirst=True)
