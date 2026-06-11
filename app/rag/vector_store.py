import asyncio
import logging
import uuid
from pathlib import Path
from typing import List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class VectorStore:
    """Singleton vector store manager using ChromaDB and local embeddings."""

    _instance: Optional["VectorStore"] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> "VectorStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = False
            self._client = None
            self._collection = None
            self._embedding_model = None

    async def _initialize(self) -> None:
        """Lazy initialization of ChromaDB client, collection, and embedding model."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            try:
                # Ensure the parent directory exists
                chroma_path = Path(settings.CHROMA_PATH)
                chroma_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Initializing ChromaDB at {chroma_path}")

                # Run synchronous ChromaDB operations in thread pool
                self._client = await asyncio.to_thread(
                    chromadb.PersistentClient,
                    path=str(chroma_path),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                # Ensure collection exists
                collection_name = "chatisp_academic"
                self._collection = await asyncio.to_thread(
                    self._client.get_or_create_collection,
                    name=collection_name,
                )
                # Load embedding model (also synchronous)
                self._embedding_model = await asyncio.to_thread(
                    SentenceTransformer,
                    settings.EMBEDDING_MODEL,
                )
                self._initialized = True
                logger.info("Vector store initialized", extra={"path": str(chroma_path)})
            except Exception as e:
                logger.exception("Failed to initialize vector store")
                raise RuntimeError("Vector store initialization failed") from e

    async def ensure_collection(self) -> None:
        """Ensure the collection is accessible (for health checks)."""
        await self._initialize()

    async def similarity_search(self, query: str, k: int = 5) -> List[Document]:
        """
        Perform similarity search against the vector store.
        Returns a list of Documents with page_content and metadata.
        """
        await self._initialize()
        try:
            # Generate query embedding
            query_embedding = await asyncio.to_thread(
                self._embedding_model.encode, query
            )
            # Query ChromaDB
            results = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[query_embedding.tolist()],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
            documents = []
            if results["documents"]:
                for i, doc_text in enumerate(results["documents"][0]):
                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    distance = results["distances"][0][i] if results["distances"] else 0.0
                    # Convert L2 distance to similarity score (0-1)
                    metadata["score"] = 1.0 / (1.0 + distance)
                    documents.append(Document(page_content=doc_text, metadata=metadata))
            logger.debug(
                "Similarity search completed",
                extra={"query": query[:50], "k": k, "found": len(documents)},
            )
            return documents
        except Exception as e:
            logger.exception("Similarity search failed", extra={"query": query[:50]})
            # Return empty list on error, as fallback
            return []

    async def add_documents(self, documents: List[Document]) -> None:
        """Add documents to the vector store (used by ingestion script)."""
        await self._initialize()
        try:
            texts = [doc.page_content for doc in documents]
            metadatas = [doc.metadata for doc in documents]
            ids = [str(uuid.uuid4()) for _ in documents]

            # Generate embeddings
            embeddings = await asyncio.to_thread(
                self._embedding_model.encode, texts, convert_to_tensor=False
            )
            embeddings_list = [emb.tolist() for emb in embeddings]

            await asyncio.to_thread(
                self._collection.add,
                embeddings=embeddings_list,
                documents=texts,
                metadatas=metadatas,
                ids=ids,
            )
            logger.info("Added %d documents to vector store", len(documents))
        except Exception as e:
            logger.exception("Failed to add documents")
            raise