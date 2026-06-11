import logging
from datetime import datetime
from typing import Optional, List, AsyncGenerator, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.message import MessageCreate, MessageOut, ChatStreamChunk
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.services.rag_service import RagService
from app.rag.vector_store import VectorStore
from app.rag.llm_engine import LLMEngine
from app.core.config import get_settings

router = APIRouter(tags=["Messages"])
logger = logging.getLogger(__name__)
settings = get_settings()


async def get_rag_service(
    db: AsyncSession = Depends(get_db),
) -> RagService:
    """Dependency to build RagService with its dependencies."""
    vector_store = VectorStore()
    llm_engine = LLMEngine(vector_store)
    return RagService(db, vector_store, llm_engine)


@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    body: MessageCreate,
    rag: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Send a message and receive a streaming response (SSE).
    The stream ends with a chunk containing `done: true` and the `message_id` of the assistant's response.
    """
    # Verify conversation ownership
    conv_service = ConversationService(db)
    conv = await conv_service.get_conversation(body.conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_service = MessageService(db)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Stream tokens from the RAG service
            async for token in rag.process_message_stream(
                conversation_id=body.conversation_id,
                user_message=body.content,
            ):
                if await request.is_disconnected():
                    logger.debug("Client disconnected, stopping stream")
                    break
                chunk = ChatStreamChunk(token=token)
                yield f"data: {chunk.model_dump_json()}\n\n"

            # If client disconnected, stop without final chunk
            if await request.is_disconnected():
                return

            # After streaming, retrieve the last assistant message to get its ID
            last_messages = await msg_service.get_last_messages(body.conversation_id, limit=1)
            if last_messages and last_messages[0].role == "assistant":
                message_id = last_messages[0].id
            else:
                # Should never happen, but fallback
                logger.error("No assistant message found after stream", extra={"conv_id": body.conversation_id})
                message_id = ""

            final_chunk = ChatStreamChunk(done=True, message_id=message_id)
            yield f"data: {final_chunk.model_dump_json()}\n\n"

        except Exception as e:
            logger.exception("Error in chat stream", extra={"conv_id": body.conversation_id})
            error_chunk = ChatStreamChunk(token="[Error generating response]")
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            # Still send a done chunk to close the stream gracefully
            yield f"data: {ChatStreamChunk(done=True, message_id='').model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/conversations/{conversation_id}/messages", response_model=Dict[str, Any])
async def get_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    before: Optional[datetime] = Query(None, description="Cursor: only messages before this timestamp"),
) -> Dict[str, Any]:
    """
    Get paginated messages of a conversation.
    Returns an object with 'items' (list of messages) and 'next_cursor' (ISO timestamp of the last returned message).
    """
    # Verify ownership
    conv_service = ConversationService(db)
    conv = await conv_service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_service = MessageService(db)
    msgs, next_cursor_dt = await msg_service.get_conversation_messages(
        conversation_id=conversation_id,
        limit=limit,
        before=before,
    )

    items = [MessageOut.model_validate(m) for m in msgs]
    next_cursor = next_cursor_dt.isoformat() if next_cursor_dt else None
    return {"items": items, "next_cursor": next_cursor}


@router.post("/conversations/{conversation_id}/regenerate")
async def regenerate_response(
    conversation_id: str,
    request: Request,
    rag: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Regenerate the last assistant response for a conversation.
    Deletes the previous assistant message (if any) and streams a new response.
    The stream ends with a chunk containing `done: true` and the new message_id.
    """
    # Verify ownership
    conv_service = ConversationService(db)
    conv = await conv_service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_service = MessageService(db)

    # Get the last user message (the one before the assistant response)
    last_messages = await msg_service.get_last_messages(conversation_id, limit=2)
    if len(last_messages) < 1:
        raise HTTPException(status_code=400, detail="No messages to regenerate")
    # Expect last messages in chronological order (oldest first)
    # So the last message is the most recent.
    # We need the most recent user message. If the last message is assistant, then the previous is user.
    if last_messages[-1].role == "assistant":
        # There is an assistant message; delete it
        await msg_service.delete_message(last_messages[-1].id)
        # The user message is the one before it (if exists)
        if len(last_messages) >= 2:
            user_msg_content = last_messages[-2].content
        else:
            raise HTTPException(status_code=400, detail="No user message to regenerate from")
    elif last_messages[-1].role == "user":
        # Last message is user (maybe first message, no assistant yet)
        user_msg_content = last_messages[-1].content
        # No assistant to delete
    else:
        raise HTTPException(status_code=400, detail="Unexpected message role")

    # Now stream new response using the same user message
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for token in rag.process_message_stream(
                conversation_id=conversation_id,
                user_message=user_msg_content,
            ):
                if await request.is_disconnected():
                    break
                chunk = ChatStreamChunk(token=token)
                yield f"data: {chunk.model_dump_json()}\n\n"

            if await request.is_disconnected():
                return

            # Get the newly created assistant message
            last_msgs = await msg_service.get_last_messages(conversation_id, limit=1)
            if last_msgs and last_msgs[0].role == "assistant":
                message_id = last_msgs[0].id
            else:
                logger.error("No assistant message after regenerate", extra={"conv_id": conversation_id})
                message_id = ""

            final_chunk = ChatStreamChunk(done=True, message_id=message_id)
            yield f"data: {final_chunk.model_dump_json()}\n\n"

        except Exception as e:
            logger.exception("Error in regenerate stream", extra={"conv_id": conversation_id})
            yield f"data: {ChatStreamChunk(token='[Error]').model_dump_json()}\n\n"
            yield f"data: {ChatStreamChunk(done=True, message_id='').model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )