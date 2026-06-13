"""
Point d'entrée principal de l'application FastAPI.
Configuration des routes, CORS, démarrage/arrêt.
Les modèles lourds (ChromaDB, embeddings) sont chargés à la demande.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db, close_db
from app.core.logging import configure_logging
from app.api.endpoints import conversations, messages, health, auth, admin

settings = get_settings()
logger = logging.getLogger(__name__)

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gère les événements de démarrage et d'arrêt."""
    logger.info("Démarrage de ChatISP AI backend")
    await init_db()
    logger.info("Base de données initialisée")

    # ⚠️ NE PAS charger le vector store ici – il sera initialisé à la première requête
    # pour économiser la mémoire (lazy loading).
    logger.info("Vector store sera chargé à la première utilisation (lazy loading)")

    yield

    await close_db()
    logger.info("Connexions à la base de données fermées")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

logger.info("Application FastAPI créée avec succès")