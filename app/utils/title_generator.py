"""
Génération de titres de conversation : heuristique locale et via LLM (Gemini).
"""

import asyncio
import logging
import re
from typing import Optional, Set

import google.generativeai as genai

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Stopwords français pour l'heuristique
FRENCH_STOPWORDS: Set[str] = {
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "mais",
    "donc", "car", "ni", "que", "qui", "quoi", "dont", "où", "comment",
    "pourquoi", "quand", "est", "sont", "avec", "sans", "chez", "par",
    "sur", "dans", "hors", "en", "vers", "entre", "pendant", "depuis",
    "jusque", "voici", "voilà", "ce", "cet", "cette", "ces", "mon", "ton",
    "son", "notre", "votre", "leur", "mes", "tes", "ses", "nos", "vos",
    "leurs", "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "me", "te", "se", "lui", "leur", "y", "en", "ceci", "cela", "ça",
}

# Client Gemini (lazy initialization)
_gemini_client = None


def _get_gemini_client():
    """Retourne le client Gemini s'il est configuré, sinon None."""
    global _gemini_client
    if _gemini_client is None and settings.GEMINI_API_KEY:
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            _gemini_client = genai.GenerativeModel(settings.GEMINI_MODEL)
            logger.info("Client Gemini initialisé pour la génération de titres")
        except Exception as e:
            logger.error(f"Impossible d'initialiser le client Gemini: {e}")
            _gemini_client = False  # marquer l'échec
    return _gemini_client if _gemini_client is not None else None


def generate_title_heuristic(message: str, max_words: int = 8, max_chars: int = 60) -> str:
    """
    Génère un titre à partir du message en utilisant une heuristique simple
    (extraction des premiers mots significatifs, sans stopwords).
    Fallback : "Conversation".
    """
    # Normaliser
    text = re.sub(r"\s+", " ", message.strip().lower())
    words = re.findall(r"\b\w+\b", text)

    # Filtrer stopwords et mots très courts
    meaningful = [w for w in words if w not in FRENCH_STOPWORDS and len(w) > 2]

    if not meaningful:
        meaningful = words[:max_words]

    if not meaningful:
        return "Conversation"

    # Capitaliser la première lettre de chaque mot
    title = " ".join(w.capitalize() for w in meaningful[:max_words])

    if len(title) > max_chars:
        title = title[:max_chars - 1] + "…"

    return title


async def generate_title_with_llm(message: str) -> Optional[str]:
    """
    Génère un titre court (3‑8 mots) à partir du premier message en utilisant Gemini.
    Retourne None en cas d'échec (fallback vers heuristique).
    """
    client = _get_gemini_client()
    if client is None:
        logger.debug("Client Gemini non disponible, fallback heuristique")
        return None

    prompt = f"""Génère un titre très court (3 à 8 mots maximum) qui résume le sujet principal de ce message.
Ne réponds que par le titre, sans guillemets, sans point final. Sois concis et pertinent.

Message : {message}

Titre :"""

    try:
        # Appel synchrone dans un thread pour éviter de bloquer
        response = await asyncio.to_thread(
            client.generate_content,
            prompt,
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 20,
            }
        )
        title = response.text.strip()
        if not title:
            return None
        # Nettoyer
        title = re.sub(r'["\']', '', title)
        # Limiter la longueur
        if len(title) > 60:
            title = title[:57] + "..."
        # Vérifier que le titre est cohérent (entre 2 et 10 mots)
        word_count = len(title.split())
        if 2 <= word_count <= 10:
            return title
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la génération du titre par LLM: {e}")
        return None