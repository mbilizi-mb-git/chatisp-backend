"""
Endpoints de santé et de vérification de l'état du service.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.config import get_settings
from app.rag.vector_store import VectorStore

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)
settings = get_settings()


@router.get("/health")
async def health_check() -> dict:
    """
    Vérification simple de l'état du service.
    Retourne toujours 200 OK si l'application répond.
    """
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Vérification de l'état de préparation (readiness probe).
    Vérifie la connectivité à la base de données et au vector store.
    """
    # Vérification de la base de données
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.exception("Base de données inaccessible")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de données non disponible",
        )

    # Vérification du vector store ChromaDB
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
    except Exception as e:
        logger.exception("Vector store inaccessible")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store non disponible",
        )

    return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}