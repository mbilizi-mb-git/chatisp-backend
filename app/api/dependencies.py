"""
Dépendances FastAPI pour l'injection de session DB, l'authentification JWT,
et la vérification des droits administrateur.
"""

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
import jwt

from app.core.database import get_db
from app.core.security import decode_token
from app.services.user_service import UserService
from app.models.user import User
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Security scheme for Bearer token
security = HTTPBearer(auto_error=False)


async def _update_last_seen_background(user_id: str, db: AsyncSession) -> None:
    """
    Tâche de fond pour mettre à jour last_seen sans bloquer la requête.
    Gère ses propres erreurs et rollback.
    """
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as new_session:
            service = UserService(new_session)
            await service.update_last_seen(user_id)
            await new_session.commit()
        logger.debug(f"Last_seen mis à jour en arrière-plan pour l'utilisateur {user_id}")
    except Exception as e:
        logger.error(f"Échec de la mise à jour last_seen en arrière-plan pour {user_id}: {e}")


async def get_current_user(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> User:
    """
    Dépendance pour récupérer l'utilisateur authentifié à partir du JWT.
    
    Returns:
        User: L'utilisateur correspondant au token
        
    Raises:
        HTTPException: 401 si token manquant, invalide, expiré, ou utilisateur inexistant/inactif
    """
    if creds is None or not creds.credentials:
        logger.warning("Tentative d'accès sans token JWT")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = creds.credentials
    
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            logger.warning(f"Tentative d'utilisation d'un token non-access: {payload.get('type')}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide (type incorrect)",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = payload.get("sub")
        if not user_id:
            logger.warning("Token JWT sans subject (sub)")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide (subject manquant)",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.ExpiredSignatureError:
        logger.warning("Token JWT expiré")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token JWT invalide: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.exception(f"Erreur inattendue lors du décodage du token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Erreur d'authentification",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if not user:
        logger.warning(f"Utilisateur introuvable pour l'ID {user_id} (token valide)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur inexistant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        logger.warning(f"Tentative d'accès avec compte inactif: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé",
        )
    
    # Mise à jour asynchrone de last_seen (non bloquante)
    asyncio.create_task(_update_last_seen_background(user.id, db))
    
    logger.debug(f"Utilisateur authentifié: {user.email} (id={user.id})")
    return user


async def get_current_admin_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Dépendance pour vérifier que l'utilisateur authentifié est administrateur.
    À utiliser pour protéger les endpoints d'administration.
    
    Returns:
        User: L'utilisateur admin
        
    Raises:
        HTTPException: 403 si l'utilisateur n'est pas admin
    """
    if not current_user.is_admin:
        logger.warning(f"Tentative d'accès admin par {current_user.email} (non autorisé)")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Droits administrateur requis",
        )
    return current_user


# Re-export de get_db pour les autres modules
get_db = get_db