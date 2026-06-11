import logging
from datetime import datetime
from typing import Optional, List, Tuple
from uuid import uuid4

from sqlalchemy import select, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MessageService:
    """Service for message operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> Message:
        """Create and store a new message."""
        msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        logger.info("Message created", extra={"msg_id": msg.id, "conv_id": conversation_id, "role": role})
        return msg

    async def get_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 20,
        before: Optional[datetime] = None,
    ) -> Tuple[List[Message], Optional[datetime]]:
        """
        Retrieve messages for a conversation, paginated by created_at (cursor).
        Returns (messages, next_cursor) where next_cursor is the created_at of the last message.
        """
        query = select(Message).where(Message.conversation_id == conversation_id)
        if before:
            query = query.where(Message.created_at < before)

        query = query.order_by(Message.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(query)
        msgs = result.scalars().all()

        next_cursor = None
        if len(msgs) > limit:
            next_cursor = msgs[limit].created_at
            msgs = msgs[:limit]

        # Return in ascending order for client convenience
        msgs.reverse()
        return list(msgs), next_cursor

    async def get_last_messages(
        self,
        conversation_id: str,
        limit: int = 10,
    ) -> List[Message]:
        """Retrieve the most recent N messages in a conversation (for memory)."""
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        msgs = result.scalars().all()
        # Return in chronological order
        return list(reversed(msgs))

    async def get_preview(self, conversation_id: str, max_chars: int = 120) -> str:
        """
        Return a preview of the last assistant message (or user if none).
        If no messages, return empty string.
        """
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = result.scalar_one_or_none()
        if not last_msg:
            return ""
        preview = last_msg.content[:max_chars].replace("\n", " ")
        if len(last_msg.content) > max_chars:
            preview += "…"
        return preview

    async def delete_message(self, message_id: str) -> None:
        """Delete a single message by its ID."""
        stmt = delete(Message).where(Message.id == message_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        if result.rowcount == 0:
            raise ValueError(f"Message {message_id} not found")
        logger.info("Message deleted", extra={"msg_id": message_id})