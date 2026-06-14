# ============================================================
# director/rhythm_controller.py —— 节奏控制器
# ============================================================
# 负责控制叙事节奏（紧张度曲线）。
#
# 核心职责：
#   - 根据故事进展、玩家活跃度、时间流逝，计算当前紧张度
#   - 防止紧张度"抖动"（短时间内频繁切换）
#   - 实现三幕式叙事结构的节奏曲线
#   - 记录紧张度历史，供调试和前端可视化使用
#
# 三幕结构（基于 convergence_factor）：
#   第一幕（0.0 ~ 0.3）→ CALM，建立背景和角色
#   第二幕（0.3 ~ 0.7）→ TENSE，冲突升级
#   第三幕（0.7 ~ 1.0）→ CRISIS / RESOLUTION，高潮和收束
#
# TODO（后续迭代方向）：
#   - 接入 LLM，让导演根据对话内容动态判断紧张度
#   - 支持自定义叙事结构（五幕式、非线性等）
#   - 加入"呼吸感"：高紧张后自动给玩家短暂喘息空间
# ============================================================

from backend.model.narrative import TensionLevel, DirectorState
import logging

logger = logging.getLogger(__name__)


class RhythmController:
    """
    叙事节奏控制器。
    像 DJ 一样控制故事的"节奏感"，让紧张度有高有低、张弛有度。
    """

    # ── 配置常量 ─────────────────────────────────────────────
    # 紧张度切换的最小间隔（tick 数），防止抖动
    # 例如设为 30，表示两次紧张度切换之间至少间隔 30 tick
    MIN_TENSION_CHANGE_INTERVAL = 30

    # 玩家不活跃多少 tick 后，开始推高紧张度
    PLAYER_INACTIVE_THRESHOLD = 20

    # 紧张度保持在 CRISIS 的最大 tick 数，超过则强制切换到 RESOLUTION
    MAX_CRISIS_DURATION = 100

    def __init__(self):
        # 紧张度数值历史（存浮点数，方便后续绘制曲线）
        self._tension_history: list[float] = []

        # 玩家上次活跃的 tick（用于判断玩家是否长时间不活跃）
        self._last_player_active_tick: int = 0

        # 当前 CRISIS 状态已持续的 tick 数（防止 CRISIS 太长）
        self._crisis_duration: int = 0

    # ============================================================
    # 核心方法：评估并返回新的紧张度
    # ============================================================

    def evaluate_tension(self, state: DirectorState, tick: int,
                         player_active: bool) -> TensionLevel:
        """
        评估并更新当前紧张度，返回新的 TensionLevel。
        
        这是节奏控制器最核心的方法，每个 tick 由 DirectorService 调用一次。
        
        决策逻辑（按优先级从高到低）：
          1. 防抖检查：距离上次切换太近，不切换
          2. CRISIS 持续时间检查：太久了强制转 RESOLUTION
          3. 三幕结构基础紧张度：由 convergence_factor 决定
          4. 玩家不活跃修正：玩家太久没动，稍微提高紧张度
          5. 秘密曝光进度修正：曝光得越多，紧张度越高
        
        Args:
            state: 当前导演状态（读取 convergence_factor、revealed_secrets 等）
            tick: 当前 tick 数
            player_active: 本 tick 玩家是否有操作
            
        Returns:
            TensionLevel: 新的紧张度等级
        """
        # 更新玩家活跃记录
        if player_active:
            self._last_player_active_tick = tick

        # ── 步骤 1：防抖检查 ────────────────────────────────
        # 如果距离上次紧张度切换不足 MIN_TENSION_CHANGE_INTERVAL tick，
        # 直接返回当前紧张度，不做任何改变。
        # 这防止了紧张度在 TENSE/CALM 之间快速抖动，影响体验。
        ticks_since_change = tick - state.last_tension_change_tick
        if ticks_since_change < self.MIN_TENSION_CHANGE_INTERVAL:
            self._record_history(state.current_tension)
            return state.current_tension

        # ── 步骤 2：CRISIS 持续时间检查 ────────────────────
        # 如果当前已经是 CRISIS，且持续太久了，
        # 强制推进到 RESOLUTION（给玩家一个结局信号）
        if state.current_tension == TensionLevel.CRISIS:
            self._crisis_duration += 1
            if self._crisis_duration >= self.MAX_CRISIS_DURATION:
                logger.info(f"[RhythmController] CRISIS 持续 {self._crisis_duration} tick，强制推进到 RESOLUTION")
                self._crisis_duration = 0
                return self._apply_tension_change(state, tick, TensionLevel.RESOLUTION, "crisis_timeout")
        else:
            # 不在 CRISIS 时重置计数
            self._crisis_duration = 0

        # ── 步骤 3：三幕结构基础紧张度 ─────────────────────
        # 根据 convergence_factor（0.0 ~ 1.0）决定基础紧张度阶段
        # convergence_factor 代表故事整体进展，由 NarrativeConvergence 维护
        base_tension = self._get_base_tension_from_convergence(state.convergence_factor)

        # ── 步骤 4：玩家不活跃修正 ──────────────────────────
        # 如果玩家超过阈值没有任何操作，轻微提高紧张度
        # 目的：推动玩家参与，让"不作为"本身有叙事代价
        player_inactive_ticks = tick - self._last_player_active_tick
        if player_inactive_ticks > self.PLAYER_INACTIVE_THRESHOLD:
            base_tension = self._raise_tension_by_one(base_tension)
            logger.debug(f"[RhythmController] 玩家不活跃 {player_inactive_ticks} tick，紧张度上调")

        # ── 步骤 5：秘密曝光进度修正 ────────────────────────
        # 已曝光的秘密越多，说明剧情进展越快，紧张度应该更高
        revealed_ratio = state.get_revealed_ratio()
        if revealed_ratio > 0.5 and base_tension == TensionLevel.CALM:
            # 超过一半的秘密已曝光，但紧张度还在 CALM，强制抬高
            base_tension = TensionLevel.TENSE
            logger.debug(f"[RhythmController] 秘密曝光率 {revealed_ratio:.0%}，强制抬高到 TENSE")

        # ── 最终决策 ────────────────────────────────────────
        # 如果计算出的紧张度和当前不同，执行切换
        if base_tension != state.current_tension:
            return self._apply_tension_change(state, tick, base_tension, "rhythm_evaluation")

        # 没有变化，记录历史后返回当前值
        self._record_history(state.current_tension)
        return state.current_tension

    # ============================================================
    # 辅助判断方法
    # ============================================================

    def should_accelerate(self, state: DirectorState, tick: int) -> bool:
        """
        判断是否应该加快节奏（推进剧情）。
        
        触发条件：
          - 玩家长时间没有进展（不活跃超过 2 倍阈值）
          - 叙事已经停滞（scheduled_events 为空且紧张度低）
          - 收束因子长时间没有增长
          
        返回 True 时，EventScheduler 可以安排新的自发事件来推动剧情。
        
        Args:
            state: 当前导演状态
            tick: 当前 tick
            
        Returns:
            bool: True 表示需要加速
        """
        # 条件 1：玩家超长时间不活跃
        player_inactive_too_long = (
            (tick - self._last_player_active_tick) > self.PLAYER_INACTIVE_THRESHOLD * 2
        )

        # 条件 2：事件队列空，且紧张度处于低位
        no_upcoming_events = len(state.scheduled_events) == 0
        low_tension = state.current_tension <= TensionLevel.CALM

        # 条件 3：收束因子过低（故事推进太慢）
        # 例如超过 200 tick 还没有任何进展（convergence_factor < 0.1）
        stagnant = state.convergence_factor < 0.1 and (tick - state.tick_started) > 200

        return player_inactive_too_long or (no_upcoming_events and low_tension) or stagnant

    def should_decelerate(self, state: DirectorState, tick: int) -> bool:
        """
        判断是否应该放慢节奏（给玩家喘息空间）。
        
        触发条件：
          - 紧张度已在 CRISIS 状态超过一段时间
          - 短时间内发生了太多事件（玩家信息过载）
          
        返回 True 时，EventScheduler 应该暂停调度新事件。
        
        Args:
            state: 当前导演状态
            tick: 当前 tick
            
        Returns:
            bool: True 表示需要减速
        """
        # 条件 1：CRISIS 持续时间超过一半阈值（还没到强制 RESOLUTION 但需要喘息）
        crisis_too_long = (
            state.current_tension == TensionLevel.CRISIS
            and self._crisis_duration > self.MAX_CRISIS_DURATION // 2
        )

        # 条件 2：最近 20 tick 内已触发超过 3 个事件（事件密度过高）
        recent_events = [
            e for e in state.triggered_events
            if (tick - e.scheduled_tick) <= 20
        ]
        event_overload = len(recent_events) >= 3

        return crisis_too_long or event_overload

    def get_tension_curve(self) -> list[float]:
        """
        获取紧张度历史曲线（浮点数列表）。
        
        用途：
          - 调试：观察紧张度变化是否符合预期
          - 前端可视化：绘制紧张度折线图
          - TODO：后续可以用这条曲线训练/调优导演决策
          
        Returns:
            list[float]: 每个 tick 的紧张度数值（0.0 ~ 3.0）
        """
        return self._tension_history.copy()

    # ============================================================
    # 私有辅助方法
    # ============================================================

    def _get_base_tension_from_convergence(self, convergence_factor: float) -> TensionLevel:
        """
        根据叙事收束因子（0.0 ~ 1.0）计算基础紧张度。
        
        实现三幕式叙事结构：
          0.0 ~ 0.3 → CALM（第一幕：建立）
          0.3 ~ 0.6 → TENSE（第二幕前半：对抗上升）
          0.6 ~ 0.85 → CRISIS（第二幕后半：高潮危机）
          0.85 ~ 1.0 → RESOLUTION（第三幕：收束解决）
          
        Args:
            convergence_factor: 收束因子，由 NarrativeConvergence 维护
            
        Returns:
            TensionLevel: 对应的基础紧张度
        """
        if convergence_factor < 0.3:
            return TensionLevel.CALM
        elif convergence_factor < 0.6:
            return TensionLevel.TENSE
        elif convergence_factor < 0.85:
            return TensionLevel.CRISIS
        else:
            return TensionLevel.RESOLUTION

    def _raise_tension_by_one(self, tension: TensionLevel) -> TensionLevel:
        """
        将紧张度提升一级，但不超过 CRISIS（RESOLUTION 是特殊状态，不通过这里进入）。
        
        Args:
            tension: 当前紧张度
            
        Returns:
            TensionLevel: 提升后的紧张度（最高到 CRISIS）
        """
        if tension == TensionLevel.CALM:
            return TensionLevel.TENSE
        elif tension == TensionLevel.TENSE:
            return TensionLevel.CRISIS
        else:
            # CRISIS 和 RESOLUTION 不再提升
            return tension

    def _apply_tension_change(self, state: DirectorState, tick: int,
                              new_tension: TensionLevel, reason: str) -> TensionLevel:
        """
        执行紧张度切换，更新 state 并记录日志。
        
        所有紧张度切换都应该通过这个方法，保证：
          1. last_tension_change_tick 始终被更新（防抖机制依赖它）
          2. 切换行为被记录到 decision_log
          
        Args:
            state: 导演状态（会被修改）
            tick: 当前 tick
            new_tension: 目标紧张度
            reason: 切换原因（用于日志）
            
        Returns:
            TensionLevel: 新的紧张度
        """
        old_tension = state.current_tension
        state.last_tension_change_tick = tick

        logger.info(
            f"[RhythmController] tick={tick} 紧张度切换: "
            f"{old_tension.label()} → {new_tension.label()} (原因: {reason})"
        )

        state.log_decision(tick, "tension_change", {
            "from": old_tension.label(),
            "to": new_tension.label(),
            "reason": reason,
        })

        self._record_history(new_tension)
        return new_tension

    def _record_history(self, tension: TensionLevel) -> None:
        """
        记录当前紧张度到历史列表。
        只保留最近 500 条，防止内存无限增长。
        
        Args:
            tension: 当前紧张度
        """
        self._tension_history.append(float(tension))
        if len(self._tension_history) > 500:
            # 丢弃最旧的数据
            self._tension_history = self._tension_history[-500:]