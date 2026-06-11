"""
Génération de titres de conversation : heuristique locale et via LLM (Groq).
"""

import re
from typing import List, Set, Optional

from groq import AsyncGroq

from app.core.config import get_settings

settings = get_settings()
client = AsyncGroq(api_key=settings.GROQ_API_KEY)

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
    Génère un titre court (3‑8 mots) à partir du premier message en utilisant Groq.
    Retourne None en cas d'échec (fallback vers heuristique).
    """
    prompt = f"""Génère un titre très court (3 à 8 mots maximum) qui résume le sujet principal de ce message.
Ne réponds que par le titre, sans guillemets, sans point final. Sois concis et pertinent.

Message : {message}

Titre :"""

    try:
        response = await client.chat.completions.create(
            model=settings.MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=30,
        )
        title = response.choices[0].message.content.strip()
        # Nettoyer
        title = re.sub(r'["\']', '', title)
        # Limiter la longueur
        if len(title) > 60:
            title = title[:57] + "..."
        # Vérifier que le titre est cohérent (entre 2 et 10 mots)
        word_count = len(title.split())
        if 2 <= word_count <= 10:
            return title
        # Si trop long ou trop court, on ignore
        return None
    except Exception:
        return None