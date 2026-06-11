# Tests des messages
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.conversation import Conversation
from app.services.message_service import MessageService


@pytest.mark.asyncio
async def test_chat_stream(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    mock_vector_store,
    mock_llm_engine,
):
    """Test sending a message and receiving a stream."""
    response = await client.post(
        "/chat/stream",
        headers={"X-Device-ID": test_user.id},
        json={"conversation_id": test_conversation.id, "content": "Hello"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"

    content = ""
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            import json
            data = json.loads(line[5:])
            if "token" in data:
                content += data["token"]
            elif data.get("done"):
                assert "message_id" in data
                break
    assert content == "Mocked stream response"


@pytest.mark.asyncio
async def test_chat_stream_conversation_not_found(client: AsyncClient, test_user: User):
    """Test streaming with non-existent conversation."""
    response = await client.post(
        "/chat/stream",
        headers={"X-Device-ID": test_user.id},
        json={"conversation_id": "invalid", "content": "Hello"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_messages(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    test_messages: list,
):
    """Test retrieving messages with pagination."""
    response = await client.get(
        f"/conversations/{test_conversation.id}/messages",
        headers={"X-Device-ID": test_user.id},
        params={"limit": 2},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "next_cursor" in data
    items = data["items"]
    assert len(items) == 2
    assert items[0]["content"] == "Hello, how are you?"
    assert items[1]["content"] == "I'm fine, thank you!"
    next_cursor = data["next_cursor"]
    assert next_cursor is not None

    response2 = await client.get(
        f"/conversations/{test_conversation.id}/messages",
        headers={"X-Device-ID": test_user.id},
        params={"limit": 2, "before": next_cursor},
    )
    data2 = response2.json()
    items2 = data2["items"]
    assert len(items2) == 2
    assert items2[0]["content"] == "What is the capital of France?"
    assert items2[1]["content"] == "The capital of France is Paris."
    assert data2["next_cursor"] is None


@pytest.mark.asyncio
async def test_get_messages_empty(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
):
    """Test getting messages when there are none."""
    response = await client.get(
        f"/conversations/{test_conversation.id}/messages",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_regenerate_response(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    test_messages: list,
    mock_vector_store,
    mock_llm_engine,
    session: AsyncSession,
):
    """Test regenerating the last assistant response."""
    msg_service = MessageService(session)
    last_assistant = await msg_service.get_last_messages(test_conversation.id, limit=1)
    assert last_assistant[0].role == "assistant"
    old_id = last_assistant[0].id
    old_content = last_assistant[0].content

    response = await client.post(
        f"/conversations/{test_conversation.id}/regenerate",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"

    content = ""
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            import json
            data = json.loads(line[5:])
            if "token" in data:
                content += data["token"]
            elif data.get("done"):
                new_id = data["message_id"]
                break

    new_assistant = await msg_service.get_last_messages(test_conversation.id, limit=1)
    assert new_assistant[0].id != old_id
    assert new_assistant[0].content == "Mocked stream response"

    old_exists = await session.get(MessageService.model, old_id)  # type: ignore
    assert old_exists is None


@pytest.mark.asyncio
async def test_regenerate_no_assistant(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    session: AsyncSession,
    mock_vector_store,
    mock_llm_engine,
):
    """Test regenerate when there is no assistant message (only user)."""
    msg_service = MessageService(session)
    await msg_service.create_message(test_conversation.id, "user", "Hello")

    response = await client.post(
        f"/conversations/{test_conversation.id}/regenerate",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"

    # Read stream to ensure it works
    content = ""
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            import json
            data = json.loads(line[5:])
            if "token" in data:
                content += data["token"]
            elif data.get("done"):
                new_id = data["message_id"]
                break

    # Verify a new assistant message was created
    last_msgs = await msg_service.get_last_messages(test_conversation.id, limit=1)
    assert last_msgs[0].role == "assistant"
    assert last_msgs[0].content == "Mocked stream response"


@pytest.mark.asyncio
async def test_regenerate_conversation_not_found(client: AsyncClient, test_user: User):
    """Test regenerate on non-existent conversation."""
    response = await client.post(
        "/conversations/invalid/regenerate",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 404