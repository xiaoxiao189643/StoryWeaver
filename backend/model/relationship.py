from pydantic import BaseModel, Field
from typing import List


class Relationship(BaseModel):
    """NPC 对另一个 NPC 的主观关系数据"""
    agent_id: str
    target_id: str
    trust_value: float = Field(default=0.0, ge=-100.0, le=100.0)
    attitude: str = "中立"      # 友好 / 中立 / 冷淡 / 敌对
    history: List[str] = Field(default_factory=list)
