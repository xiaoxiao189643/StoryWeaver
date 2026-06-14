# ============================================================
# model/agent.py —— 角色 Agent 数据模型
# ============================================================
# 定义每个 Agent 的完整状态，包括：
#   - 人格（Personality）
#   - 目标（Goal）
#   - 记忆（Memory）
#   - 情绪（Emotion）
#   - 认知（Belief）
#   - 位置（Location）
# ============================================================

from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from enum import Enum


class PersonalityTrait(str, Enum):
    """人格特质（参考 Big Five 简化版）"""
    OPENNESS = "openness"           # 开放性
    CONSCIENTIOUSNESS = "conscientiousness"  # 尽责性
    EXTRAVERSION = "extraversion"   # 外向性
    AGREEABLENESS = "agreeableness" # 宜人性
    NEUROTICISM = "neuroticism"     # 神经质


class Personality(BaseModel):
    """角色人格配置"""
    traits: Dict[PersonalityTrait, float] = Field(default_factory=lambda: {
        PersonalityTrait.OPENNESS: 0.5,
        PersonalityTrait.CONSCIENTIOUSNESS: 0.5,
        PersonalityTrait.EXTRAVERSION: 0.5,
        PersonalityTrait.AGREEABLENESS: 0.5,
        PersonalityTrait.NEUROTICISM: 0.5,
    })
    # 角色的核心行为倾向描述（给 LLM 的 system prompt 素材）
    core_description: str = ""


class EmotionalState(BaseModel):
    """角色情绪状态"""
    # 基础情绪维度
    arousal: float = 0.0       # 0.0 ~ 1.0（激活度）
    valence: float = 0.0       # -1.0 ~ 1.0（效价）
    # 具体情绪标签
    current_mood: str = "平静"  # 平静 / 焦虑 / 紧张 / 冷静 / 愤怒 / 悲伤 / 恐惧 / 惊讶 / 怀疑 / 困惑 / 坚定 / 担忧
    intensity: float = 0.5     # 当前情绪强度


class Goal(BaseModel):
    """角色当前目标"""
    id: str
    description: str
    priority: int = 5          # 1-10
    is_active: bool = True
    progress: float = 0.0      # 0.0 ~ 1.0
    deadline_tick: Optional[int] = None


class Belief(BaseModel):
    """
    角色对世界的"主观认知"。
    可能正确，也可能错误、过时或被误导。
    这是角色 Agent 做决策的依据，而非 World Truth。
    """
    # 角色认为的"事实"
    facts: Dict[str, str] = Field(default_factory=dict)
    # 角色对其他人/事的相信程度
    certainty: Dict[str, float] = Field(default_factory=dict)
    # 角色对其他人的怀疑
    suspicions: Dict[str, float] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    """一条记忆"""
    id: str
    world_id: str = "default_world"
    tick: int                      # 发生时的游戏 tick
    content: str                   # 记忆内容（文本）
    importance: float = 0.5        # 重要性 0~1
    emotion_tag: str = "平静"   # 情绪标签
    is_retrieved: bool = False     # 是否已被召回
    scope: str = "agent"           # 记忆范围：agent / global
    metadata: dict = {}            # 附加元数据


class AgentState(BaseModel):
    """
    一个角色 Agent 的完整运行时状态。
    每个 Agent 对应一个 LLM 驱动的 autonomous 角色。
    """
    id: str
    name: str
    personality: Personality = Field(default_factory=Personality)
    emotion: EmotionalState = Field(default_factory=EmotionalState)
    goals: List[Goal] = Field(default_factory=list)
    belief: Belief = Field(default_factory=Belief)
    knowledge: Dict[str, str] = Field(default_factory=dict)  # 角色知道的信息
    location_id: Optional[str] = None
    
    # 当前行为状态
    current_action: str = "idle"
    current_action_type: str = "idle"
    action_progress: float = 0.0
    
    # 与玩家的关系
    trust_player: float = 0.0     # -1.0 ~ 1.0
    is_controlled: bool = False    # 是否被玩家强制控制

    class Config:
        # 让 Agent 可以放入 LangGraph 状态
        frozen = False
