"""
Service RAG orchestre la recherche vectorielle, l'appel au LLM, la gestion des messages
et la génération automatique des titres de conversation (LLM + fallback heuristique).
"""

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
from app.utils.title_generator import generate_title_heuristic, generate_title_with_llm
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RagService:
    """
    Orchestrateur du pipeline RAG :
    - Récupération du contexte vectoriel
    - Mémorisation des derniers messages
    - Appel LLM (streaming)
    - Sauvegarde des messages
    - Génération automatique du titre pour la première question
    """

    def __init__(
        self,
        db: AsyncSession,
        vector_store: VectorStore,
        llm_engine: LLMEngine,
    ):
        self.db = db
        self.vector_store = vector_store
        self.llm = llm_engine
        self.conv_service = ConversationService(db)
        self.msg_service = MessageService(db)

    async def process_message_stream(
        self,
        conversation_id: str,
        user_message: str,
    ) -> AsyncGenerator[str, None]:
        """
        Traite un message utilisateur et génère une réponse en streaming.
        Sauvegarde automatiquement les messages et, si c'est le premier message,
        génère un titre intelligent pour la conversation.
        """
        # 1. Sauvegarder le message utilisateur
        user_msg = await self.msg_service.create_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )
        logger.debug(f"Message utilisateur enregistré: {user_msg.id}")

        # 2. Vérifier si c'est le premier message de la conversation
        is_first = await self._is_first_message(conversation_id)

        # 3. Récupérer les derniers messages pour le contexte
        memory = await self.msg_service.get_last_messages(
            conversation_id, limit=settings.MEMORY_LIMIT
        )
        history = [
            {"role": msg.role, "content": msg.content} for msg in memory
        ]

        # 4. Recherche vectorielle (contexte)
        context = await self.vector_search(user_message)
        logger.debug(f"Contexte récupéré: {len(context)} caractères")

        # 5. Appel LLM en streaming
        full_response = []
        async for token in self.llm.ask_stream(
            question=user_message,
            context=context,
            history=history,
        ):
            full_response.append(token)
            yield token

        assistant_content = "".join(full_response)

        # 6. Sauvegarder la réponse de l'assistant
        assistant_msg = await self.msg_service.create_message(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_content,
        )
        logger.debug(f"Réponse assistant enregistrée: {assistant_msg.id}")

        # 7. Si premier message, générer un titre intelligent
        if is_first:
            title = await self._generate_conversation_title(user_message)
            if title:
                try:
                    await self.conv_service.rename_conversation(conversation_id, title)
                    logger.info(
                        "Titre généré automatiquement",
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
        await self._touch_conversation(conversation_id)

    async def vector_search(self, query: str, k: int = 5) -> str:
        """
        Recherche les documents pertinents dans la base vectorielle.
        Retourne une chaîne de texte concaténée ou une chaîne vide.
        """
        try:
            docs = await self.vector_store.similarity_search(query, k=k)
            if not docs:
                return ""
            # Concaténer les extraits avec un séparateur
            return "\n\n---\n\n".join([doc.page_content for doc in docs])
        except Exception as e:
            logger.error(f"Erreur lors de la recherche vectorielle: {e}")
            return ""

    async def _is_first_message(self, conversation_id: str) -> bool:
        """Détermine si le message actuel est le premier de la conversation."""
        messages = await self.msg_service.get_last_messages(conversation_id, limit=2)
        # Un seul message = c'est le premier (le message utilisateur vient d'être ajouté)
        return len(messages) == 1

    async def _generate_conversation_title(self, user_message: str) -> Optional[str]:
        """
        Génère un titre pour une nouvelle conversation.
        Essaie d'abord le LLM, puis l'heuristique en fallback.
        Retourne None si aucun titre n'est généré.
        """
        # Tentative LLM
        title = await generate_title_with_llm(user_message)
        if title:
            logger.debug(f"Titre généré par LLM: {title}")
            return title

        # Fallback heuristique
        title = generate_title_heuristic(user_message)
        if title and title != "Conversation":
            logger.debug(f"Titre généré par heuristique: {title}")
            return title

        # Dernier recours : éviter de laisser le titre nul
        if len(user_message.strip()) > 0:
            # Extraire les premiers mots
            first_words = " ".join(user_message.split()[:5])
            if len(first_words) > 40:
                first_words = first_words[:37] + "..."
            title = first_words if first_words else "Nouvelle conversation"
            logger.debug(f"Titre par défaut: {title}")
            return title

        return None

    async def _touch_conversation(self, conversation_id: str) -> None:
        """Met à jour le champ updated_at de la conversation."""
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.utcnow())
        )
        await self.db.execute(stmt)
        await self.db.commit()