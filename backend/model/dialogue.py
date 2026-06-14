from pydantic import BaseModel, Field
from typing import Optional


class DialogueRecord(BaseModel):
    """一条对白历史记录"""
    id: str
    world_id: str
    speaker_id: str
    speaker_name: str
    content: str
    timestamp: str
    target_id: Optional[str] = None
