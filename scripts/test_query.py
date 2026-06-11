#!/usr/bin/env python3
"""
Script de test pour interroger la base vectorielle ChromaDB après ingestion.
"""

import asyncio
import sys
from pathlib import Path

# Ajout du répertoire parent pour pouvoir importer les modules de l'application
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.vector_store import VectorStore

logger = get_logger("test_query")
settings = get_settings()


async def test_query(query: str, k: int = 5):
    """Effectue une recherche et affiche les résultats."""
    print(f"\n🔍 Recherche de : '{query}' (k={k})\n")
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
        results = await vector_store.similarity_search(query, k=k)

        if not results:
            print("❌ Aucun document trouvé.")
            return

        print(f"✅ {len(results)} document(s) trouvé(s) :\n")
        for i, doc in enumerate(results, 1):
            print(f"--- Résultat {i} ---")
            print(f"Source : {doc.metadata.get('source_file', 'inconnue')}")
            print(f"Score : {doc.metadata.get('score', 0.0):.4f}")
            print(f"Extrait : {doc.page_content}...")
            print()
    except Exception as e:
        logger.exception("Erreur lors de la recherche")
        print(f"❌ Erreur : {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_query.py \"votre requête\" [nombre de résultats]")
        sys.exit(1)
    query = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    asyncio.run(test_query(query, k))


if __name__ == "__main__":
    main()