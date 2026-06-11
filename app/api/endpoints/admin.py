"""
Endpoints d'administration réservés aux utilisateurs avec privilèges admin.
Tableau de bord : statistiques, gestion des utilisateurs, export de données,
réinitialisation de mot de passe (sans afficher le hash).
"""

import csv
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_admin_user, get_db
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.user_service import UserService
from app.core.security import hash_password

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_stats(
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Statistiques globales : utilisateurs, conversations, messages."""
    total_users = await db.scalar(select(func.count()).select_from(User))
    yesterday = datetime.utcnow() - timedelta(days=1)
    active_users = await db.scalar(
        select(func.count()).where(User.last_seen > yesterday)
    )
    google_users = await db.scalar(
        select(func.count()).where(User.google_id.isnot(None))
    )
    total_conversations = await db.scalar(select(func.count()).select_from(Conversation))
    total_messages = await db.scalar(select(func.count()).select_from(Message))
    user_messages = await db.scalar(
        select(func.count()).where(Message.role == "user")
    )
    assistant_messages = await db.scalar(
        select(func.count()).where(Message.role == "assistant")
    )
    return {
        "total_users": total_users,
        "active_users_last_24h": active_users,
        "google_users": google_users,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, description="Recherche par email ou display_name"),
) -> Dict[str, Any]:
    """Liste paginée des utilisateurs (sans mot de passe)."""
    query = select(
        User.id,
        User.email,
        User.display_name,
        User.avatar_url,
        User.is_active,
        User.is_admin,
        User.created_at,
        User.last_seen,
    )
    if search:
        query = query.where(
            (User.email.contains(search)) | (User.display_name.contains(search))
        )
    query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    users = [
        {
            "id": u[0],
            "email": u[1],
            "display_name": u[2],
            "avatar_url": u[3],
            "is_active": u[4],
            "is_admin": u[5],
            "created_at": u[6].isoformat(),
            "last_seen": u[7].isoformat() if u[7] else None,
        }
        for u in result.fetchall()
    ]
    total_query = select(func.count()).select_from(User)
    if search:
        total_query = total_query.where(
            (User.email.contains(search)) | (User.display_name.contains(search))
        )
    total = await db.scalar(total_query)
    return {"items": users, "total": total, "limit": limit, "offset": offset}


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Détail complet d'un utilisateur (sans mot de passe)."""
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    conv_count = await db.scalar(
        select(func.count()).where(Conversation.user_id == user_id)
    )
    msg_count = await db.scalar(
        select(func.count())
        .select_from(Message)
        .join(Conversation)
        .where(Conversation.user_id == user_id)
    )
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
        "last_seen": user.last_seen.isoformat() if user.last_seen else None,
        "conversations_count": conv_count,
        "messages_count": msg_count,
    }


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    new_password: str = Query(..., min_length=6),
) -> Dict[str, str]:
    """
    Réinitialise le mot de passe d'un utilisateur (admin uniquement).
    Nécessaire pour les comptes email/mdp oubliés. Ne retourne jamais l'ancien hash.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    if user.google_id is not None:
        raise HTTPException(status_code=400, detail="Impossible de réinitialiser un compte Google")
    hashed = hash_password(new_password)
    await db.execute(
        update(User).where(User.id == user_id).values(hashed_password=hashed)
    )
    await db.commit()
    logger.info(f"Admin {admin.email} a réinitialisé le mot de passe de {user.email}")
    return {"message": "Mot de passe réinitialisé avec succès"}


@router.get("/users/{user_id}/conversations")
async def get_user_conversations(
    user_id: str,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Liste paginée des conversations d'un utilisateur avec nombre de messages."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    convs = result.scalars().all()
    total = await db.scalar(
        select(func.count()).where(Conversation.user_id == user_id)
    )
    items = []
    for conv in convs:
        msg_count = await db.scalar(
            select(func.count()).where(Message.conversation_id == conv.id)
        )
        items.append({
            "id": conv.id,
            "title": conv.title,
            "is_pinned": conv.is_pinned,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "messages_count": msg_count,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages_admin(
    conversation_id: str,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> List[Dict[str, Any]]:
    """Récupère tous les messages d'une conversation pour inspection."""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat(),
            "conversation_id": conversation_id,
            "user_id": conv.user_id,
        }
        for msg in messages
    ]


@router.get("/export/users")
async def export_users_csv(
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Export CSV de tous les utilisateurs (sans mot de passe)."""
    result = await db.execute(
        select(
            User.id,
            User.email,
            User.display_name,
            User.avatar_url,
            User.is_active,
            User.is_admin,
            User.created_at,
            User.last_seen,
        ).order_by(User.created_at)
    )
    users = result.fetchall()
    async def csv_generator():
        yield "id,email,display_name,avatar_url,is_active,is_admin,created_at,last_seen\n"
        for u in users:
            row = f"{u[0]},{u[1]},{u[2]},{u[3] or ''},{u[4]},{u[5]},{u[6].isoformat()},{u[7].isoformat() if u[7] else ''}\n"
            yield row
    return StreamingResponse(
        csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users_export.csv"},
    )


@router.get("/export/conversations")
async def export_conversations_csv(
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Export CSV de toutes les conversations avec l'email de l'utilisateur."""
    stmt = (
        select(
            Conversation.id,
            Conversation.user_id,
            User.email,
            Conversation.title,
            Conversation.is_pinned,
            Conversation.created_at,
            Conversation.updated_at,
        )
        .join(User, Conversation.user_id == User.id)
        .order_by(Conversation.created_at)
    )
    result = await db.execute(stmt)
    convs = result.fetchall()
    async def csv_generator():
        yield "conversation_id,user_id,user_email,title,is_pinned,created_at,updated_at\n"
        for c in convs:
            row = f"{c[0]},{c[1]},{c[2]},{c[3] or ''},{c[4]},{c[5].isoformat()},{c[6].isoformat()}\n"
            yield row
    return StreamingResponse(
        csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=conversations_export.csv"},
    )


@router.get("/export/messages")
async def export_messages_csv(
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Export CSV de tous les messages (avec conversation_id et user_id)."""
    stmt = (
        select(
            Message.id,
            Message.conversation_id,
            Conversation.user_id,
            Message.role,
            Message.content,
            Message.created_at,
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .order_by(Message.created_at)
    )
    result = await db.execute(stmt)
    msgs = result.fetchall()
    async def csv_generator():
        yield "message_id,conversation_id,user_id,role,content,created_at\n"
        for m in msgs:
            content = m[4].replace('"', '""')
            row = f"{m[0]},{m[1]},{m[2]},{m[3]},\"{content}\",{m[5].isoformat()}\n"
            yield row
    return StreamingResponse(
        csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=messages_export.csv"},
    )