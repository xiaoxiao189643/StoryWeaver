# ============================================================
# model/intervention.py —— 玩家干预模型
# ============================================================
# 定义玩家干预（Intervention）的四种类型：
#   1. Observation（观察）
#   2. Suggestion（建议）
#   3. Persuasion（说服）
#   4. Override（强制干预）
#
# 所有干预最终由 World Simulator 验证并决定效果。
# ============================================================

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class InterventionType(str, Enum):
    """玩家干预类型"""
    OBSERVATION = "observation"       # 观察/调查
    SUGGESTION = "suggestion"         # 建议
    PERSUASION = "persuasion"         # 说服
    OVERRIDE = "override"             # 强制干预


class Observation(BaseModel):
    """观察行为：偷听、调查、跟踪等"""
    target_agent_id: Optional[str] = None
    target_location_id: Optional[str] = None
    target_item_id: Optional[str] = None
    observation_type: str = "general"  # eavesdrop / investigate / follow / search / etc.


class Suggestion(BaseModel):
    """建议：给某个 Agent 提出建议"""
    target_agent_id: str
    message: str
    context: str = ""


class Persuasion(BaseModel):
    """说服：尝试说服某个 Agent
    系统会基于信任、情绪、人格、关系计算成功率。
    """
    target_agent_id: str
    claim: str                        # 要说服的内容
    reason: str = ""                  # 理由
    emotional_appeal: str = "logic"   # logic / emotion / authority / etc.


class PlayerOverride(BaseModel):
    """强制干预：极少使用，会破坏 Agent 自主性"""
    target_agent_id: str
    forced_action: str                # 强制执行的行动
    duration_ticks: int = 5           # 持续 tick 数


class InterventionRequest(BaseModel):
    """
    玩家干预请求 —— 统一入口。
    所有玩家输入先解析为 InterventionRequest，
    再由 Intervention Service 处理。
    """
    type: InterventionType
    observation: Optional[Observation] = None
    suggestion: Optional[Suggestion] = None
    persuasion: Optional[Persuasion] = None
    override: Optional[PlayerOverride] = None
    player_id: str = "player"         # 支持多玩家扩展


class InterventionResult(BaseModel):
    """干预处理结果"""
    accepted: bool                     # 是否生效
    effectiveness: float = 0.0        # 效果程度 0~1
    narrative_feedback: str = ""       # 叙事反馈文本
    trust_delta: float = 0.0          # 信任变化
    emotion_delta: str = "neutral"    # 情绪变化
