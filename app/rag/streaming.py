import json
from typing import Any, Dict


def format_sse_event(data: Dict[str, Any]) -> str:
    """
    Format a dictionary as a Server‑Sent Event (SSE) data line.

    The output is a string starting with "data: " followed by the JSON
    representation of the dictionary, and ending with two newlines.
    This format is suitable for a StreamingResponse with media_type
    "text/event-stream".

    Args:
        data: Dictionary to be sent as an SSE event.

    Returns:
        A string formatted according to the SSE specification.
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"