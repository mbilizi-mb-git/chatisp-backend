"""
Modèle SQLAlchemy pour les utilisateurs (authentification email/mot de passe + Google).
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class User(Base):
    """
    Utilisateur de l'application.
    Peut être authentifié via email/mot de passe ou via Google OAuth2.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identifiant unique (UUID v4)",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="Adresse email unique (utilisée pour la connexion)",
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Hash bcrypt du mot de passe (null pour les comptes Google)",
    )
    google_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        doc="Identifiant Google (sub), présent uniquement pour les comptes Google",
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Nom affiché publiquement (obligatoire)",
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="URL de la photo de profil (Google ou upload ultérieur)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Compte actif (soft delete possible)",
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Droits d'administration (réservé au créateur)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        doc="Date d'inscription",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        doc="Dernière mise à jour du profil",
    )
    last_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        doc="Dernière activité (connexion, requête API)",
    )

    # Relations
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        doc="Toutes les conversations de l'utilisateur (supprimées en cascade)",
    )

    # Index composites
    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
        Index("ix_users_google_id", "google_id"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} is_google={self.google_id is not None}>"