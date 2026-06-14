# ============================================================
# modules/narrative/logic_validator.py —— 逻辑校验器
# ============================================================
# 校验 LLM 输出：角色一致性、信息泄露、事实矛盾、回应连贯性
# ============================================================

import logging
from typing import Dict, List, Optional, Tuple

from backend.modules.narrative.story_state import StoryState

logger = logging.getLogger(__name__)


class ValidationResult:
    def __init__(self, passed: bool, issues: List[str] = None, fixed_dialogues: List[Dict] = None):
        self.passed = passed
        self.issues = issues or []
        self.fixed_dialogues = fixed_dialogues or []

    def __bool__(self):
        return self.passed


class LogicValidator:
    """校验 LLM 生成的场景是否符合故事逻辑"""

    def __init__(self, story_state: StoryState):
        self.state = story_state

    def validate_scene(
        self,
        narration: str,
        dialogues: List[Dict],
        previous_dialogues: List[str],
        character_names: Dict[str, str],  # agent_id -> name
    ) -> ValidationResult:
        """校验整段场景，返回校验结果"""
        issues = []
        fixed = list(dialogues)

        for i, dlg in enumerate(dialogues):
            speaker = dlg.get("speaker", "")
            content = dlg.get("content", "")

            if not speaker or not content:
                continue

            # 1. 检查角色是否存在
            if speaker not in character_names.values():
                issues.append(f"对话引用了不存在的角色: {speaker}")
                continue

            # 2. 检查信息泄露
            leak = self._check_info_leak(speaker, content, character_names)
            if leak:
                issues.append(leak)

            # 3. 检查事实矛盾
            contradiction = self._check_contradiction(content)
            if contradiction:
                issues.append(contradiction)

            # 4. 检查是否在回应上文
            if i == 0 and previous_dialogues:
                coherence = self._check_coherence(content, previous_dialogues[-3:])
                if coherence:
                    issues.append(coherence)

        # 5. 检查叙事是否有推进
        if len(dialogues) >= 2:
            stagnation = self._check_stagnation(dialogues, previous_dialogues)
            if stagnation:
                issues.append(stagnation)

        passed = len(issues) == 0
        if not passed:
            logger.warning(f"[Validator] 发现 {len(issues)} 个问题: {issues}")

        return ValidationResult(passed=passed, issues=issues, fixed_dialogues=fixed)

    def _check_info_leak(self, speaker: str, content: str, character_names: Dict[str, str]) -> Optional[str]:
        """检查角色是否说了他们不应该知道的事"""
        # 找到 speaker 的 agent_id
        speaker_id = None
        for aid, name in character_names.items():
            if name == speaker:
                speaker_id = aid
                break

        if not speaker_id or speaker_id not in self.state.character_knowledge:
            return None

        knowledge = self.state.character_knowledge[speaker_id]

        # 检查是否引用了未揭露的秘密
        for secret_id, desc in self.state.all_secrets.items():
            if secret_id not in self.state.revealed_secrets:
                # 秘密尚未揭露，检查对话中是否泄露
                keywords = desc.split()[:3]  # 简单关键词匹配
                for kw in keywords:
                    if len(kw) >= 2 and kw in content:
                        if secret_id not in knowledge.revealed_secrets:
                            return f"{speaker} 泄露了未揭露的秘密: {secret_id}"

        return None

    def _check_contradiction(self, content: str) -> Optional[str]:
        """检查是否与已确立的事实矛盾"""
        for fact in self.state.established_facts:
            # 简单的否定检查
            fact_words = set(fact.replace("不", "").split())
            content_words = set(content.split())
            common = fact_words & content_words
            if len(common) >= 3:
                # 有重叠关键词，检查是否有否定词
                if "不" in fact and "不" not in content.split():
                    return f"与已确立事实矛盾: '{fact}' vs '{content[:50]}'"
                if "不" not in fact and "不" in content.split():
                    return f"与已确立事实矛盾: '{fact}' vs '{content[:50]}'"
        return None

    def _check_coherence(self, content: str, recent: List[str]) -> Optional[str]:
        """检查回应是否与上文连贯"""
        if not recent:
            return None
        # 过滤掉旁白条目，只比较角色对话之间的连贯性
        dialogue_recent = [r for r in recent if not r.startswith("旁白:")]
        if not dialogue_recent:
            return None
        # 如果内容与上一条角色对话完全无关（没有共享关键词），可能是不连贯的
        last = dialogue_recent[-1]
        last_words = set(last.replace("：", " ").split())
        content_words = set(content.split())
        overlap = last_words & content_words
        if len(overlap) == 0 and len(content) > 20:
            return f"对话可能与上文不连贯，无共享关键词: 上文'{last[:40]}' -> 回复'{content[:40]}'"
        return None

    def _check_stagnation(self, dialogues: List[Dict], previous: List[str]) -> Optional[str]:
        """检查叙事是否停滞——是否在重复同样的内容"""
        if not previous:
            return None

        current_text = " ".join(d.get("content", "") for d in dialogues)
        recent_text = " ".join(previous[-4:])

        current_words = set(current_text.split())
        recent_words = set(recent_text.split())
        overlap_ratio = len(current_words & recent_words) / max(len(current_words), 1)

        if overlap_ratio > 0.7:
            return f"叙事停滞：当前对话与上文重叠度 {overlap_ratio:.0%}"

        return None

    def generate_fix_hint(self, issues: List[str]) -> str:
        """生成修复提示，供 LLM 重新生成时参考"""
        if not issues:
            return ""
        hints = ["请在生成下一段时注意以下问题："]
        for issue in issues:
            hints.append(f"- {issue}")
        return "\n".join(hints)
