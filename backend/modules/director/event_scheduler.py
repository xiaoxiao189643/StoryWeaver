

# ============================================================
# director/event_scheduler.py —— 事件调度器
# ============================================================
# 负责调度叙事事件（Narrative Event）。
#
# 两类事件：
#   预定事件（Scheduled）：提前安排好时间触发（如剧情关键节点）
#   自发事件（Spontaneous）：根据当前叙事状态即时生成
#
# 事件执行流程：
#   1. 外部调用 schedule_event() 把事件放入 state.scheduled_events 队列
#   2. 每个 tick，DirectorService 调用 get_due_events() 取出到期事件
#   3. DirectorService 调用 _trigger_event() 执行事件
#   4. 执行后事件进入 state.triggered_events 历史
#
# TODO（后续迭代方向）：
#   - generate_spontaneous_event 接入 LLM，让导演根据故事上下文生成事件
#   - 支持事件优先级队列（高优先级事件可以插队）
#   - 支持事件依赖（事件 B 必须在事件 A 触发后才能触发）
#   - 支持条件触发（满足某个世界状态条件才触发）
# ============================================================

from backend.model.narrative import NarrativeEvent, DirectorState, TensionLevel
from backend.utils.i18n import cn_event_type
from typing import List, Optional, Dict, Any
import uuid
import logging

logger = logging.getLogger(__name__)


# ============================================================
# 事件模板库
# ============================================================
# 每种紧张度对应的自发事件模板列表。
# 列表中有多个选项，避免每次都触发相同事件。
#
# 数据结构说明：
#   type            → 事件类型（对应 WorldSimulator 的处理逻辑）
#   description     → 事件描述（用于前端展示和 LLM 上下文）
#   priority        → 优先级（同 tick 多事件时决定顺序）
#   metadata        → 事件特有数据（WorldSimulator 读取后执行具体逻辑）
#
# 注意：这里只是"建议"，最终是否触发还要看 should_generate_spontaneous()
SPONTANEOUS_EVENT_TEMPLATES: Dict[TensionLevel, List[Dict[str, Any]]] = {
    TensionLevel.CALM: [
        {
            "type": "broadcast",
            "description": "广播通知：管家提醒晚餐即将开始，请各位前往餐厅",
            "priority": 1,
            "metadata": {"message": "晚餐即将开始，请各位前往餐厅"},
        },
        {
            "type": "weather_change",
            "description": "窗外天空开始乌云密布，远处传来雷声",
            "priority": 1,
            "metadata": {"weather": "stormy", "transition": "gradual"},
        },
        {
            "type": "ambient",
            "description": "老旧的留声机自动播放起了一首忧郁的曲子",
            "priority": 0,
            "metadata": {},
        },
    ],
    TensionLevel.TENSE: [
        {
            "type": "blackout",
            "description": "突然停电，整栋建筑陷入黑暗，有人惊叫了一声",
            "priority": 2,
            "metadata": {"duration_ticks": 10, "affected_area": "all"},
        },
        {
            "type": "strange_sound",
            "description": "二楼传来沉重的脚步声，然后是什么东西被打翻的声音",
            "priority": 2,
            "metadata": {"location": "floor_2", "sound_type": "thud"},
        },
        {
            "type": "broadcast",
            "description": "广播突然发出刺耳的杂音，然后传出一段含糊不清的警告",
            "priority": 2,
            "metadata": {"message": "警告：有人正在撒谎…", "corrupted": True},
        },
    ],
    TensionLevel.CRISIS: [
        {
            "type": "alarm",
            "description": "警报声突然大作，红色警示灯开始闪烁",
            "priority": 3,
            "metadata": {"alarm_type": "emergency", "light_color": "red"},
        },
        {
            "type": "confrontation",
            "description": "两名角色的争执突然升级，推搡声从走廊传来",
            "priority": 3,
            "metadata": {"location": "hallway", "intensity": "high"},
        },
        {
            "type": "discovery",
            "description": "有人发现了一件关键物证，气氛瞬间凝固",
            "priority": 3,
            "metadata": {"evidence_type": "physical", "location": "study"},
        },
    ],
    TensionLevel.RESOLUTION: [
        {
            "type": "new_arrival",
            "description": "大门被敲响——外面站着两名警察，要求所有人集合到大厅",
            "priority": 4,
            "metadata": {"arrival_type": "police", "count": 2},
        },
        {
            "type": "revelation",
            "description": "一封被藏匿的信件从书架后滑落，信封上写着关键人物的名字",
            "priority": 4,
            "metadata": {"clue_type": "letter", "target": "key_character"},
        },
    ],
}

