

# ============================================================
# director/narrative_convergence.py —— 叙事收束器
# ============================================================
# 防止剧情无限发散，确保故事朝着结局推进。
#
# 核心问题：开放世界叙事容易"跑偏"
#   - 玩家可能一直在探索无关支线
#   - Agent 之间的对话可能越来越偏离主要冲突
#   - 没有外力干预的话，故事可以无限拖延
#
# 收束器的解决方案：
#   - 维护 convergence_factor（0.0 ~ 1.0）表示故事进展
#   - 检测叙事是否"偏离"（太久没有核心事件发生）
#   - 偏离时触发"收束事件"，强制拉回主线
#   - convergence_factor 越高，故事离结局越近
#
# convergence_factor 增长来源：
#   1. 核心事件触发（谋杀、关键揭示等）+ 0.1 ~ 0.2
#   2. 秘密曝光 + 0.05 / 个
#   3. 强制收束触发 + 0.1
#   4. 玩家主动推进剧情 + 0.05
#
# TODO（后续迭代方向）：
#   - 接入 LLM：分析最近对话/事件，判断是否真的偏离主线
#   - 支持多条叙事线路（不同玩家行为导向不同结局）
#   - 实现"软收束"：不直接触发事件，而是引导 Agent 行为
# ============================================================

from backend.model.narrative import DirectorState, NarrativeEvent, TensionLevel
from typing import List
import uuid
import logging

logger = logging.getLogger(__name__)


# ============================================================
# 配置常量
# ============================================================

# 允许叙事"发散"的最大 tick 数
# 超过这个值还没有核心事件，触发强制收束
MAX_DIVERGENCE_TICKS = 200

# convergence_factor 达到这个值时，开始进入结局准备阶段
ENDGAME_THRESHOLD = 0.85

# 收束事件触发后 convergence_factor 的增量
CONVERGENCE_BOOST = 0.1

# 强制收束事件的最小冷却时间（避免频繁触发）
FORCED_CONVERGENCE_COOLDOWN = 50


