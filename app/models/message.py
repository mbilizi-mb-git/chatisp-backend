import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from .conversation import Conversation


class Message(Base):
    """Represents a single message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique message identifier (UUID4)",
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key to the conversation",
    )
    role: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        doc="Role of the message sender: 'user' or 'assistant'",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Message content (text)",
    )
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
        doc="Timestamp when the message was created",
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    # Indexes: fast retrieval of messages per conversation
    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_messages_role_valid"
        ),
    )

    def __repr__(self) -> str:
        return f"<Message id={self.id} role={self.role}>"