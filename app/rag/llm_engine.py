import asyncio
import logging
import re
import numpy as np
from typing import List, Dict, Any, Optional, AsyncGenerator

import groq
from groq import AsyncGroq
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
    """Advanced RAG engine with hybrid search, reranking, and streaming."""

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self._embedding_model = None

    async def _get_embedding_model(self) -> SentenceTransformer:
        """Lazy load the sentence transformer model for embeddings."""
        if self._embedding_model is None:
            self._embedding_model = await asyncio.to_thread(
                SentenceTransformer, settings.EMBEDDING_MODEL
            )
        return self._embedding_model

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def ask(
        self,
        question: str,
        context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Non‑streaming answer generation."""
        try:
            await rate_limiter.acquire()

            estimated_tokens = len(question) // 4 + len(context) // 4 + 500
            if not await token_counter.can_add(estimated_tokens):
                return self._get_quota_exceeded_response()

            system_content = self._build_system_content(context)
            messages = [
                {"role": "system", "content": system_content},
                *self._history_to_messages(history),
                {"role": "user", "content": question},
            ]

            response = await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            )

            answer = response.choices[0].message.content
            if hasattr(response, "usage") and response.usage:
                await token_counter.add(response.usage.total_tokens)

            answer = self._enhance_markdown_formatting(answer)
            answer = self._check_response_coherence(answer, question)
            return answer

        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded", extra={"wait": e.wait_time})
            return self._get_rate_limit_response(e.wait_time)
        except groq.APITimeoutError:
            logger.error("Groq API timeout")
            return self._get_timeout_response()
        except groq.APIConnectionError:
            logger.error("Groq network error")
            return self._get_network_error_response()
        except Exception as e:
            logger.exception("Unexpected error in LLMEngine.ask")
            return self._create_empty_response()

    async def ask_stream(
        self,
        question: str,
        context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming answer generation, yields tokens one by one."""
        try:
            await rate_limiter.acquire()

            estimated_tokens = len(question) // 4 + len(context) // 4 + 500
            if not await token_counter.can_add(estimated_tokens):
                yield self._get_quota_exceeded_response()
                return

            system_content = self._build_system_content(context)
            messages = [
                {"role": "system", "content": system_content},
                *self._history_to_messages(history),
                {"role": "user", "content": question},
            ]

            # Note: 'stream_options' parameter may not be supported in the current Groq client
            stream = await self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=messages,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
                stream=True,
            )

            usage = None
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    yield token
                # Usage may be available in a final chunk if the API includes it
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage

            if usage and usage.total_tokens:
                await token_counter.add(usage.total_tokens)

        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded during stream")
            yield self._get_rate_limit_response(e.wait_time)
        except groq.APITimeoutError:
            logger.error("Groq API timeout during stream")
            yield self._get_timeout_response()
        except groq.APIConnectionError:
            logger.error("Groq network error during stream")
            yield self._get_network_error_response()
        except asyncio.CancelledError:
            logger.debug("Stream cancelled by client")
            raise
        except Exception as e:
            logger.exception("Unexpected error in streaming")
            yield self._create_empty_response()

    # ------------------------------------------------------------------
    # Hybrid search & reranking (production‑ready)
    # ------------------------------------------------------------------

    async def hybrid_search(
        self,
        query: str,
        k: int = 10,
        alpha: float = 0.5,
        mmr_lambda: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search: vector + BM25, then rerank with composite score,
        apply MMR for diversity using real embeddings.
        Returns a list of documents with scores.
        """
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

        composite_scores = []
        for i in range(len(vector_docs)):
            composite = alpha * vector_scores[i] + (1 - alpha) * bm25_scores[i]
            composite_scores.append(composite)

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
        """
        Maximal Marginal Relevance selection using cosine similarity of real embeddings.
        """
        if len(docs_with_scores) <= k:
            return docs_with_scores[:k]

        # Ensure embedding model is loaded
        model = await self._get_embedding_model()

        # Compute embeddings for all documents
        texts = [d["document"].page_content for d in docs_with_scores]
        # Run embedding in thread pool to avoid blocking
        embeddings = await asyncio.to_thread(model.encode, texts, convert_to_tensor=False)
        # embeddings is a numpy array of shape (n, dim)
        # Normalize embeddings for cosine similarity (dot product of normalized vectors)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # avoid division by zero
        embeddings_norm = embeddings / norms

        # Function to compute cosine similarity between two documents by index
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
            # Select best
            best_idx, _ = max(mmr_scores, key=lambda x: x[1])
            selected_indices.append(best_idx)
            remaining_indices.remove(best_idx)

        return [docs_with_scores[i] for i in selected_indices]

    # ------------------------------------------------------------------
    # Fallback responses
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

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _build_system_content(self, context: str) -> str:
        """Build the system message content, including RAG context if any."""
        base = prompt_manager.get_system_prompt()
        if context:
            base += f"\n\nCONTEXTE DOCUMENTAIRE:\n{context}"
        return base

    def _history_to_messages(self, history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        """Convert conversation history to OpenAI message format."""
        if not history:
            return []
        # Limit to last N messages (configured in settings)
        limited = history[-settings.MEMORY_LIMIT:]
        return [{"role": msg["role"], "content": msg["content"]} for msg in limited]

    def _enhance_markdown_formatting(self, text: str) -> str:
        # Convert asterisk lists to bullet points for better markdown
        text = re.sub(r"^\s*\*\s", "• ", text, flags=re.MULTILINE)
        return text

    def _check_response_coherence(self, answer: str, question: str) -> str:
        if len(answer.split()) < 10:
            answer += "\n\n💡 Désolé, ma réponse est courte. Souhaites‑tu plus de détails ?"
        return answer

    def _calculate_composite_score(
        self,
        vector_score: float,
        bm25_score: float,
        alpha: float = 0.5,
    ) -> float:
        return alpha * vector_score + (1 - alpha) * bm25_score

    def _advanced_tokenization(self, text: str) -> int:
        return len(text) // 4