import re
from collections import Counter
from typing import List, Set

# French stopwords (reused from title_generator)
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


def truncate_preview(text: str, max_chars: int = 120) -> str:
    """
    Truncate a text to create a preview.

    The text is stripped of leading/trailing whitespace and newlines are
    replaced with spaces. If the resulting length exceeds max_chars, it is
    cut and an ellipsis ("…") is appended.

    Args:
        text: The original text.
        max_chars: Maximum number of characters allowed.

    Returns:
        A preview string.
    """
    # Normalize whitespace
    clean = re.sub(r"\s+", " ", text.strip())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1] + "…"


def clean_text(text: str) -> str:
    """
    Clean a text by removing extra whitespace and normalizing punctuation.

    This function:
      - Strips leading/trailing spaces.
      - Replaces multiple spaces or newlines with a single space.
      - (Optionally) could remove control characters, but kept simple.

    Args:
        text: Input text.

    Returns:
        Cleaned text.
    """
    # Remove any control characters (except newline/tab) - simple approach
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Replace any sequence of whitespace (including newlines) with a single space
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_keywords(text: str, limit: int = 5) -> List[str]:
    """
    Extract the most relevant keywords from a text.

    The text is tokenized, stopwords are removed, and the remaining words
    are counted by frequency. The top `limit` most frequent words are returned.

    Args:
        text: Input text.
        limit: Maximum number of keywords to return.

    Returns:
        List of keywords (lowercase, without punctuation).
    """
    # Normalize and tokenize
    text = text.lower()
    words = re.findall(r"\b\w+\b", text)

    # Filter stopwords and very short words
    filtered = [w for w in words if w not in FRENCH_STOPWORDS and len(w) > 2]

    # Count frequencies
    counter = Counter(filtered)
    # Get most common
    most_common = counter.most_common(limit)
    return [word for word, _ in most_common]