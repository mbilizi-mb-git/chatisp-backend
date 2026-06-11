"""
Fixtures pour les tests d'intégration avec authentification JWT.
"""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.database import Base, get_db
from app.core.config import get_settings
from app.core.security import hash_password, create_access_token
from app.main import app
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.user_service import UserService
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.rag.vector_store import VectorStore
from app.rag.llm_engine import LLMEngine

# Base de données en mémoire pour les tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    """Crée un moteur de base de données de test en mémoire."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Crée une session de base de données de test."""
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Crée un client HTTP de test avec remplacement de la dépendance get_db."""
    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(session: AsyncSession) -> User:
    """Crée un utilisateur de test avec email et mot de passe."""
    service = UserService(session)
    user, _, _, _, _ = await service.register(
        email="test@example.com",
        password="test123456",
        display_name="Test User",
    )
    return user


@pytest_asyncio.fixture
async def test_user_token(test_user: User) -> str:
    """Génère un token JWT pour l'utilisateur de test."""
    token, _ = create_access_token(test_user.id)
    return token


@pytest_asyncio.fixture
async def auth_headers(test_user_token: str) -> Dict[str, str]:
    """En-têtes d'authentification pour les requêtes protégées."""
    return {"Authorization": f"Bearer {test_user_token}"}


@pytest_asyncio.fixture
async def test_conversation(session: AsyncSession, test_user: User) -> Conversation:
    """Crée une conversation de test pour l'utilisateur."""
    service = ConversationService(session)
    conv = await service.create_conversation(test_user.id)
    return conv


@pytest_asyncio.fixture
async def test_messages(session: AsyncSession, test_conversation: Conversation) -> list[Message]:
    """Crée des messages de test dans la conversation."""
    service = MessageService(session)
    msgs = []
    msgs.append(await service.create_message(test_conversation.id, "user", "Hello, how are you?"))
    msgs.append(await service.create_message(test_conversation.id, "assistant", "I'm fine, thank you!"))
    msgs.append(await service.create_message(test_conversation.id, "user", "What is the capital of France?"))
    msgs.append(await service.create_message(test_conversation.id, "assistant", "The capital of France is Paris."))
    return msgs


@pytest.fixture
def mock_vector_store() -> Generator[MagicMock, None, None]:
    """Mock du VectorStore pour éviter ChromaDB."""
    with patch("app.rag.vector_store.VectorStore", autospec=True) as mock:
        instance = mock.return_value
        instance.similarity_search = AsyncMock(return_value=[])
        instance.add_documents = AsyncMock()
        instance.ensure_collection = AsyncMock()
        yield instance


@pytest.fixture
def mock_llm_engine() -> Generator[MagicMock, None, None]:
    """Mock du LLMEngine pour éviter Groq."""
    with patch("app.rag.llm_engine.LLMEngine", autospec=True) as mock:
        instance = mock.return_value
        instance.ask = AsyncMock(return_value="Mocked response")
        async def _mock_stream(*args, **kwargs):
            yield "Mocked "
            yield "stream "
            yield "response"
        instance.ask_stream = _mock_stream
        yield instance