# 自发事件生成的冷却时间（tick 数），防止事件刷新过快
SPONTANEOUS_EVENT_COOLDOWN = 40


class EventScheduler:
    """
    叙事事件调度器。
    在合适的时机触发预定或自发的叙事事件。
    """

    def __init__(self):
        # 记录上次生成自发事件的 tick（实现冷却时间）
        self._last_spontaneous_tick: int = -SPONTANEOUS_EVENT_COOLDOWN

        # 记录每种紧张度下已使用的模板索引，实现轮换避免重复
        # { TensionLevel: 上次使用的模板 index }
        self._template_rotation: Dict[TensionLevel, int] = {}

    # ============================================================
    # 预定事件管理
    # ============================================================

    def schedule_event(
        self,
        state: DirectorState,
        event_type: str,
        tick: int,
        affected_locations: List[str],
        affected_agents: List[str],
        description: str = "",
        priority: int = 0,
        metadata: Dict[str, Any] = None,
    ) -> NarrativeEvent:
        """
        调度一个在指定 tick 触发的预定事件，并加入等待队列。
        
        使用场景：
          - 剧情设计时预埋的关键事件（如第 100 tick 必须发生谋杀）
          - NarrativeConvergence 触发的收束事件
          - 玩家干预导致的连锁事件
          
        Args:
            state: 导演状态（事件会被加入 state.scheduled_events）
            event_type: 事件类型字符串
            tick: 计划触发的 tick
            affected_locations: 影响的地点 ID 列表
            affected_agents: 影响的角色 ID 列表
            description: 事件描述
            priority: 优先级（同 tick 多事件时用于排序）
            metadata: 事件特有数据
            
        Returns:
            NarrativeEvent: 创建好的事件对象（已加入队列）
        """
        event = NarrativeEvent(
            id=str(uuid.uuid4()),
            type=event_type,
            scheduled_tick=tick,
            affected_locations=affected_locations,
            affected_agents=affected_agents,
            description=description,
            priority=priority,
            metadata=metadata or {},
        )

        # 加入待触发队列
        state.scheduled_events.append(event)

        # 按 priority 降序 + scheduled_tick 升序排列，方便后续取出
        state.scheduled_events.sort(key=lambda e: (-e.priority, e.scheduled_tick))

        logger.info(
            f"[EventScheduler] 调度事件: type={event_type}, "
            f"tick={tick}, priority={priority}, desc={description}"
        )

        return event

    def get_due_events(self, state: DirectorState, current_tick: int) -> List[NarrativeEvent]:
        """
        取出所有在当前 tick 到期的事件，并从队列中移除。
        
        这个方法会修改 state.scheduled_events，
        将到期的事件标记为 is_triggered=True 并移出队列。
        
        注意：
          - 同 tick 多个到期事件按 priority 从高到低排列返回
          - 已经 is_triggered=True 的事件会被直接丢弃（防止重复）
          
        Args:
            state: 导演状态
            current_tick: 当前 tick 数
            
        Returns:
            List[NarrativeEvent]: 本 tick 应该触发的事件列表（已排序）
        """
        due_events = []
        remaining_events = []

        for event in state.scheduled_events:
            if event.scheduled_tick <= current_tick and not event.is_triggered:
                # 标记为已触发（防止后续重复处理）
                event.is_triggered = True
                due_events.append(event)
                logger.info(
                    f"[EventScheduler] 事件到期: type={event.type}, "
                    f"id={event.id[:8]}, desc={event.description}"
                )
            else:
                # 未到期或已触发过的保留在队列
                remaining_events.append(event)

        # 更新队列
        state.scheduled_events = remaining_events

        # 按优先级降序排列，高优先级事件先执行
        due_events.sort(key=lambda e: -e.priority)

        return due_events

    # ============================================================
    # 自发事件生成
    # ============================================================

    def generate_spontaneous_event(
        self, state: DirectorState, current_tick: int
    ) -> Optional[NarrativeEvent]:
        """
        根据当前叙事状态，判断是否需要生成自发事件，并返回事件对象。
        
        自发事件是导演的"即兴创作"——当故事需要推进但没有预定事件时，
        导演会根据当前紧张度自主生成合适的事件。
        
        决策流程：
          1. 检查冷却时间（避免事件刷太快）
          2. 检查 RhythmController 的信号（应该加速？）
          3. 从当前紧张度对应的模板库中选取事件
          4. 返回事件对象（但不加入队列，由调用方决定是否触发）
          
        Args:
            state: 当前导演状态
            current_tick: 当前 tick
            
        Returns:
            Optional[NarrativeEvent]: 生成的事件，如果不需要生成则返回 None
            
        TODO：
          将模板选取替换为 LLM 调用：
          ```python
          prompt = build_director_prompt(state, current_tick)
          response = await llm.generate(prompt)
          event = parse_event_from_response(response)
          ```
        """
        # ── 步骤 1：冷却时间检查 ────────────────────────────
        # 距离上次自发事件不足冷却时间，不生成
        if (current_tick - self._last_spontaneous_tick) < SPONTANEOUS_EVENT_COOLDOWN:
            return None

        # ── 步骤 2：判断是否真的需要自发事件 ──────────────
        # 如果队列里已经有足够多的待触发事件，不需要额外生成
        pending_count = len(state.scheduled_events)
        if pending_count >= 2:
            # 已有 2 个以上待触发事件，不需要再生成
            return None

        # ── 步骤 3：从模板库中选取事件 ────────────────────
        # 根据当前紧张度选择对应的模板列表
        tension = state.current_tension
        templates = SPONTANEOUS_EVENT_TEMPLATES.get(tension, [])

        if not templates:
            logger.warning(f"[EventScheduler] 紧张度 {tension} 没有对应的事件模板")
            return None

        # 轮换选取模板，避免重复
        last_index = self._template_rotation.get(tension, -1)
        next_index = (last_index + 1) % len(templates)
        self._template_rotation[tension] = next_index
        template = templates[next_index]

        # ── 步骤 4：构造事件对象 ────────────────────────────
        event = NarrativeEvent(
            id=str(uuid.uuid4()),
            type=template["type"],
            scheduled_tick=current_tick,  # 自发事件立即触发
            affected_locations=[],
            affected_agents=[],
            description=template["description"],
            priority=template.get("priority", 1),
            metadata=template.get("metadata", {}),
        )

        # 更新冷却时间记录
        self._last_spontaneous_tick = current_tick

        logger.info(
            f"[EventScheduler] 生成自发事件: type={event.type}, "
            f"tension={tension.label()}, desc={event.description}"
        )

        return event

    def cancel_event(self, state: DirectorState, event_id: str) -> bool:
        """
        取消一个尚未触发的预定事件。
        
        使用场景：
          - 玩家的干预导致原定事件不再需要
          - 叙事发生了意外分支，原计划的事件已不合适
          
        Args:
            state: 导演状态
            event_id: 要取消的事件 ID
            
        Returns:
            bool: True 表示成功取消，False 表示未找到
        """
        original_count = len(state.scheduled_events)
        state.scheduled_events = [
            e for e in state.scheduled_events if e.id != event_id
        ]
        cancelled = len(state.scheduled_events) < original_count

        if cancelled:
            logger.info(f"[EventScheduler] 取消事件: id={event_id[:8]}")
        else:
            logger.warning(f"[EventScheduler] 未找到要取消的事件: id={event_id[:8]}")

        return cancelled

    def get_upcoming_events_summary(self, state: DirectorState) -> List[Dict[str, Any]]:
        """
        获取即将触发的事件摘要，用于 REST API 返回给前端。
        
        对应接口文档中的：
          GET /director/upcoming_events
          返回：[{ type, description, triggerTime, probability }]
          
        Args:
            state: 导演状态
            
        Returns:
            List[dict]: 前端可读的事件摘要列表
        """
        return [
            {
                "type": cn_event_type(event.type),
                "typeKey": event.type,
                "description": event.description,
                "triggerTime": event.scheduled_tick,
                # 预定事件概率为 1.0，自发事件概率在生成时设置
                "probability": event.metadata.get("probability", 1.0),
            }
            for event in state.scheduled_events
            if not event.is_triggered
        ]