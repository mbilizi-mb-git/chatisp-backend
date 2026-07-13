"""
Point d'entrée principal de l'application FastAPI.
Configuration des routes, CORS, démarrage/arrêt.
Le vector store et le LLMEngine sont préchargés au démarrage pour éviter les lenteurs.
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
from app.rag.llm_engine import LLMEngine
from app.services.rag_service import RagService
from app.services.rag_singleton import set_rag_service

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gère les événements de démarrage et d'arrêt."""
    logger.info("Démarrage de ChatISP AI backend")
    await init_db()
    logger.info("Base de données initialisée")

    # Préchargement du vector store (modèle d'embedding)
    vector_store = None
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
        logger.info("Vector store chargé et prêt (préchauffage réussi)")
    except Exception as e:
        logger.error(f"Échec du préchargement du vector store: {e}")
        logger.info("Le vector store sera chargé à la première utilisation (lazy loading)")

    # Préchargement du LLMEngine (cache Gemini + embedding model)
    if vector_store:
        try:
            llm_engine = LLMEngine(vector_store)
            # Charger le modèle d'embedding explicitement
            await llm_engine.load_embedding_model()
            logger.info("LLMEngine préchargé avec succès")
            # Créer le service RAG avec les instances préchargées
            rag_service = RagService(
                db=None,  # sera passé dans les endpoints
                vector_store=vector_store,
                llm_engine=llm_engine
            )
            set_rag_service(rag_service)  # Stocker dans le singleton
            logger.info("RagService initialisé avec succès")
        except Exception as e:
            logger.error(f"Échec du préchargement du LLMEngine: {e}")
            set_rag_service(None)

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