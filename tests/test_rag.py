import pytest
from unittest.mock import AsyncMock, MagicMock

from app.rag.llm_engine import LLMEngine
from app.utils.title_generator import generate_title_from_message


@pytest.mark.asyncio
async def test_llm_engine_ask(mock_vector_store):
    """Test LLMEngine.ask with mocks."""
    engine = LLMEngine(mock_vector_store)
    engine.client = AsyncMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(content="Mocked answer"))]
    mock_completion.usage = MagicMock(total_tokens=10)
    engine.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    answer = await engine.ask(question="What is the capital of France?")
    assert answer == "Mocked answer"


@pytest.mark.asyncio
async def test_llm_engine_ask_stream(mock_vector_store):
    """Test LLMEngine.ask_stream with mocks."""
    engine = LLMEngine(mock_vector_store)

    async def mock_stream(*args, **kwargs):
        class Chunk:
            def __init__(self, content):
                self.choices = [MagicMock(delta=MagicMock(content=content))]
                self.usage = None
        yield Chunk("Mocked ")
        yield Chunk("stream ")
        yield Chunk("response")
        class UsageChunk:
            def __init__(self):
                self.choices = []
                self.usage = MagicMock(total_tokens=15)
        yield UsageChunk()

    engine.client.chat.completions.create = AsyncMock(return_value=mock_stream())

    tokens = []
    async for token in engine.ask_stream(question="Hello"):
        tokens.append(token)
    assert "".join(tokens) == "Mocked stream response"


def test_title_generator():
    """Test the title generation heuristic."""
    message = "Hello, I would like to know more about the history of France."
    title = generate_title_from_message(message)
    assert len(title) <= 60
    assert title


def test_title_generator_fallback():
    """Test title generator with stopword-only message."""
    message = "le la les et"
    title = generate_title_from_message(message)
    assert title == "Le La Les Et"