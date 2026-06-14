# ============================================================
# prompt/dialogue_prompts.py —— 对话生成提示模板
# ============================================================
# 用于生成角色对话文本的 prompt。
# 包含说话者设定、场景上下文、对话意图。
# ============================================================

from backend.model.agent import AgentState
from typing import List


class DialoguePromptBuilder:
    """
    对话提示构建器。
    根据角色和场景生成对话 prompt。
    """

    def build_dialogue_prompt(self, speaker: AgentState,
                              listeners: List[AgentState],
                              context: str, intent: dict) -> str:
        """构建对话生成 prompt"""
        listener_lines = []
        for listener in listeners:
            relation = "信任" if listener.id in speaker.belief.facts else "不太了解"
            listener_lines.append(f"- {listener.name}（你{relation}他们）")

        prompt = f"""你正在扮演 {speaker.name}。

## 你的设定
{speaker.personality.core_description}

## 你当前的情绪
{speaker.emotion.current_mood}（强度: {speaker.emotion.intensity:.1f}）

## 场景
{context}

## 你在和谁说话
{chr(10).join(listener_lines)}

## 你说话的目的
{intent.get('purpose', '日常对话')}

## 要传达的信息
{intent.get('message', '无特定信息')}

## 注意事项
- 你的对话要符合你的性格和当前情绪
- 不要说你知道的信息不包含的内容
- 你可以选择隐瞒、暗示或直接说出信息
- 对话要自然，像真人一样

请以 {speaker.name} 的身份说出你的对话内容：
"""
        return prompt
