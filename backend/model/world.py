# ============================================================
# model/world.py —— 世界状态模型
# ============================================================
# 定义"客观真相层"（World Truth）的数据结构。
# 包括：地点（Location）、物品（Item）、关系（Relationship）、
# 时间（GameTime）、全局状态（WorldState）等。
#
# 这些数据由 World Simulator 严格维护，不可由 Agent 直接修改。
# ============================================================

from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from enum import Enum


class LocationType(str, Enum):
    """地点类型"""
    ROOM = "room"
    CORRIDOR = "corridor"
    OUTDOOR = "outdoor"
    VEHICLE = "vehicle"


class Location(BaseModel):
    """场景中的一个地点（房间/区域）"""
    id: str
    name: str
    type: LocationType = LocationType.ROOM
    description: str = ""
    connected_to: List[str] = Field(default_factory=list)  # 相邻地点 ID
    locked: bool = False
    lock_key_id: Optional[str] = None
    # 可容纳的角色上限（-1 表示无限制）
    capacity: int = -1


class Item(BaseModel):
    """场景中的物品"""
    id: str
    name: str
    description: str = ""
    location_id: Optional[str] = None        # 所在地点
    held_by: Optional[str] = None            # 持有者 Agent ID
    is_hidden: bool = False                  # 是否被隐藏
    is_key_item: bool = False                # 是否关键物品


class Relationship(BaseModel):
    """两个角色之间的关系状态"""
    agent_a: str
    agent_b: str
    trust: float = 0.0          # -1.0 ~ 1.0
    familiarity: float = 0.0    # 0.0 ~ 1.0
    sentiment: float = 0.0      # -1.0 ~ 1.0（好感度）
    last_interaction_tick: int = 0


class GameTime(BaseModel):
    """游戏内时间"""
    tick: int = 0               # 总 tick 数
    day: int = 1
    hour: int = 8               # 0-23
    minute: int = 0             # 0-59
    phase: str = "morning"      # morning / afternoon / evening / night


class WorldTruth(BaseModel):
    """
    客观真相 —— 系统的"唯一真实世界"。
    - 任何实体（玩家/Agent/导演）都不能直接修改。
    - 只能通过 World Simulator 的 Intent → Resolution 流程改变。
    """
    locations: Dict[str, Location] = Field(default_factory=dict)
    items: Dict[str, Item] = Field(default_factory=dict)
    relationships: Dict[str, Relationship] = Field(default_factory=dict)
    time: GameTime = Field(default_factory=GameTime)
    # agent_id → location_id，记录每个 Agent 的当前位置
    agent_locations: Dict[str, str] = Field(default_factory=dict)
    # 秘密真相（角色默认不知道，需调查发现）
    secrets: Dict[str, str] = Field(default_factory=dict)
    # 已发生的关键事件日志
    event_log: List[str] = Field(default_factory=list)