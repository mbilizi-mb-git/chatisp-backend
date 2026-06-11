"""
Tests des endpoints de santé (/health, /ready).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test l'endpoint /health."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_readiness_check(client: AsyncClient, session: AsyncSession):
    """Test l'endpoint /ready dans des conditions normales."""
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"

    # Simuler une panne de base de données
    async def broken_db():
        raise Exception("DB down")

    from app.api.endpoints.health import get_db
    app = client._transport.app
    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = broken_db

    response = await client.get("/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["detail"] == "Base de données non disponible"

    # Restaurer
    if original_override:
        app.dependency_overrides[get_db] = original_override
    else:
        app.dependency_overrides.pop(get_db, None)