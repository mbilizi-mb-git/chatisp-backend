import asyncio
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
from app.services.rag_singleton import get_rag_service as get_global_rag_service

router = APIRouter(tags=["Messages"])
logger = logging.getLogger(__name__)


async def get_rag_service() -> RagService:
    """Retourne l'instance singleton de RagService (préchargée au démarrage)."""
    service = get_global_rag_service()
    if service is None:
        raise HTTPException(status_code=503, detail="RagService non disponible (démarrage en cours)")
    return service


@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    body: MessageCreate,
    rag: RagService = Depends(get_rag_service),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Envoie un message et reçoit une réponse en streaming (SSE)."""
    # Vérifier la conversation
    conv_service = ConversationService(db)
    conv = await conv_service.get_conversation(body.conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

    msg_service = MessageService(db)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for token in rag.process_message_stream(
                conversation_id=body.conversation_id,
                user_message=body.content,
                db=db,  # <-- PASSER LA SESSION EXPLICITEMENT
            ):
                if await request.is_disconnected():
                    logger.debug("Client déconnecté, arrêt du stream")
                    break
                chunk = ChatStreamChunk(token=token)
                yield f"data: {chunk.model_dump_json()}\n\n"

            if await request.is_disconnected():
                return

            last_messages = await msg_service.get_last_messages(body.conversation_id, limit=1)
            if last_messages and last_messages[0].role == "assistant":
                message_id = last_messages[0].id
            else:
                logger.error("Aucun message assistant trouvé après le stream")
                message_id = ""

            final_chunk = ChatStreamChunk(done=True, message_id=message_id)
            yield f"data: {final_chunk.model_dump_json()}\n\n"

        except asyncio.CancelledError:
            logger.debug("Stream annulé")
            raise
        except Exception as e:
            logger.exception("Erreur dans le stream chat")
            error_chunk = ChatStreamChunk(token="[Erreur lors de la génération]")
            yield f"data: {error_chunk.model_dump_json()}\n\n"
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


@router.get("/conversations/{conversation_id}/messages", response_model=Dict[str, Any])
async def get_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    before: Optional[datetime] = Query(None, description="Curseur : messages avant cette date"),
) -> Dict[str, Any]:
    conv_service = ConversationService(db)
    conv = await conv_service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

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
    conv_service = ConversationService(db)
    conv = await conv_service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

    msg_service = MessageService(db)

    last_messages = await msg_service.get_last_messages(conversation_id, limit=2)
    if len(last_messages) < 1:
        raise HTTPException(status_code=400, detail="Aucun message à régénérer")

    if last_messages[-1].role == "assistant":
        if len(last_messages) >= 2:
            user_msg_content = last_messages[-2].content
            await msg_service.delete_message(last_messages[-1].id)
        else:
            raise HTTPException(status_code=400, detail="Aucun message utilisateur associé")
    elif last_messages[-1].role == "user":
        user_msg_content = last_messages[-1].content
    else:
        raise HTTPException(status_code=400, detail="Rôle de message inattendu")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for token in rag.process_message_stream(
                conversation_id=conversation_id,
                user_message=user_msg_content,
                db=db,  # <-- PASSER LA SESSION EXPLICITEMENT
            ):
                if await request.is_disconnected():
                    break
                chunk = ChatStreamChunk(token=token)
                yield f"data: {chunk.model_dump_json()}\n\n"

            if await request.is_disconnected():
                return

            last_msgs = await msg_service.get_last_messages(conversation_id, limit=1)
            if last_msgs and last_msgs[0].role == "assistant":
                message_id = last_msgs[0].id
            else:
                logger.error("Aucun message assistant après régénération")
                message_id = ""

            final_chunk = ChatStreamChunk(done=True, message_id=message_id)
            yield f"data: {final_chunk.model_dump_json()}\n\n"

        except asyncio.CancelledError:
            logger.debug("Stream de régénération annulé")
            raise
        except Exception as e:
            logger.exception("Erreur dans la régénération")
            yield f"data: {ChatStreamChunk(token='[Erreur]').model_dump_json()}\n\n"
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