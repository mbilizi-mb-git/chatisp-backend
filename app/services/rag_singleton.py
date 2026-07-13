"""
Module pour stocker l'instance globale de RagService (singleton).
Évite les imports circulaires entre main.py et endpoints.
"""

_rag_service = None


def set_rag_service(service):
    """Définit l'instance globale de RagService."""
    global _rag_service
    _rag_service = service


def get_rag_service():
    """Retourne l'instance globale de RagService."""
    return _rag_service