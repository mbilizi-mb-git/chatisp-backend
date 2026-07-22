from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict, StringConstraints
from typing_extensions import Annotated

from app.schemas.message import MessageOut


# Title validation: max 200 characters
TitleStr = Annotated[str, StringConstraints(max_length=200)]


class ConversationCreate(BaseModel):
    """Empty request body for creating a new conversation."""
    pass


class ConversationRename(BaseModel):
    """Request body for renaming a conversation."""

    title: TitleStr = Field(..., description="New conversation title (max 200 characters)")


class ConversationPin(BaseModel):
    """Request body for pinning/unpinning a conversation."""

    is_pinned: bool = Field(..., description="True to pin, False to unpin")


class ConversationOut(BaseModel):
    """Conversation summary returned in list views."""

    id: str = Field(..., description="Conversation ID (UUID4)")
    title: Optional[str] = Field(None, description="Conversation title (nullable)")
    is_pinned: bool = Field(..., description="Whether the conversation is pinned")
    pinned_at: Optional[datetime] = Field(None, description="When it was pinned (null if not pinned)")
    updated_at: datetime = Field(..., description="Last update timestamp")
    preview: Optional[str] = Field(None, description="Preview of the last message (max 120 chars)")

    model_config = ConfigDict(from_attributes=True)


class ConversationDetail(BaseModel):
    """Detailed conversation view, optionally including messages."""

    id: str = Field(..., description="Conversation ID (UUID4)")
    title: Optional[str] = Field(None, description="Conversation title")
    is_pinned: bool = Field(..., description="Pinned status")
    pinned_at: Optional[datetime] = Field(None, description="Pin timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    messages: Optional[List[MessageOut]] = Field(
        default=None,
        description="List of messages (if requested)"
    )

    model_config = ConfigDict(from_attributes=True)