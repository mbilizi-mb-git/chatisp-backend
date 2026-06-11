"""
Configuration centralisée de l'application utilisant Pydantic Settings.
Les variables sont chargées depuis le fichier .env à la racine du projet.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# Racine du projet (là où se trouve le dossier app/)
BASE_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """Paramètres de l'application chargés depuis les variables d'environnement."""

    # Application
    APP_NAME: str = "ChatISP AI"
    CREATOR: str = "MBILIZI"
    DEBUG: bool = False

    # Base de données (PostgreSQL recommandé en production)
    # Exemple de format pour PostgreSQL : postgresql+asyncpg://user:pass@localhost:5432/dbname
    DATABASE_URL: str = "postgresql+asyncpg://chatisp_user:change_me@localhost:5432/chatisp_db"

    # Pour faciliter le déploiement, on peut aussi décomposer (optionnel)
    POSTGRES_USER: str = "chatisp_user"
    POSTGRES_PASSWORD: str = "change_me"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "chatisp_db"

    # Sécurité JWT
    JWT_SECRET_KEY: str = "change_this_in_production_use_env_variable"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 30          # 30 jours pour email/mdp
    REFRESH_TOKEN_EXPIRE_DAYS: int = 180        # 6 mois pour Google

    # Google OAuth2
    GOOGLE_CLIENT_ID: str = ""   # À remplir dans .env

    # RAG & Embeddings
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    CHROMA_PATH: str = str(BASE_DIR / "data" / "vector_store")
    SIMILARITY_THRESHOLD: float = 0.75

    # Mémoire conversationnelle
    MEMORY_LIMIT: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = str(BASE_DIR / "data" / "logs" / "app.json")

    # Cache
    CACHE_DIR: str = str(BASE_DIR / "data" / "cache")

    # CORS
    CORS_ORIGINS: str = "*"

    # Limites Groq (optionnelles, gardées pour compatibilité)
    GROQ_API_KEY: str = ""
    MODEL_NAME: str = ""
    TEMPERATURE: float = 0.7
    MAX_TOKENS: int = 4096
    GROQ_RATE_LIMIT_MAX_CALLS: int = 30
    GROQ_RATE_LIMIT_PERIOD: int = 60
    GROQ_RATE_LIMIT_MAX_WAIT: int = 10
    GROQ_DAILY_TOKEN_QUOTA: int = 1_000_000

    @property
    def cors_origins_list(self) -> List[str]:
        """Retourne la liste des origines autorisées pour CORS."""
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        """Retourne l'URL de connexion à la base de données,
        en priorité depuis DATABASE_URL, sinon construite depuis les composants."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignorer les variables inconnues
    )


@lru_cache
def get_settings() -> Settings:
    """Retourne une instance unique (cachée) des paramètres."""
    return Settings()