import asyncio
import logging
import re
import numpy as np
from typing import List, Dict, Any, Optional, AsyncGenerator

import google.generativeai as genai
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.rag.vector_store import VectorStore
from app.rag.prompts import PromptManager
from app.utils.rate_limiter import RateLimiter, RateLimitExceeded
from app.utils.token_counter import TokenCounter

logger = logging.getLogger(__name__)
settings = get_settings()
prompt_manager = PromptManager()

rate_limiter = RateLimiter(
    max_calls=settings.GROQ_RATE_LIMIT_MAX_CALLS,
    period=settings.GROQ_RATE_LIMIT_PERIOD,
    max_wait=settings.GROQ_RATE_LIMIT_MAX_WAIT,
)
token_counter = TokenCounter(daily_quota=settings.GROQ_DAILY_TOKEN_QUOTA)


class LLMEngine:
    """Advanced RAG engine with hybrid search, reranking, and streaming using Google Gemini with Context Caching."""

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._embedding_model = None
        self._cached_content = None
        self._cache_id = None
        self._system_prompt = prompt_manager.get_system_prompt()

        # Créer le cache au démarrage (préchargement)
        self._create_cache()

        # Le modèle d'embedding sera chargé explicitement plus tard via load_embedding_model()
        # pour ne pas bloquer le démarrage.

    def _create_cache(self) -> None:
        """Crée un cache contextuel pour le prompt système (préchargement)."""
        try:
            logger.info("Création du cache contextuel Gemini...")
            self._cached_content = genai.caching.CachedContent.create(
                model=settings.GEMINI_MODEL,
                display_name="chatisp_system_prompt",
                system_instruction=self._system_prompt,
                ttl=settings.GEMINI_CACHE_TTL,
            )
            self._cache_id = self._cached_content.name
            logger.info(f"Cache créé avec succès, ID: {self._cache_id}")
        except Exception as e:
            logger.warning(f"Impossible de créer le cache (utilisation sans cache): {e}")
            self._cached_content = None
            self._cache_id = None

    async def load_embedding_model(self) -> None:
        """Charge explicitement le modèle d'embedding (préchargement)."""
        if self._embedding_model is None:
            logger.info("Chargement du modèle d'embedding...")
            self._embedding_model = await asyncio.to_thread(
                SentenceTransformer, settings.EMBEDDING_MODEL
            )
            logger.info("Modèle d'embedding chargé avec succès.")

    async def _get_embedding_model(self) -> SentenceTransformer:
        """Retourne le modèle d'embedding (chargé si nécessaire)."""
        if self._embedding_model is None:
            await self.load_embedding_model()
        return self._embedding_model

    def _get_model(self):
        """Retourne le modèle Gemini avec ou sans cache."""
        if self._cache_id:
            return genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                cached_content=self._cache_id
            )
        else:
            return genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=self._system_prompt
            )

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def ask(
        self,
        question: str,
        context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        try:
            await rate_limiter.acquire()

            estimated_tokens = len(question) // 4 + len(context) // 4 + 500
            if not await token_counter.can_add(estimated_tokens):
                return self._get_quota_exceeded_response()

            user_prompt = ""
            if context:
                user_prompt += f"CONTEXTE DOCUMENTAIRE:\n{context}\n\n"
            if history:
                history_text = "\n".join(
                    [f"{msg['role'].capitalize()}: {msg['content']}" for msg in history[-settings.MEMORY_LIMIT:]]
                )
                user_prompt += f"Historique:\n{history_text}\n\n"
            user_prompt += f"Question: {question}"

            model = self._get_model()
            response = await asyncio.to_thread(
                model.generate_content,
                user_prompt,
                generation_config={
                    "temperature": settings.TEMPERATURE,
                    "max_output_tokens": settings.MAX_TOKENS,
                }
            )

            answer = response.text
            token_est = len(answer) // 4 + len(user_prompt) // 4
            await token_counter.add(token_est)

            answer = self._enhance_markdown_formatting(answer)
            answer = self._check_response_coherence(answer, question)
            return answer

        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded", extra={"wait": e.wait_time})
            return self._get_rate_limit_response(e.wait_time)
        except Exception as e:
            logger.exception("Unexpected error in LLMEngine.ask")
            return self._create_empty_response()

    async def ask_stream(
        self,
        question: str,
        context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            await rate_limiter.acquire()

            estimated_tokens = len(question) // 4 + len(context) // 4 + 500
            if not await token_counter.can_add(estimated_tokens):
                yield self._get_quota_exceeded_response()
                return

            user_prompt = ""
            if context:
                user_prompt += f"CONTEXTE DOCUMENTAIRE:\n{context}\n\n"
            if history:
                history_text = "\n".join(
                    [f"{msg['role'].capitalize()}: {msg['content']}" for msg in history[-settings.MEMORY_LIMIT:]]
                )
                user_prompt += f"Historique:\n{history_text}\n\n"
            user_prompt += f"Question: {question}"

            model = self._get_model()
            response = await asyncio.to_thread(
                model.generate_content,
                user_prompt,
                generation_config={
                    "temperature": settings.TEMPERATURE,
                    "max_output_tokens": settings.MAX_TOKENS,
                },
                stream=True,
            )

            full_text = ""
            for chunk in response:
                if chunk.text:
                    token = chunk.text
                    full_text += token
                    yield token

            token_est = len(full_text) // 4 + len(user_prompt) // 4
            await token_counter.add(token_est)

        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded during stream")
            yield self._get_rate_limit_response(e.wait_time)
        except asyncio.CancelledError:
            logger.debug("Stream cancelled by client")
            raise
        except Exception as e:
            logger.exception("Unexpected error in streaming")
            yield self._create_empty_response()

    # ------------------------------------------------------------------
    # Hybrid search & reranking (inchangé)
    # ------------------------------------------------------------------
    async def hybrid_search(
        self,
        query: str,
        k: int = 10,
        alpha: float = 0.5,
        mmr_lambda: float = 0.5,
    ) -> List[Dict[str, Any]]:
        candidate_k = k * 2
        vector_docs = await self.vector_store.similarity_search(query, k=candidate_k)
        if not vector_docs:
            return []

        corpus = [doc.page_content for doc in vector_docs]
        bm25 = BM25Okapi([text.split() for text in corpus])
        query_tokens = query.split()
        bm25_scores = bm25.get_scores(query_tokens)
        max_bm25 = max(bm25_scores) if bm25_scores else 1.0
        bm25_scores = [s / max_bm25 for s in bm25_scores]
        vector_scores = [doc.metadata.get("score", 0.0) for doc in vector_docs]
        composite_scores = [
            alpha * vector_scores[i] + (1 - alpha) * bm25_scores[i]
            for i in range(len(vector_docs))
        ]
        docs_with_scores = [
            {"document": doc, "score": composite_scores[i]}
            for i, doc in enumerate(vector_docs)
        ]
        docs_with_scores.sort(key=lambda x: x["score"], reverse=True)
        selected = await self._mmr_select(docs_with_scores, k, mmr_lambda)
        return selected

    async def _mmr_select(
        self,
        docs_with_scores: List[Dict[str, Any]],
        k: int,
        lambda_: float = 0.5,
    ) -> List[Dict[str, Any]]:
        if len(docs_with_scores) <= k:
            return docs_with_scores[:k]
        model = await self._get_embedding_model()
        texts = [d["document"].page_content for d in docs_with_scores]
        embeddings = await asyncio.to_thread(model.encode, texts, convert_to_tensor=False)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        embeddings_norm = embeddings / norms

        def cosine_sim(i: int, j: int) -> float:
            return float(np.dot(embeddings_norm[i], embeddings_norm[j]))

        selected_indices = []
        remaining_indices = list(range(len(docs_with_scores)))
        while len(selected_indices) < k and remaining_indices:
            mmr_scores = []
            for i in remaining_indices:
                relevance = docs_with_scores[i]["score"]
                if selected_indices:
                    max_sim = max(cosine_sim(i, j) for j in selected_indices)
                else:
                    max_sim = 0.0
                mmr = lambda_ * relevance - (1 - lambda_) * max_sim
                mmr_scores.append((i, mmr))
            best_idx, _ = max(mmr_scores, key=lambda x: x[1])
            selected_indices.append(best_idx)
            remaining_indices.remove(best_idx)
        return [docs_with_scores[i] for i in selected_indices]

    # ------------------------------------------------------------------
    # Fallback responses & utilities (inchangés)
    # ------------------------------------------------------------------
    def _get_timeout_response(self) -> str:
        return "⏳ Oups, la réponse a pris trop de temps... Peux-tu reformuler ou réessayer ?"

    def _get_network_error_response(self) -> str:
        return "📡 Problème de connexion. Vérifie ta connexion internet et réessaie."

    def _get_rate_limit_response(self, wait_seconds: int) -> str:
        return f"⏱️ Trop de requêtes pour le moment. Attends {wait_seconds} secondes avant de réessayer."

    def _get_quota_exceeded_response(self) -> str:
        return "📊 Le quota journalier de tokens est atteint. Réessaie demain !"

    def _create_empty_response(self) -> str:
        return "🤔 Je n'ai pas reçu de message valide. Peux‑tu préciser ta demande ?"

    def _enhance_markdown_formatting(self, text: str) -> str:
        text = re.sub(r"^\s*\*\s", "• ", text, flags=re.MULTILINE)
        return text

    def _check_response_coherence(self, answer: str, question: str) -> str:
        if len(answer.split()) < 10:
            answer += "\n\n💡 Désolé, ma réponse est courte. Souhaites‑tu plus de détails ?"
        return answer

    def _calculate_composite_score(self, vector_score: float, bm25_score: float, alpha: float = 0.5) -> float:
        return alpha * vector_score + (1 - alpha) * bm25_score

    def _advanced_tokenization(self, text: str) -> int:
        return len(text) // 4