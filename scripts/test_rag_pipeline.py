#!/usr/bin/env python3
"""
Script de test complet du pipeline RAG (recherche + génération LLM).

Utilisation :
    python scripts/test_rag_pipeline.py "votre question" [nombre de documents à récupérer]

Affiche les documents pertinents puis la réponse générée par le LLM.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

# Charge le .env situé dans le répertoire parent
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Ajout du répertoire parent pour pouvoir importer les modules de l'application
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.vector_store import VectorStore
from app.rag.llm_engine import LLMEngine
from app.rag.prompts import PromptManager

logger = get_logger("test_rag")
settings = get_settings()


async def run_pipeline(query: str, k: int = 5):
    """
    Exécute le pipeline complet :
    1. Recherche de documents pertinents
    2. Construction du contexte
    3. Appel au LLM
    4. Affichage des résultats
    """
    print("\n" + "=" * 60)
    print("🔍 TEST DU PIPELINE RAG")
    print("=" * 60 + "\n")

    # 1. Initialisation
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
        print("✅ Connexion à la base vectorielle établie")
    except Exception as e:
        logger.exception("Erreur lors de l'initialisation du vector store")
        print(f"❌ Erreur : impossible d'initialiser la base vectorielle - {e}")
        return

    # 2. Recherche de documents
    print(f"\n🔎 Recherche de documents pour la requête : '{query}' (k={k})")
    try:
        docs = await vector_store.similarity_search(query, k=k)
    except Exception as e:
        logger.exception("Erreur lors de la recherche")
        print(f"❌ Erreur lors de la recherche : {e}")
        return

    if not docs:
        print("⚠️ Aucun document pertinent trouvé.")
    else:
        print(f"\n✅ {len(docs)} document(s) pertinent(s) trouvé(s) :\n")
        for i, doc in enumerate(docs, 1):
            print(f"--- Document {i} ---")
            source = doc.metadata.get('source_file', 'inconnue')
            score = doc.metadata.get('score', 0.0)
            print(f"Source : {source}")
            print(f"Score : {score:.4f}")
            extrait = doc.page_content[:200] + ("…" if len(doc.page_content) > 200 else "")
            print(f"Extrait : {extrait}\n")

    # 3. Construction du contexte (concaténation des documents)
    if docs:
        context = "\n\n---\n\n".join([doc.page_content for doc in docs])
        print(f"📚 Contexte construit avec {len(docs)} documents.")
    else:
        context = ""
        print("📚 Aucun contexte disponible.")

    # 4. Initialisation du LLM
    try:
        llm = LLMEngine(vector_store)  # Note : LLMEngine nécessite vector_store pour hybrid_search
        print("✅ Moteur LLM initialisé")
    except Exception as e:
        logger.exception("Erreur lors de l'initialisation du LLM")
        print(f"❌ Erreur : impossible d'initialiser le LLM - {e}")
        return

    # 5. Appel au LLM (version non‑streaming)
    print("\n⏳ Génération de la réponse par le LLM...")
    try:
        answer = await llm.ask(
            question=query,
            context=context,
            history=None  # Pas d'historique pour ce test
        )
    except Exception as e:
        logger.exception("Erreur lors de l'appel au LLM")
        print(f"❌ Erreur lors de la génération : {e}")
        return

    # 6. Affichage de la réponse
    print("\n" + "=" * 60)
    print("🤖 RÉPONSE DU LLM")
    print("=" * 60)
    print(answer)
    print("=" * 60 + "\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_rag_pipeline.py \"votre question\" [nombre de documents]")
        sys.exit(1)

    query = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    asyncio.run(run_pipeline(query, k))


if __name__ == "__main__":
    main()