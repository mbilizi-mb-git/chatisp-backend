"""Schémas Pydantic pour l'ensemble de l'API ChatISP AI."""

from app.schemas.conversation import (
    ConversationCreate,
    ConversationRename,
    ConversationPin,
    ConversationOut,
    ConversationDetail,
)
from app.schemas.message import (
    MessageCreate,
    MessageOut,
    ChatStreamChunk,
    RegenerateRequest,
)
from app.schemas.auth import (
    Token,
    TokenPayload,
    LoginRequest,
    RegisterRequest,
    GoogleAuthRequest,
    RefreshTokenRequest,
    EmailCheckResponse,
    UserResponse,
)

__all__ = [
    "ConversationCreate",
    "ConversationRename",
    "ConversationPin",
    "ConversationOut",
    "ConversationDetail",
    "MessageCreate",
    "MessageOut",
    "ChatStreamChunk",
    "RegenerateRequest",
    "Token",
    "TokenPayload",
    "LoginRequest",
    "RegisterRequest",
    "GoogleAuthRequest",
    "RefreshTokenRequest",
    "EmailCheckResponse",
    "UserResponse",
]