#!/usr/bin/env python3
"""
Script interactif pour tester Gemini avec RAG et prompt système, en streaming.

Utilise les composants du projet :
- VectorStore (ChromaDB + embeddings)
- PromptManager (système)
- Gemini API

Usage :
    python scripts/test_gemini_rag.py

Nécessite les variables GEMINI_API_KEY, EMBEDDING_MODEL, etc. dans .env
"""
import os
os.environ["TQDM_DISABLE"] = "1"
import asyncio
import sys
from pathlib import Path

# Ajouter le dossier parent pour importer les modules du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

import google.generativeai as genai
from dotenv import load_dotenv

from app.core.config import get_settings
from app.rag.vector_store import VectorStore
from app.rag.prompts import PromptManager
from app.core.logging import configure_logging

# Charger .env
load_dotenv()
settings = get_settings()
configure_logging()

# Configuration Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel(settings.GEMINI_MODEL)


async def main():
    print("🤖 ChatISP AI (RAG + streaming)")
    print("Tapez votre question (ou 'exit', 'quit', 'q' pour quitter)\n")

    # Initialisation du vector store (chargement des embeddings)
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
        print("✅ Base vectorielle chargée")
    except Exception as e:
        print(f"❌ Erreur chargement vector store: {e}")
        return

    prompt_manager = PromptManager()
    system_prompt = prompt_manager.get_system_prompt()

    while True:
        user_input = input("🧑 Vous : ").strip()
        if user_input.lower() in ("exit", "quit", "q"):
            print("Au revoir !")
            break
        if not user_input:
            continue

        # 1. Recherche RAG
        try:
            docs = await vector_store.similarity_search(user_input, k=5)
            context = "\n\n".join([doc.page_content for doc in docs]) if docs else ""
        except Exception as e:
            print(f"❌ Erreur recherche : {e}")
            context = ""

        # 2. Construction du prompt
        full_prompt = system_prompt
        if context:
            full_prompt += f"\n\nCONTEXTE DOCUMENTAIRE:\n{context}\n"
        full_prompt += f"\nQuestion: {user_input}"

        # 3. Appel Gemini en streaming
        try:
            response = model.generate_content(
                full_prompt,
                generation_config={
                    "temperature": settings.TEMPERATURE,
                    "max_output_tokens": settings.MAX_TOKENS,
                },
                stream=True,
            )
            print("🤖 ChatISP AI  : ", end="", flush=True)
            for chunk in response:
                if chunk.text:
                    print(chunk.text, end="", flush=True)
            print("\n")
        except Exception as e:
            print(f"\n❌ Erreur Gemini : {e}\n")


if __name__ == "__main__":
    asyncio.run(main())