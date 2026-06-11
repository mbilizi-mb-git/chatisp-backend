# ChatISP AI Backend v1.0

**Créateur** : MBILIZI  WABENGA DEMBI
**Assistant IA universitaire** conçu pour l'ISP/Bukavu, optimisé mobile‑first.

## Stack technique

- **Framework** : FastAPI (asynchrone)
- **Base de données** : SQLite + SQLAlchemy 2.0 (async)
- **Vector store** : ChromaDB (persistant)
- **Embeddings** : Sentence‑Transformers (`all-MiniLM-L6-v2`)
- **LLM** : Groq (API distante)
- **Logging** : JSON structuré (structlog)

## Installation

1. **Cloner le dépôt** (ou placer les fichiers dans `chatisp-backend/`).
2. **Créer un environnement virtuel** :

   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   venv\Scripts\activate      # Windows
