from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator


class MessageCreate(BaseModel):
    """Request body for sending a new message."""

    conversation_id: str = Field(..., description="ID of the conversation")
    content: str = Field(..., description="Message content (text)")


class MessageOut(BaseModel):
    """Message data returned in history views."""

    id: str = Field(..., description="Message ID (UUID4)")
    role: str = Field(..., description="Sender role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    created_at: datetime = Field(..., description="Timestamp")

    model_config = ConfigDict(from_attributes=True)


class ChatStreamChunk(BaseModel):
    """One chunk in the SSE stream."""

    token: Optional[str] = Field(None, description="A token of the generated response")
    done: Optional[bool] = Field(None, description="Indicates end of stream")
    message_id: Optional[str] = Field(None, description="Final message ID (present when done=true)")

    @model_validator(mode="after")
    def check_exactly_one_field(self) -> "ChatStreamChunk":
        """Ensure exactly one of (token) or (done+message_id) is set."""
        if self.token is not None and (self.done is not None or self.message_id is not None):
            raise ValueError("Cannot set both token and done/message_id")
        if self.done is not None and self.message_id is None:
            raise ValueError("When done is True, message_id must be provided")
        if self.done is None and self.message_id is not None:
            raise ValueError("message_id can only be set when done is True")
        if self.token is None and self.done is None:
            raise ValueError("Either token or done must be set")
        return self


class RegenerateRequest(BaseModel):
    """Empty request body for regenerating a response."""
    pass