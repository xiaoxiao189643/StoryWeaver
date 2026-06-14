# ============================================================
# model/narrative.py —— 导演后端数据模型
# ============================================================
# 所有导演相关的数据结构都定义在这里。
# 使用 Pydantic BaseModel，方便做类型校验和 JSON 序列化。
#
# 依赖关系：
#   - 被 director/ 所有子模块导入
#   - 被 api/routes.py 用于返回给前端
#   - 被 world_simulator.py 用于状态同步
# ============================================================

from __future__ import annotations

from enum import IntEnum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
import time


# ============================================================
# 枚举：紧张度等级
# ============================================================

class TensionLevel(IntEnum):
    """
    叙事紧张度等级。
    
    导演通过调整这个值来控制整体氛围：
      CALM       → 角色正常互动，玩家可以探索
      TENSE      → 开始出现猜疑和冲突，信息量增加
      CRISIS     → 危机爆发，迫使角色做出关键选择
      RESOLUTION → 真相即将揭示，叙事走向收束
    
    IntEnum 的好处：可以直接做数值比较（CRISIS > TENSE）
    前端接收的是整数，需要在 API 层转成字符串描述。
    """
    CALM = 0
    TENSE = 1
    CRISIS = 2
    RESOLUTION = 3

    def label(self) -> str:
        """返回可读标签，用于前端展示和日志"""
        return {
            TensionLevel.CALM:       "平静",
            TensionLevel.TENSE:      "紧张",
            TensionLevel.CRISIS:     "危机",
            TensionLevel.RESOLUTION: "收束",
        }[self]


# ============================================================
# 叙事事件（NarrativeEvent）
# ============================================================

class NarrativeEvent(BaseModel):
    """
    一个叙事事件，代表导演在世界里触发的具体变化。
    
    事件类型（type）目前支持：
      blackout      → 停电，影响所有人的视野和行动
      broadcast     → 广播通知，传递信息或营造氛围
      alarm         → 警报，制造紧张感
      murder        → 谋杀发生（核心剧情事件）
      weather_change → 天气变化，影响场景氛围
      new_arrival   → 新角色出现
      convergence_trigger → 收束触发器（导演强制拉回主线）
    
    使用流程：
      1. EventScheduler 创建并存入 DirectorState.scheduled_events
      2. 每个 tick，EventScheduler 检查 scheduled_tick 是否到期
      3. 到期后 is_triggered = True，由 DirectorService 执行
      4. 执行后通过 EventBus 发布到 World Simulator
    """

    # 唯一 ID，默认自动生成 UUID
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # 事件类型，对应上面的类型列表
    type: str

    # 计划在哪个 tick 触发
    scheduled_tick: int

    # 影响的地点列表（location_id），空列表表示全局事件
    affected_locations: List[str] = Field(default_factory=list)

    # 影响的角色列表（agent_id），空列表表示影响所有人
    affected_agents: List[str] = Field(default_factory=list)

    # 事件描述，用于日志、前端展示、LLM 上下文
    description: str = ""

    # 是否已触发（防止重复触发）
    is_triggered: bool = False

    # 事件优先级，数字越大越优先（用于同 tick 多事件排序）
    priority: int = 0

    # 事件元数据，存放事件类型特有的数据
    # 例如 murder 事件可以存放 {"victim": "agent_001", "weapon": "knife"}
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # 事件创建时间戳（Unix 时间）
    created_at: float = Field(default_factory=time.time)


# ============================================================
# 场景目标（SceneGoal）
# ============================================================

class SceneGoal(BaseModel):
    """
    导演对当前场景的目标描述。
    
    SceneGoal 不是具体剧情，而是叙事结构目标。
    例如："增加猜疑"而不是"让 Agent A 怀疑 Agent B"。
    
    具体如何实现这个目标，由角色后端的 Agent 决策系统处理。
    导演只设定方向，不控制细节。
    
    使用流程：
      DirectorService.update() → _generate_scene_goal() → 返回给 World Simulator
      World Simulator 将 SceneGoal 注入 Agent 的决策上下文
    """

    # 目标描述，会被注入到 Agent 的 prompt 作为氛围引导
    description: str

    # 这个目标预计持续多少 tick（用于 rhythm 判断是否需要切换目标）
    duration_ticks: int = 60

    # 目标优先级（高优先级的目标会覆盖低优先级）
    priority: int = 0

    # 可选：目标指向的特定角色（None 表示全局目标）
    target_agent_id: Optional[str] = None

    # 可选：目标指向的特定地点
    target_location_id: Optional[str] = None

    # 创建时间戳
    created_at: float = Field(default_factory=time.time)


