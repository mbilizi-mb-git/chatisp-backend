"""
Point d'entrée principal de l'application FastAPI.
Configuration des routes, CORS, démarrage/arrêt, et intégration de l'authentification.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db, close_db
from app.core.logging import configure_logging
from app.api.endpoints import conversations, messages, health, auth, admin
from app.rag.vector_store import VectorStore

settings = get_settings()
logger = logging.getLogger(__name__)

# Configure logging au démarrage
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gère les événements de démarrage et d'arrêt de l'application."""
    # Startup
    logger.info("Démarrage de ChatISP AI backend")
    await init_db()
    logger.info("Base de données initialisée")

    # Initialisation du vector store
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
        logger.info("Vector store prêt")
    except Exception as e:
        logger.error(f"Échec de l'initialisation du vector store: {e}")

    yield

    # Shutdown
    await close_db()
    logger.info("Connexions à la base de données fermées")


# Création de l'application FastAPI
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routeurs
app.include_router(auth.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

logger.info("Application FastAPI créée avec succès")