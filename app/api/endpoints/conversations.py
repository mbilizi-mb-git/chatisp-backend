"""
Endpoints pour la gestion des conversations : création, liste, renommage, épinglage, suppression.
"""

import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationRename,
    ConversationPin,
    ConversationOut,
    ConversationDetail,
)
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    body: ConversationCreate = None,
) -> ConversationOut:
    """Crée une nouvelle conversation pour l'utilisateur authentifié."""
    service = ConversationService(db)
    conv = await service.create_conversation(current_user.id)
    logger.info("Conversation créée", extra={"conv_id": conv.id, "user_id": current_user.id})
    return ConversationOut.model_validate(conv)


@router.get("", response_model=Dict[str, Any])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Curseur composite: updated_at,id"),
) -> Dict[str, Any]:
    """
    Liste les conversations de l'utilisateur avec pagination par curseur.
    Retourne un objet avec 'items' (liste des conversations) et 'next_cursor'.
    """
    service = ConversationService(db)
    msg_service = MessageService(db)

    convs, next_cursor = await service.list_conversations(
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
    )

    items = []
    for conv in convs:
        preview = await msg_service.get_preview(conv.id)
        out = ConversationOut.model_validate(conv)
        out.preview = preview
        items.append(out)

    return {"items": items, "next_cursor": next_cursor}


@router.put("/{conversation_id}/rename", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: str,
    body: ConversationRename,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationOut:
    """Renomme une conversation. L'utilisateur doit en être le propriétaire."""
    service = ConversationService(db)
    conv = await service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

    updated = await service.rename_conversation(conversation_id, body.title)
    logger.info("Conversation renommée", extra={"conv_id": conversation_id, "title": body.title})
    return ConversationOut.model_validate(updated)


@router.patch("/{conversation_id}/pin", response_model=ConversationOut)
async def pin_conversation(
    conversation_id: str,
    body: ConversationPin,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationOut:
    """Épingle ou désépingle une conversation."""
    service = ConversationService(db)
    conv = await service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

    updated = await service.pin_conversation(conversation_id, body.is_pinned)
    logger.info(
        "Épingle conversation modifiée",
        extra={"conv_id": conversation_id, "is_pinned": body.is_pinned},
    )
    return ConversationOut.model_validate(updated)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Supprime une conversation et tous ses messages."""
    service = ConversationService(db)
    conv = await service.get_conversation(conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

    await service.delete_conversation(conversation_id)
    logger.info("Conversation supprimée", extra={"conv_id": conversation_id})


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation_detail(
    conversation_id: str,
    include_messages: bool = Query(False, description="Inclure les 50 derniers messages"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationDetail:
    """Retourne le détail d'une conversation, optionnellement avec ses messages."""
    service = ConversationService(db)
    if include_messages:
        conv = await service.get_conversation_with_messages(conversation_id, limit_messages=50)
    else:
        conv = await service.get_conversation(conversation_id)

    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")

    # Éviter le lazy loading en définissant messages à None si non chargé
    if not include_messages:
        conv.messages = None

    return ConversationDetail.model_validate(conv)