# ============================================================
# 导演状态（DirectorState）
# ============================================================

class Chapter(BaseModel):
    """叙事章节 —— 导演自动划分的故事段落。"""
    id: str = ""
    number: int = 0
    title: str = ""
    summary: str = ""
    start_tick: int = 0
    end_tick: Optional[int] = None
    key_events: List[str] = Field(default_factory=list)
    tension: str = "CALM"


class DirectorState(BaseModel):
    """
    导演的完整运行时状态。
    
    这是导演模块唯一的"记忆"载体。
    所有子模块（rhythm/info/event/convergence）都读写这个对象，
    而不是各自维护独立状态，保证状态一致性。
    
    状态持久化：
      后续需要把这个对象序列化到 PostgreSQL，
      用于断线重连时的状态恢复。
      Pydantic 的 model_dump() 可以直接转成 dict 存储。
    """

    # ── 节奏控制 ──────────────────────────────────────────
    # 当前紧张度等级
    current_tension: TensionLevel = TensionLevel.CALM

    # 目标紧张度（rhythm_controller 的目标，实际紧张度向它靠拢）
    target_tension: TensionLevel = TensionLevel.CALM

    # 上次修改紧张度的 tick（防止抖动，避免频繁切换）
    last_tension_change_tick: int = 0

    # ── 叙事收束 ──────────────────────────────────────────
    # 收束因子（0.0 = 刚开始，1.0 = 准备结局）
    # 只增不减，代表故事的整体进展
    convergence_factor: float = 0.0

    # 上次核心事件发生的 tick（用于判断是否需要强制收束）
    last_core_event_tick: int = 0

    # ── 信息控制 ──────────────────────────────────────────
    # 当前仍然隐藏的秘密 key 列表
    # 例如 ["murderer_identity", "victim_past", "secret_room"]
    hidden_secrets: List[str] = Field(default_factory=list)

    # 已曝光的秘密 key 列表（用于计算信息进展）
    revealed_secrets: List[str] = Field(default_factory=list)

    # 上次曝光秘密的 tick（控制曝光节奏，不要太频繁）
    last_revelation_tick: int = 0

    # ── 事件调度 ──────────────────────────────────────────
    # 待触发的事件队列
    scheduled_events: List[NarrativeEvent] = Field(default_factory=list)

    # 已触发的事件历史（保留最近 100 个，用于叙事上下文）
    triggered_events: List[NarrativeEvent] = Field(default_factory=list)

    # ── 场景目标 ──────────────────────────────────────────
    # 当前场景目标
    scene_goal: Optional[SceneGoal] = None

    # 当前场景目标已持续的 tick 数
    scene_goal_elapsed_ticks: int = 0

    # ── 元数据 ────────────────────────────────────────────
    # 导演启动时的 tick（用于计算相对时间）
    tick_started: int = 0

    # 最后一次 update() 执行的 tick
    last_update_tick: int = 0

    # 导演决策日志（最近 50 条，用于调试和前端展示）
    decision_log: List[Dict[str, Any]] = Field(default_factory=list)

    def log_decision(self, tick: int, decision_type: str, detail: str) -> None:
        """
        记录一条导演决策日志。
        保留最近 50 条，超出自动丢弃最旧的。
        
        Args:
            tick: 当前 tick
            decision_type: 决策类型，如 "tension_change" / "event_trigger"
            detail: 决策详情描述
        """
        entry = {
            "tick": tick,
            "type": decision_type,
            "detail": detail,
            "timestamp": time.time(),
        }
        self.decision_log.append(entry)
        # 只保留最近 50 条，避免内存无限增长
        if len(self.decision_log) > 50:
            self.decision_log = self.decision_log[-50:]

    def get_revealed_ratio(self) -> float:
        """
        计算秘密曝光比例（0.0 ~ 1.0）。
        用于 rhythm_controller 和 narrative_convergence 判断进展。
        
        Returns:
            float: 0.0 表示全部隐藏，1.0 表示全部曝光
        """
        total = len(self.hidden_secrets) + len(self.revealed_secrets)
        if total == 0:
            return 0.0
        return len(self.revealed_secrets) / total

    def record_triggered_event(self, event: NarrativeEvent) -> None:
        """
        将触发过的事件存入历史记录。
        只保留最近 100 个。
        
        Args:
            event: 已触发的事件
        """
        self.triggered_events.append(event)
        if len(self.triggered_events) > 100:
            self.triggered_events = self.triggered_events[-100:]