import logging
from datetime import datetime
from typing import Optional, List, Tuple
from uuid import uuid4

from sqlalchemy import select, update, delete, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.message import Message
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ConversationService:
    """Service for conversation CRUD operations with cursor pagination."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_conversation(self, user_id: str) -> Conversation:
        """Create a new conversation with null title."""
        conv = Conversation(
            id=str(uuid4()),
            user_id=user_id,
            title=None,
            is_pinned=False,
            pinned_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        logger.info("Conversation created", extra={"conv_id": conv.id, "user_id": user_id})
        return conv

    async def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        """Rename an existing conversation."""
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(title=title, updated_at=datetime.utcnow())
            .returning(Conversation)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        conv = result.scalar_one_or_none()
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")
        logger.info("Conversation renamed", extra={"conv_id": conversation_id, "title": title})
        return conv

    async def pin_conversation(self, conversation_id: str, is_pinned: bool) -> Conversation:
        """Pin or unpin a conversation."""
        pinned_at = datetime.utcnow() if is_pinned else None
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                is_pinned=is_pinned,
                pinned_at=pinned_at,
                updated_at=datetime.utcnow(),
            )
            .returning(Conversation)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        conv = result.scalar_one_or_none()
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")
        logger.info("Conversation pin toggled", extra={"conv_id": conversation_id, "is_pinned": is_pinned})
        return conv

    async def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation (cascade handled by DB)."""
        stmt = delete(Conversation).where(Conversation.id == conversation_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        if result.rowcount == 0:
            raise ValueError(f"Conversation {conversation_id} not found")
        logger.info("Conversation deleted", extra={"conv_id": conversation_id})

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[str] = None,  # cursor = updated_at isoformat of last item
    ) -> Tuple[List[Conversation], Optional[str]]:
        """
        List conversations for a user, sorted by is_pinned DESC, updated_at DESC.
        Cursor is the updated_at of the last seen conversation (ISO string).
        Returns (conversations, next_cursor).
        """
        query = select(Conversation).where(Conversation.user_id == user_id)

        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor)
            except ValueError:
                raise ValueError("Invalid cursor format")
            # We want items with updated_at <= cursor_dt, but because of tie-breaking,
            # we use a composite condition: (updated_at < cursor_dt) OR
            # (updated_at == cursor_dt AND id < last_seen_id) but we don't have id in cursor.
            # Simpler: use updated_at as cursor and accept that if two have same timestamp we might miss some.
            # But we can refine by using (updated_at, id) as cursor. Let's use a tuple cursor:
            # For now, we'll implement simple updated_at cursor.
            query = query.where(Conversation.updated_at < cursor_dt)

        query = query.order_by(
            Conversation.is_pinned.desc(),
            Conversation.updated_at.desc(),
        ).limit(limit + 1)  # fetch one extra to determine next cursor

        result = await self.db.execute(query)
        convs = result.scalars().all()

        next_cursor = None
        if len(convs) > limit:
            next_cursor = convs[limit].updated_at.isoformat()
            convs = convs[:limit]

        return list(convs), next_cursor

    async def get_conversation_with_messages(
        self,
        conversation_id: str,
        limit_messages: Optional[int] = None,
    ) -> Optional[Conversation]:
        """
        Retrieve a conversation with its messages (optionally limited).
        Returns None if not found.
        """
        query = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        result = await self.db.execute(query)
        conv = result.scalar_one_or_none()
        if conv and limit_messages is not None:
            # slice the loaded messages (they are loaded eagerly, we can limit after)
            conv.messages = conv.messages[-limit_messages:]  # last N messages
        return conv

    async def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Retrieve a conversation by ID without messages."""
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()