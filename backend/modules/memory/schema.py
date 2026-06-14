from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DialogueRecord(BaseModel):
    """One stored dialogue message and its optional memory metadata."""

    id: str
    world_id: str
    speaker_id: str
    speaker_name: str
    content: str
    timestamp: str
    target_id: Optional[str] = None
    tick: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
