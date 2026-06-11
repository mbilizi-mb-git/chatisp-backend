from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class BootstrapResponse(BaseModel):
    """Response returned by the /bootstrap endpoint."""

    device_id: str = Field(..., description="Unique device identifier (UUID4)")
    created_at: datetime = Field(..., description="Timestamp when the user was created")
    last_seen: Optional[datetime] = Field(None, description="Last activity timestamp")

    model_config = ConfigDict(from_attributes=True)