class NarrativeConvergence:
    """
    叙事收束器。
    确保故事不会无限发散，朝着结局推进。
    """

    def __init__(self):
        # 上次强制收束的 tick（实现冷却时间）
        self._last_forced_convergence_tick: int = -FORCED_CONVERGENCE_COOLDOWN

    # ============================================================
    # 核心方法
    # ============================================================

    def evaluate_convergence(
        self,
        state: DirectorState,
        tick: int,
        recent_events: List[str],
    ) -> float:
        """
        评估当前叙事收束程度，返回更新后的 convergence_factor（0.0 ~ 1.0）。
        
        这个方法读取多种信号来判断故事进展，并相应地增加 convergence_factor。
        
        信号来源：
          1. 秘密曝光进度（最客观的指标）
          2. 最近事件列表（是否有核心剧情推进）
          3. 时间流逝（随着游戏进行，自然增长）
          
        注意：convergence_factor 只增不减。
        故事进展不会倒退（除非你在做时间循环玩法）。
        
        Args:
            state: 当前导演状态
            tick: 当前 tick
            recent_events: 最近 N 个 tick 发生的事件描述列表
            
        Returns:
            float: 新的 convergence_factor（已更新到 state 中）
            
        TODO：
          接入 LLM 分析：
          ```python
          context = f"最近发生的事件：{recent_events}\\n核心冲突：{state.core_conflict}"
          progress = await llm.analyze_narrative_progress(context)
          return min(1.0, state.convergence_factor + progress.delta)
          ```
        """
        current_factor = state.convergence_factor
        delta = 0.0

        # ── 信号 1：秘密曝光进度 ────────────────────────────
        # 已曝光秘密 / 总秘密数量，直接反映信息层面的进展
        revealed_ratio = state.get_revealed_ratio()
        # 把曝光比例映射到 convergence 贡献（最多 +0.6 来自秘密曝光）
        target_from_revelation = revealed_ratio * 0.6

        # 如果当前 factor 低于应有水平，拉一点上来
        if current_factor < target_from_revelation:
            delta += (target_from_revelation - current_factor) * 0.1

        # ── 信号 2：最近事件中是否有核心事件 ──────────────
        core_event_types = {"murder", "revelation", "confrontation", "new_arrival"}
        has_core_event = any(
            # recent_events 是字符串描述列表，检查类型关键词
            any(et in event_desc for et in core_event_types)
            for event_desc in recent_events
        )
        if has_core_event:
            delta += 0.05
            logger.debug(f"[NarrativeConvergence] 检测到核心事件，convergence +0.05")

        # ── 信号 3：时间自然流逝（非常缓慢的背景增长）──────
        # 每 100 tick 自然增长 0.01，防止游戏完全停滞
        natural_growth = (tick - state.tick_started) / 10000
        delta += min(natural_growth, 0.001)  # 每次最多 +0.001

        # ── 应用 delta，保证不超过 1.0 ──────────────────────
        new_factor = min(1.0, current_factor + delta)

        if new_factor > current_factor:
            logger.info(
                f"[NarrativeConvergence] convergence_factor: "
                f"{current_factor:.3f} → {new_factor:.3f} (delta={delta:.3f})"
            )

        state.convergence_factor = new_factor
        return new_factor

    def needs_convergence(
        self,
        state: DirectorState,
        tick: int,
        last_core_event_tick: int,
    ) -> bool:
        """
        判断是否需要启动收束机制（触发强制收束事件）。
        
        触发条件（满足任一）：
          1. 距离上次核心事件超过 MAX_DIVERGENCE_TICKS tick（叙事停滞）
          2. convergence_factor 长时间没有增长（进展卡住）
          
        同时检查冷却时间，避免频繁触发强制收束。
        
        Args:
            state: 导演状态
            tick: 当前 tick
            last_core_event_tick: 上次核心事件发生的 tick
            
        Returns:
            bool: True 表示需要触发收束
        """
        # 冷却时间检查（强制收束不能太频繁）
        if (tick - self._last_forced_convergence_tick) < FORCED_CONVERGENCE_COOLDOWN:
            return False

        # 条件 1：叙事发散时间过长
        ticks_since_core = tick - max(last_core_event_tick, state.last_core_event_tick)
        if ticks_since_core > MAX_DIVERGENCE_TICKS:
            logger.warning(
                f"[NarrativeConvergence] 叙事发散 {ticks_since_core} tick，"
                f"超过阈值 {MAX_DIVERGENCE_TICKS}，触发收束"
            )
            return True

        # 条件 2：游戏进行了很久但 factor 还很低（进展异常缓慢）
        ticks_elapsed = tick - state.tick_started
        expected_factor = ticks_elapsed / 2000  # 期望每 2000 tick 到达 factor=1.0
        if state.convergence_factor < expected_factor * 0.5 and ticks_elapsed > 300:
            logger.warning(
                f"[NarrativeConvergence] 进展过慢: factor={state.convergence_factor:.2f}, "
                f"期望 {expected_factor:.2f}，触发收束"
            )
            return True

        return False

    def generate_convergence_event(
        self,
        state: DirectorState,
        current_tick: int,
    ) -> NarrativeEvent:
        """
        生成收束事件：将叙事焦点强制拉回核心冲突。
        
        收束事件是一种"导演干预"，通过在世界中制造戏剧性变化，
        迫使所有角色重新关注主要冲突。
        
        事件强度与当前 convergence_factor 相关：
          factor < 0.3 → 轻微干预（广播提示）
          factor 0.3~0.6 → 中等干预（停电、声音）
          factor > 0.6 → 强力干预（警告、紧急事件）
          
        Args:
            state: 导演状态（convergence_factor 会被提升）
            current_tick: 当前 tick
            
        Returns:
            NarrativeEvent: 收束事件对象
        """
        # 更新冷却时间记录
        self._last_forced_convergence_tick = current_tick

        # 收束因子增量
        old_factor = state.convergence_factor
        state.convergence_factor = min(1.0, old_factor + CONVERGENCE_BOOST)
        state.last_core_event_tick = current_tick

        # 根据当前进展阶段选择收束事件的形式
        if old_factor < 0.3:
            # 早期：轻微的氛围提示，不要太突兀
            event_type = "broadcast"
            description = f"广播传来低沉的声音：'时间不多了…事情正在失控。'"
            priority = 2
        elif old_factor < 0.6:
            # 中期：更明显的压力事件
            event_type = "blackout"
            description = "整栋建筑突然停电，当灯光恢复时，所有人都感觉到——有什么东西改变了。"
            priority = 3
        else:
            # 后期：直接的强力干预，推向高潮
            event_type = "alarm"
            description = f"紧急警报响起，广播宣告：'所有人立刻前往大厅，有人知道真相。'"
            priority = 4

        event = NarrativeEvent(
            id=f"convergence_{current_tick}",
            type=event_type,
            scheduled_tick=current_tick,
            affected_locations=[],   # 全局事件，影响所有地点
            affected_agents=[],      # 影响所有 Agent
            description=description,
            is_triggered=True,       # 立即触发，不放入队列
            priority=priority,
            metadata={
                "convergence_factor_before": old_factor,
                "convergence_factor_after": state.convergence_factor,
                "forced": True,       # 标记为强制收束事件
            },
        )

        logger.info(
            f"[NarrativeConvergence] 生成收束事件: type={event_type}, "
            f"factor {old_factor:.2f} → {state.convergence_factor:.2f}"
        )

        state.log_decision(current_tick, "forced_convergence", {
            "event_type": event_type,
            "factor_before": old_factor,
            "factor_after": state.convergence_factor,
        })

        return event

    def is_approaching_endgame(self, state: DirectorState) -> bool:
        """
        判断故事是否正在进入结局阶段。
        
        当 convergence_factor 超过 ENDGAME_THRESHOLD 时，
        导演应该开始准备结局内容：
          - 停止调度新的长期事件
          - 确保所有关键秘密都被曝光
          - 开始推动角色做最终表态
          
        Args:
            state: 导演状态
            
        Returns:
            bool: True 表示正在进入结局
        """
        return state.convergence_factor >= ENDGAME_THRESHOLD

    def advance_convergence(
        self, state: DirectorState, delta: float, reason: str
    ) -> None:
        """
        手动推进收束因子（供外部模块调用）。
        
        使用场景：
          - 玩家做出了重要干预，大幅推进剧情
          - 核心事件（谋杀、揭示）发生
          - 角色完成了目标
          
        Args:
            state: 导演状态
            delta: 增量（0.0 ~ 1.0）
            reason: 增加原因（用于日志）
        """
        old_factor = state.convergence_factor
        state.convergence_factor = min(1.0, old_factor + delta)
        logger.info(
            f"[NarrativeConvergence] 外部推进 convergence: "
            f"{old_factor:.3f} → {state.convergence_factor:.3f} (原因: {reason})"
        )