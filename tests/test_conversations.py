# Tests des conversations
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.conversation import Conversation
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient, test_user: User):
    """Test creating a new conversation."""
    response = await client.post(
        "/conversations",
        headers={"X-Device-ID": test_user.id},
        json={},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["title"] is None
    assert data["is_pinned"] is False
    assert data["pinned_at"] is None
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_list_conversations_empty(client: AsyncClient, test_user: User):
    """Test listing conversations when none exist."""
    response = await client.get(
        "/conversations",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["items"] == []
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_conversations_with_items(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    session: AsyncSession,
):
    """Test listing conversations with one conversation."""
    # Add a second conversation to test ordering
    service = ConversationService(session)
    conv2 = await service.create_conversation(test_user.id)

    response = await client.get(
        "/conversations",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert len(items) == 2
    # Should be sorted by updated_at desc, so conv2 (newer) first
    assert items[0]["id"] == conv2.id
    assert items[1]["id"] == test_conversation.id
    assert data["next_cursor"] is None  # because only 2 < limit


@pytest.mark.asyncio
async def test_list_conversations_pagination(
    client: AsyncClient,
    test_user: User,
    session: AsyncSession,
):
    """Test cursor pagination."""
    service = ConversationService(session)
    # Create 5 conversations
    convs = []
    for _ in range(5):
        conv = await service.create_conversation(test_user.id)
        convs.append(conv)

    # Request limit=2
    response = await client.get(
        "/conversations",
        headers={"X-Device-ID": test_user.id},
        params={"limit": 2},
    )
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert len(items) == 2
    assert items[0]["id"] == convs[4].id  # most recent first
    assert items[1]["id"] == convs[3].id
    next_cursor = data["next_cursor"]
    assert next_cursor is not None

    # Use cursor to get next page
    response2 = await client.get(
        "/conversations",
        headers={"X-Device-ID": test_user.id},
        params={"limit": 2, "cursor": next_cursor},
    )
    data2 = response2.json()
    items2 = data2["items"]
    assert len(items2) == 2
    assert items2[0]["id"] == convs[2].id
    assert items2[1]["id"] == convs[1].id
    next_cursor2 = data2["next_cursor"]
    assert next_cursor2 is not None

    # Third page
    response3 = await client.get(
        "/conversations",
        headers={"X-Device-ID": test_user.id},
        params={"limit": 2, "cursor": next_cursor2},
    )
    data3 = response3.json()
    items3 = data3["items"]
    assert len(items3) == 1
    assert items3[0]["id"] == convs[0].id
    assert data3["next_cursor"] is None


@pytest.mark.asyncio
async def test_rename_conversation(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
):
    """Test renaming a conversation."""
    new_title = "New Title"
    response = await client.put(
        f"/conversations/{test_conversation.id}/rename",
        headers={"X-Device-ID": test_user.id},
        json={"title": new_title},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_conversation.id
    assert data["title"] == new_title
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_rename_conversation_not_found(client: AsyncClient, test_user: User):
    """Test renaming a non-existent conversation."""
    response = await client.put(
        "/conversations/does-not-exist/rename",
        headers={"X-Device-ID": test_user.id},
        json={"title": "New Title"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rename_conversation_wrong_user(
    client: AsyncClient,
    test_user: User,
    session: AsyncSession,
):
    """Test renaming a conversation belonging to another user."""
    # Create another user
    other_user = User(id="other-device")
    session.add(other_user)
    await session.commit()
    # Create conversation for other user
    conv_service = ConversationService(session)
    conv = await conv_service.create_conversation(other_user.id)

    response = await client.put(
        f"/conversations/{conv.id}/rename",
        headers={"X-Device-ID": test_user.id},
        json={"title": "Hack"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pin_conversation(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
):
    """Test pinning a conversation."""
    response = await client.patch(
        f"/conversations/{test_conversation.id}/pin",
        headers={"X-Device-ID": test_user.id},
        json={"is_pinned": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_conversation.id
    assert data["is_pinned"] is True
    assert data["pinned_at"] is not None


@pytest.mark.asyncio
async def test_unpin_conversation(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    session: AsyncSession,
):
    """Test unpinning a conversation."""
    # First pin it
    service = ConversationService(session)
    await service.pin_conversation(test_conversation.id, True)

    response = await client.patch(
        f"/conversations/{test_conversation.id}/pin",
        headers={"X-Device-ID": test_user.id},
        json={"is_pinned": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_pinned"] is False
    assert data["pinned_at"] is None


@pytest.mark.asyncio
async def test_delete_conversation(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    session: AsyncSession,
):
    """Test deleting a conversation."""
    response = await client.delete(
        f"/conversations/{test_conversation.id}",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 204

    # Verify it's gone
    service = ConversationService(session)
    conv = await service.get_conversation(test_conversation.id)
    assert conv is None


@pytest.mark.asyncio
async def test_get_conversation_detail(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    test_messages: list,
):
    """Test getting conversation detail without messages."""
    response = await client.get(
        f"/conversations/{test_conversation.id}",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_conversation.id
    assert "messages" not in data


@pytest.mark.asyncio
async def test_get_conversation_detail_with_messages(
    client: AsyncClient,
    test_user: User,
    test_conversation: Conversation,
    test_messages: list,
):
    """Test getting conversation detail including messages."""
    response = await client.get(
        f"/conversations/{test_conversation.id}",
        headers={"X-Device-ID": test_user.id},
        params={"include_messages": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_conversation.id
    assert "messages" in data
    assert len(data["messages"]) == 4  # limited to last 50, all present
    # Messages should be in chronological order
    assert data["messages"][0]["content"] == "Hello, how are you?"
    assert data["messages"][-1]["content"] == "The capital of France is Paris."


@pytest.mark.asyncio
async def test_get_conversation_detail_not_found(client: AsyncClient, test_user: User):
    """Test getting a non-existent conversation."""
    response = await client.get(
        "/conversations/does-not-exist",
        headers={"X-Device-ID": test_user.id},
    )
    assert response.status_code == 404