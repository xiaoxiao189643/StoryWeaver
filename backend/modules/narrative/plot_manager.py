# ============================================================
# modules/narrative/plot_manager.py —— 剧情管理器
# ============================================================
# 管理：故事推进节奏、冲突升级、秘密揭露时机、角色调度
# ============================================================

import logging
from typing import Dict, List, Optional

from backend.modules.narrative.story_state import StoryState, StoryPhase

logger = logging.getLogger(__name__)


class PlotManager:
    """控制故事节奏和剧情走向"""

    def __init__(self, story_state: StoryState):
        self.state = story_state
        self._last_speakers: List[str] = []     # 最近发言的角色
        self._speak_counts: Dict[str, int] = {}  # 每个角色发言次数
        self._silent_warnings: Dict[str, int] = {}  # 角色沉默的 tick 数

    def get_scene_goal(self, tick: int) -> str:
        """根据当前故事阶段和状态，生成场景目标指令"""
        phase = self.state.phase

        # 检查是否需要推进阶段
        new_phase = self.state.advance_phase(tick)
        if new_phase:
            logger.info(f"[PlotManager] 故事阶段推进: {new_phase.value}")

        # 轮转调度：优先让沉默最久的角色说话
        next_speakers = self._pick_speakers()

        base = self.state.get_phase_context()

        if next_speakers:
            return f"{base} 本轮优先让 {', '.join(next_speakers)} 说话。"

        return base

    def _pick_speakers(self) -> List[str]:
        """选择本轮应该说话的角色（优先沉默最久的）"""
        candidates = sorted(
            self._speak_counts.items(),
            key=lambda x: x[1]
        )
        return [name for name, _ in candidates[:2]] if candidates else []

    def record_speaker(self, speaker_name: str):
        """记录角色发言"""
        self._speak_counts[speaker_name] = self._speak_counts.get(speaker_name, 0) + 1
        self._last_speakers.append(speaker_name)
        if len(self._last_speakers) > 10:
            self._last_speakers = self._last_speakers[-10:]

    def should_reveal_secret(self, tick: int) -> Optional[str]:
        """判断是否应该揭露秘密"""
        unrevealed = set(self.state.all_secrets.keys()) - self.state.revealed_secrets
        if not unrevealed:
            return None

        # 开场阶段不揭露秘密
        if self.state.phase == StoryPhase.OPENING:
            return None

        # 根据故事阶段决定揭露节奏
        phase_thresholds = {
            StoryPhase.INVESTIGATION: (4, 1),
            StoryPhase.CONFLICT: (3, 2),
            StoryPhase.CLIMAX: (1, 99),
        }

        threshold, max_revealed = phase_thresholds.get(self.state.phase, (5, 1))
        if threshold <= 0:
            return None

        if self.state.phase_ticks % threshold == 0 and len(self.state.revealed_secrets) < max_revealed:
            return list(unrevealed)[0]

        return None

    def add_pending_question(self, question: str):
        """添加待解答的悬念"""
        if question not in self.state.pending_questions:
            self.state.pending_questions.append(question)

    def resolve_question(self, question_pattern: str):
        """标记某个悬念已解答"""
        self.state.pending_questions = [
            q for q in self.state.pending_questions
            if question_pattern not in q
        ]

    def ensure_all_speaking(self) -> str:
        """检查是否有人长时间没发言，返回调度提示"""
        warnings = []
        for name, count in self._speak_counts.items():
            if count == 0:
                warnings.append(f"{name} 尚未发言，请让他/她说点什么。")
        return " ".join(warnings) if warnings else ""

    def get_director_hint(self, tick: int) -> str:
        """综合调度提示"""
        hints = []

        # 轮转提示
        rotation = self.ensure_all_speaking()
        if rotation:
            hints.append(rotation)

        # 阶段提示
        hints.append(self.state.get_phase_context())

        # 秘密提示
        to_reveal = self.should_reveal_secret(tick)
        if to_reveal and to_reveal in self.state.all_secrets:
            hints.append(f"可以考虑引出秘密线索: {self.state.all_secrets[to_reveal]}")

        # 悬念提示
        if self.state.pending_questions:
            hints.append(f"当前未解悬念: {self.state.pending_questions[-1][:50]}")

        return " | ".join(hints) if hints else "自然推进剧情"
