import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from .user import User
    from .message import Message


class Conversation(Base):
    """Represents a conversation thread belonging to a user."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique conversation identifier (UUID4)",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key to the user (device_id)",
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        doc="Conversation title (nullable, auto‑generated after first message)",
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether the conversation is pinned to the top",
    )
    pinned_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        default=None,
        doc="Timestamp when the conversation was pinned (null if not pinned)",
    )
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
        doc="Timestamp when the conversation was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        doc="Timestamp of the last update (new message, rename, pin toggle)",
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        doc="All messages belonging to this conversation",
    )

    # Indexes: for efficient listing by user, sorted by pinned and updated
    __table_args__ = (
        Index("ix_conversations_user_pinned_updated", "user_id", "is_pinned", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} user_id={self.user_id}>"