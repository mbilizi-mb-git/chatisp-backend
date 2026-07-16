"""
Endpoints d'authentification avec gestion d'erreurs améliorée.
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError

from app.core.database import get_db
from app.core.security import verify_google_token, decode_token, create_access_token, create_refresh_token
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    GoogleAuthRequest,
    RefreshTokenRequest,
    Token,
    UserResponse,
    EmailCheckResponse,
)
from app.services.user_service import UserService
from app.api.dependencies import get_current_user
from app.models.user import User
from app.utils.cache import email_cache  # Nouvel import

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


def format_validation_error(exc: ValidationError) -> dict:
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        msg = error["msg"]
        if "email" in field:
            errors.append("Email invalide")
        elif "password" in field and "too short" in msg:
            errors.append("Le mot de passe doit contenir au moins 6 caractères")
        elif "display_name" in field:
            errors.append("Le nom d'affichage est requis")
        else:
            errors.append(msg)
    return {"detail": errors[0] if len(errors) == 1 else errors}


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    try:
        service = UserService(db)
        user, access_token, access_exp, refresh_token, refresh_exp = await service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
        return Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=access_exp,
            refresh_token=refresh_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        error_response = format_validation_error(e)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error_response["detail"])
    except Exception as e:
        logger.exception(f"Erreur inscription: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur interne du serveur")


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    try:
        service = UserService(db)
        user = await service.authenticate(email=payload.email, password=payload.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe incorrect",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token, access_exp = create_access_token(user.id)
        refresh_token, refresh_exp = create_refresh_token(user.id)
        return Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=access_exp,
            refresh_token=refresh_token,
        )
    except HTTPException:
        raise
    except ValidationError as e:
        error_response = format_validation_error(e)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error_response["detail"])
    except Exception as e:
        logger.exception(f"Erreur login: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur interne du serveur")


@router.post("/google", response_model=Token)
async def google_auth(
    payload: GoogleAuthRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    try:
        google_data = verify_google_token(payload.id_token)
    except ValueError as e:
        logger.warning(f"Token Google invalide: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token Google invalide",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la vérification Google",
        )

    service = UserService(db)
    try:
        user, access_token, access_exp, refresh_token, refresh_exp = await service.create_or_update_google_user(
            google_data
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la création du compte Google",
        )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=access_exp,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    try:
        payload_data = decode_token(payload.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload_data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide pour le rafraîchissement",
        )

    user_id = payload_data.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalide",
        )

    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur inexistant ou inactif",
        )

    new_access_token, new_access_exp = create_access_token(user.id)
    new_refresh_token, new_refresh_exp = create_refresh_token(user.id)

    return Token(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=new_access_exp,
        refresh_token=new_refresh_token,
    )


@router.get("/check-email", response_model=EmailCheckResponse)
async def check_email(
    email: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EmailCheckResponse:
    # 1. Vérification du format
    from pydantic import EmailStr
    valid = True
    try:
        EmailStr._validate(email)
    except Exception:
        valid = False
        return EmailCheckResponse(valid=False, exists=False)

    # 2. Cache lookup (validité + existence)
    cached = email_cache.get(email)
    if cached is not None:
        # cached est un booléen (True = email existe, False = n'existe pas)
        return EmailCheckResponse(valid=True, exists=cached)

    # 3. Requête DB
    service = UserService(db)
    exists = await service.check_email_exists(email)

    # 4. Mise en cache (durée par défaut 30s)
    email_cache.set(email, exists)

    return EmailCheckResponse(valid=True, exists=exists)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    service = UserService(db)
    return await service.get_user_response(current_user)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    service = UserService(db)
    try:
        await service.delete_account(current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        logger.exception(f"Erreur suppression compte {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Impossible de supprimer le compte",
        )