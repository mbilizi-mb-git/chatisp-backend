"""
Service RAG orchestre la recherche vectorielle, l'appel au LLM, la gestion des messages
et la génération automatique des titres de conversation (UNIQUEMENT heuristique, pas de LLM).
"""

import asyncio
import logging
from datetime import datetime
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.models.conversation import Conversation
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.rag.llm_engine import LLMEngine
from app.rag.vector_store import VectorStore
from app.utils.title_generator import generate_title_heuristic  # plus de LLM
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RagService:
    """
    Orchestrateur du pipeline RAG.
    N'utilise pas de session DB persistante ; elle est passée à chaque appel.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        llm_engine: LLMEngine,
    ):
        self.vector_store = vector_store
        self.llm = llm_engine

    async def process_message_stream(
        self,
        conversation_id: str,
        user_message: str,
        db: AsyncSession,  # ← Session DB obligatoire
    ) -> AsyncGenerator[str, None]:
        """
        Traite un message utilisateur et génère une réponse en streaming.
        Sauvegarde automatiquement les messages et, si c'est le premier message,
        génère un titre intelligent (heuristique uniquement).
        """
        msg_service = MessageService(db)
        conv_service = ConversationService(db)

        # 1. Sauvegarder le message utilisateur
        user_msg = await msg_service.create_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )
        logger.debug(f"Message utilisateur enregistré: {user_msg.id}")

        # 2. Vérifier si c'est le premier message
        is_first = await self._is_first_message(conversation_id, msg_service)

        # 3. Récupérer les derniers messages pour le contexte
        memory = await msg_service.get_last_messages(
            conversation_id, limit=settings.MEMORY_LIMIT
        )
        history = [
            {"role": msg.role, "content": msg.content} for msg in memory
        ]

        # 4. Recherche vectorielle
        context = await self.vector_search(user_message)
        logger.debug(f"Contexte récupéré: {len(context)} caractères")

        # 5. Appel LLM en streaming
        full_response = []
        assistant_content = ""
        try:
            async for token in self.llm.ask_stream(
                question=user_message,
                context=context,
                history=history,
            ):
                full_response.append(token)
                yield token
        except asyncio.CancelledError:
            logger.warning(
                "Stream interrompu par le client, sauvegarde partielle en cours",
                extra={"conv_id": conversation_id}
            )
        except Exception as e:
            logger.error(
                f"Erreur lors du streaming LLM: {e}",
                extra={"conv_id": conversation_id}
            )
        finally:
            assistant_content = "".join(full_response)
            if not assistant_content:
                assistant_content = "[Désolé, une erreur est survenue lors de la génération de la réponse.]"
                logger.warning("Contenu assistant vide, utilisation d'un message par défaut")

            # 6. Sauvegarder la réponse de l'assistant (même partielle)
            try:
                assistant_msg = await msg_service.create_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_content,
                )
                logger.info(
                    "Réponse assistant enregistrée",
                    extra={"msg_id": assistant_msg.id, "conv_id": conversation_id, "length": len(assistant_content)}
                )
            except Exception as e:
                logger.error(f"Échec de la sauvegarde du message assistant: {e}")

            # 7. Si premier message, générer un titre (UNIQUEMENT heuristique)
            if is_first and assistant_content:
                # Utiliser uniquement l'heuristique, pas le LLM
                title = self._generate_title_heuristic_only(user_message)
                if title and title != "Conversation":
                    try:
                        await conv_service.rename_conversation(conversation_id, title)
                        logger.info(
                            "Titre généré automatiquement (heuristique)",
                            extra={"conv_id": conversation_id, "title": title},
                        )
                    except Exception as e:
                        logger.error(
                            f"Échec de l'enregistrement du titre: {e}",
                            extra={"conv_id": conversation_id},
                        )
                else:
                    logger.warning("Aucun titre généré, conversation sans titre")

            # 8. Mettre à jour le timestamp de la conversation
            await self._touch_conversation(conversation_id, db)

    async def vector_search(self, query: str, k: int = 5) -> str:
        try:
            docs = await self.vector_store.similarity_search(query, k=k)
            if not docs:
                return ""
            return "\n\n---\n\n".join([doc.page_content for doc in docs])
        except Exception as e:
            logger.error(f"Erreur lors de la recherche vectorielle: {e}")
            return ""

    async def _is_first_message(self, conversation_id: str, msg_service: MessageService) -> bool:
        messages = await msg_service.get_last_messages(conversation_id, limit=2)
        return len(messages) == 1

    def _generate_title_heuristic_only(self, user_message: str) -> Optional[str]:
        """Génère un titre via l'heuristique (sans LLM)."""
        title = generate_title_heuristic(user_message)
        if title and title != "Conversation":
            return title
        if len(user_message.strip()) > 0:
            first_words = " ".join(user_message.split()[:5])
            if len(first_words) > 40:
                first_words = first_words[:37] + "..."
            return first_words if first_words else "Nouvelle conversation"
        return None

    async def _touch_conversation(self, conversation_id: str, db: AsyncSession) -> None:
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.utcnow())
        )
        await db.execute(stmt)
        await db.commit()