# ============================================================
# prompt/director_prompts.py —— 导演提示模板
# ============================================================
# Narrative Director 的 System Prompt。
# 导演不是"写剧情"的，而是"控制叙事结构"的。
#
# 导演的思考方式：
#   - 节奏是否合适？
#   - 秘密是否曝光太多/太少？
#   - 是否需要引入新事件？
#   - 故事是否在收束？
# ============================================================

from backend.model.narrative import DirectorState, TensionLevel
from typing import List


class DirectorPromptBuilder:
    """
    导演提示构建器。
    生成导演 Agent 用于决策的 prompt。
    """

    def build_system_prompt(self) -> str:
        """导演的系统提示"""
        return """你是一个叙事导演（Narrative Director）。
你的职责不是写具体剧情，而是控制叙事结构。

## 你的核心职责
1. 节奏控制：调节故事的紧张感曲线
2. 信息控制：决定秘密何时曝光
3. 事件调度：在合适时机触发叙事事件
4. 叙事收束：防止剧情无限发散

## 原则
- 你输出的是叙事目标（Scene Goal），不是具体台词
- 角色的具体行为由角色 Agent 自主完成
- 你通过调整世界参数来影响故事走向
- 好的叙事需要张弛有度
"""

    def build_direct_decision_prompt(self, state: DirectorState,
                                     world_summary: str,
                                     recent_events: List[str]) -> str:
        """导演决策 prompt"""
        prompt = f"""当前叙事状态：

## 紧张度
{state.current_tension.value}

## 世界概况
{world_summary}

## 最近发生的事件
{chr(10).join(f'- {e}' for e in recent_events)}

## 未曝光的秘密
{', '.join(state.hidden_secrets) if state.hidden_secrets else '暂无'}

## 已调度事件
{chr(10).join(f'- [{e.type}] 在 tick {e.scheduled_tick} 触发' for e in state.scheduled_events if not e.is_triggered)}

请决定：
1. 当前节奏是否需要调整？
2. 是否有秘密应该曝光？
3. 是否需要调度新的事件？
4. 故事是否需要收束？
"""
        return prompt
