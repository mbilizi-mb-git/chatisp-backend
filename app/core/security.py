"""
Sécurité : hachage de mots de passe (bcrypt direct), JWT, vérification Google Token.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple

import bcrypt
import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def hash_password(password: str) -> str:
    """
    Hache un mot de passe avec bcrypt.
    Troncature automatique à 72 octets si nécessaire.
    
    Args:
        password: Mot de passe en clair
        
    Returns:
        Hash du mot de passe (string)
        
    Raises:
        ValueError: Si le mot de passe est vide
    """
    if not password or not password.strip():
        logger.error("Tentative de hachage d'un mot de passe vide")
        raise ValueError("Le mot de passe ne peut pas être vide")
    
    # Convertir en bytes et tronquer à 72 octets
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
        logger.warning("Mot de passe tronqué à 72 octets pour bcrypt")
    
    # Générer le salt et le hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    # Retourner le hash en tant que string
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie un mot de passe en clair contre un hash bcrypt.
    
    Args:
        plain_password: Mot de passe en clair
        hashed_password: Hash stocké (string)
        
    Returns:
        True si le mot de passe correspond, False sinon
    """
    if not plain_password or not hashed_password:
        logger.warning("Tentative de vérification avec paramètres vides")
        return False
    
    # Convertir en bytes
    plain_bytes = plain_password.encode('utf-8')
    if len(plain_bytes) > 72:
        plain_bytes = plain_bytes[:72]
    
    hashed_bytes = hashed_password.encode('utf-8')
    
    try:
        result = bcrypt.checkpw(plain_bytes, hashed_bytes)
        logger.debug(f"Vérification du mot de passe: {'réussie' if result else 'échouée'}")
        return result
    except Exception as e:
        logger.error(f"Erreur lors de la vérification bcrypt: {e}")
        return False


def create_access_token(user_id: str, expires_delta: Optional[timedelta] = None) -> Tuple[str, int]:
    """
    Crée un token JWT d'accès.
    
    Args:
        user_id: Identifiant de l'utilisateur
        expires_delta: Durée de validité (par défaut settings.ACCESS_TOKEN_EXPIRE_DAYS jours)
        
    Returns:
        Tuple (token, expiration_timestamp)
    """
    if expires_delta is None:
        expires_delta = timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
    
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": user_id,
        "exp": int(expire.timestamp()),
        "type": "access",
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    encoded = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    logger.debug(f"Token d'accès créé pour l'utilisateur {user_id}, expire dans {expires_delta}")
    return encoded, int(expire.timestamp())


def create_refresh_token(user_id: str, expires_delta: Optional[timedelta] = None) -> Tuple[str, int]:
    """
    Crée un token JWT de rafraîchissement (longue durée pour Google, configurable).
    
    Args:
        user_id: Identifiant de l'utilisateur
        expires_delta: Durée de validité (par défaut settings.REFRESH_TOKEN_EXPIRE_DAYS)
        
    Returns:
        Tuple (refresh_token, expiration_timestamp)
    """
    if expires_delta is None:
        expires_delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": user_id,
        "exp": int(expire.timestamp()),
        "type": "refresh",
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    encoded = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    logger.debug(f"Token de rafraîchissement créé pour l'utilisateur {user_id}")
    return encoded, int(expire.timestamp())


def decode_token(token: str) -> Dict[str, Any]:
    """
    Décode et vérifie un token JWT.
    
    Args:
        token: Token JWT
        
    Returns:
        Payload décodé
        
    Raises:
        jwt.InvalidTokenError: Si le token est invalide ou expiré
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
        logger.debug("Token décodé avec succès")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expiré")
        raise
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token invalide: {e}")
        raise


def verify_google_token(id_token_str: str) -> Optional[Dict[str, Any]]:
    """
    Vérifie l'ID token Google et retourne les informations utilisateur.
    
    Args:
        id_token_str: ID token reçu du client
        
    Returns:
        Dictionnaire contenant les informations (sub, email, name, picture) ou None si invalide
        
    Raises:
        ValueError: Si le token est invalide ou l'audience incorrecte
    """
    try:
        # Vérifier le token avec Google
        info = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            audience=settings.GOOGLE_CLIENT_ID,
        )
        
        # Vérifications supplémentaires
        if info.get("aud") != settings.GOOGLE_CLIENT_ID:
            logger.error("Audience Google incorrecte")
            raise ValueError("Audience invalide")
        
        # Extraire les données nécessaires
        user_data = {
            "google_id": info.get("sub"),
            "email": info.get("email"),
            "display_name": info.get("name", info.get("email").split("@")[0]),
            "avatar_url": info.get("picture"),
            "email_verified": info.get("email_verified", False),
        }
        
        if not user_data["email"]:
            logger.error("Token Google sans email")
            raise ValueError("Email manquant dans le token Google")
        
        logger.info(f"Token Google vérifié pour {user_data['email']}")
        return user_data
        
    except ValueError as e:
        logger.error(f"Échec de vérification du token Google: {e}")
        raise
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la vérification Google: {e}")
        raise