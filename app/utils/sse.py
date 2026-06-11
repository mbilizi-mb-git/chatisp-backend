from typing import AsyncGenerator, Any
from fastapi.responses import StreamingResponse


async def _sse_wrapper(token_generator: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
    """
    Internal generator that wraps a token generator and formats each token
    as a Server‑Sent Event data line.
    """
    async for token in token_generator:
        yield f"data: {token}\n\n"


def sse_stream(token_generator: AsyncGenerator[str, None]) -> StreamingResponse:
    """
    Convert an async generator yielding string tokens into a Server‑Sent Events
    StreamingResponse.

    The returned response has the correct media type and headers to disable
    buffering and keep the connection alive.

    Args:
        token_generator: An async generator that yields string tokens.

    Returns:
        A StreamingResponse configured for SSE.
    """
    return StreamingResponse(
        _sse_wrapper(token_generator),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )