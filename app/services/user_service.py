"""
Service utilisateur pour la gestion des comptes (email/mot de passe, Google, suppression, etc.).
"""

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token
from app.schemas.auth import UserResponse
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class UserService:
    """Service pour la gestion des utilisateurs (création, authentification, suppression)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Méthodes publiques
    # ------------------------------------------------------------------

    async def register(
        self, email: str, password: str, display_name: str
    ) -> Tuple[User, str, int, Optional[str], int]:
        """
        Inscription d'un nouvel utilisateur avec email et mot de passe.
        
        Args:
            email: Adresse email
            password: Mot de passe en clair
            display_name: Nom affiché
            
        Returns:
            Tuple (user, access_token, access_expires_in, refresh_token, refresh_expires_in)
            
        Raises:
            ValueError: Si l'email existe déjà
        """
        existing = await self.get_by_email(email)
        if existing:
            logger.warning(f"Tentative d'inscription avec email existant: {email}")
            raise ValueError("Cet email est déjà utilisé")

        hashed = hash_password(password)
        
        user = User(
            email=email,
            hashed_password=hashed,
            display_name=display_name,
            is_active=True,
            is_admin=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        access_token, access_exp = create_access_token(user.id)
        refresh_token, refresh_exp = create_refresh_token(user.id)

        logger.info(f"Nouvel utilisateur inscrit: {user.email} (id={user.id})")
        return user, access_token, access_exp, refresh_token, refresh_exp

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """
        Authentifie un utilisateur par email et mot de passe.
        """
        user = await self.get_by_email(email)
        if not user:
            logger.warning(f"Tentative d'authentification avec email inexistant: {email}")
            return None
        
        if user.hashed_password is None:
            logger.warning(f"Compte Google tentant une connexion par mot de passe: {email}")
            return None
        
        if not verify_password(password, user.hashed_password):
            logger.warning(f"Mot de passe incorrect pour: {email}")
            return None
        
        if not user.is_active:
            logger.warning(f"Tentative de connexion sur compte inactif: {email}")
            return None
        
        await self.update_last_seen(user.id)
        logger.info(f"Utilisateur authentifié: {email}")
        return user

    async def create_or_update_google_user(
        self, google_data: dict
    ) -> Tuple[User, str, int, Optional[str], int]:
        """
        Crée ou met à jour un utilisateur à partir des données Google.
        """
        email = google_data["email"]
        google_id = google_data["google_id"]
        display_name = google_data["display_name"]
        avatar_url = google_data.get("avatar_url")

        existing = await self.get_by_email(email)
        if existing and existing.google_id is None:
            logger.warning(f"Email {email} déjà utilisé pour un compte email/mdp")
            raise ValueError(
                "Cet email est déjà utilisé avec un mot de passe. Veuillez vous connecter avec email et mot de passe."
            )

        if existing and existing.google_id == google_id:
            user = existing
            if avatar_url:
                user.avatar_url = avatar_url
            if user.display_name != display_name:
                user.display_name = display_name
            user.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(user)
            logger.info(f"Compte Google mis à jour: {email}")
        else:
            user = User(
                email=email,
                google_id=google_id,
                display_name=display_name,
                avatar_url=avatar_url,
                hashed_password=None,
                is_active=True,
                is_admin=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            logger.info(f"Nouveau compte Google créé: {email}")

        access_token, access_exp = create_access_token(user.id)
        refresh_token, refresh_exp = create_refresh_token(user.id)

        await self.update_last_seen(user.id)

        return user, access_token, access_exp, refresh_token, refresh_exp

    async def get_by_email(self, email: str) -> Optional[User]:
        """Récupère un utilisateur par son email."""
        result = await self.db.execute(
            select(User).where(User.email == email, User.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Récupère un utilisateur par son ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        return result.scalar_one_or_none()

    async def update_last_seen(self, user_id: str) -> None:
        """Met à jour le timestamp last_seen de l'utilisateur."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(last_seen=datetime.utcnow())
        )
        await self.db.execute(stmt)
        await self.db.commit()
        logger.debug(f"last_seen mis à jour pour l'utilisateur {user_id}")

    async def delete_account(self, user_id: str) -> None:
        """Supprime définitivement un utilisateur et toutes ses données (cascade)."""
        user = await self.get_by_id(user_id)
        if not user:
            logger.error(f"Tentative de suppression d'un utilisateur inexistant: {user_id}")
            raise ValueError("Utilisateur non trouvé")

        email = user.email

        stmt = delete(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        await self.db.commit()

        if result.rowcount == 0:
            logger.error(f"Échec de la suppression pour {user_id}")
            raise ValueError("Impossible de supprimer l'utilisateur")

        logger.info(f"Compte et toutes ses données supprimés: {email} (id={user_id})")

    async def check_email_exists(self, email: str) -> bool:
        """Vérifie si un email est déjà utilisé (actif)."""
        user = await self.get_by_email(email)
        return user is not None

    async def get_user_response(self, user: User) -> UserResponse:
        """Convertit un modèle User en UserResponse."""
        return UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            created_at=user.created_at.isoformat(),
            last_seen=user.last_seen.isoformat() if user.last_seen else None,
            is_google_account=(user.google_id is not None),
            is_admin=user.is_admin,  # ← AJOUT CRUCIAL
        )