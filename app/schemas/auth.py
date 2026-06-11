"""
Schémas Pydantic pour l'authentification (email/mot de passe + Google).
Inclut validation, gestion des tokens JWT et réponses standardisées.
"""

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    """Requête de connexion avec email et mot de passe."""

    email: EmailStr = Field(..., description="Adresse email de l'utilisateur")
    password: str = Field(..., min_length=6, description="Mot de passe (au moins 6 caractères)")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalise l'email en minuscules et vérifie le format."""
        v = v.lower().strip()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", v):
            raise ValueError("Format d'email invalide")
        return v


class RegisterRequest(BaseModel):
    """Requête d'inscription avec email, mot de passe et nom d'affichage."""

    email: EmailStr = Field(..., description="Adresse email unique")
    password: str = Field(..., min_length=6, description="Mot de passe (6 caractères minimum)")
    display_name: str = Field(..., min_length=1, max_length=255, description="Nom affiché publiquement")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalise l'email en minuscules."""
        return v.lower().strip()

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        """Vérifie que le nom n'est pas vide après nettoyage."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Le nom d'affichage ne peut pas être vide")
        return cleaned


class GoogleAuthRequest(BaseModel):
    """Requête d'authentification Google contenant l'ID token."""

    id_token: str = Field(..., description="ID token reçu du SDK Google Sign-In")


class RefreshTokenRequest(BaseModel):
    """Requête pour rafraîchir un token (utilisé pour les comptes Google)."""

    refresh_token: str = Field(..., description="Refresh token JWT valide")


class Token(BaseModel):
    """Token d'accès JWT retourné après authentification."""

    access_token: str = Field(..., description="JWT d'accès")
    token_type: str = Field(default="bearer", description="Type de token")
    expires_in: int = Field(..., description="Durée de validité en secondes")
    refresh_token: Optional[str] = Field(None, description="Optionnel (requis pour les comptes Google)")


class EmailCheckResponse(BaseModel):
    """Réponse pour la validation d'email en temps réel."""

    valid: bool = Field(..., description="Le format de l'email est-il valide ?")
    exists: bool = Field(..., description="L'email est-il déjà utilisé ?")


class UserResponse(BaseModel):
    """Profil utilisateur retourné après connexion/inscription."""

    id: str = Field(..., description="Identifiant unique (UUID)")
    email: EmailStr = Field(..., description="Adresse email")
    display_name: str = Field(..., description="Nom affiché")
    avatar_url: Optional[str] = Field(None, description="URL de l'avatar (Google ou upload)")
    created_at: str = Field(..., description="Date d'inscription (ISO)")
    last_seen: Optional[str] = Field(None, description="Dernière activité (ISO)")
    is_google_account: bool = Field(..., description="True si le compte est lié à Google")
    is_admin: bool = Field(default=False, description="True si l'utilisateur est administrateur")

    class Config:
        from_attributes = True


class TokenPayload(BaseModel):
    """Contenu du token JWT décodé."""

    sub: str = Field(..., description="ID de l'utilisateur")
    exp: int = Field(..., description="Timestamp d'expiration")
    type: str = Field(..., description="Type de token: 'access' ou 'refresh'")