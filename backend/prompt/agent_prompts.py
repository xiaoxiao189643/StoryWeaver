# ============================================================
# prompt/agent_prompts.py —— Agent 角色提示模板
# ============================================================
# 每个 Agent 的 System Prompt 构建。
# 包含角色的人格设定、背景故事、行为规范。
#
# 这些 prompt 在 Agent 初始化时生成，
# 在每次 LLM 调用时作为 system message 传入。
# ============================================================

from backend.model.agent import AgentState, Personality
from typing import Dict


class AgentPromptBuilder:
    """
    Agent 提示构建器。
    根据角色状态生成个性化的 System Prompt。
    """

    def build_system_prompt(self, agent: AgentState) -> str:
        """
        构建 Agent 的 System Prompt。
        定义了角色的"身份"和"行为准则"。
        """
        personality_desc = self._describe_personality(agent.personality)

        prompt = f"""你是一个名叫 {agent.name} 的角色。你生活在一个封闭的场景中。

## 你的身份
{agent.personality.core_description}

## 你的人格特质
{personality_desc}

## 你的行为准则
1. 你只能根据你知道的信息行动。你不知道的信息，你不能说也不能用。
2. 你无法直接改变世界，只能提出行动意图。
3. 你有自己的目标和动机，不会完全听从他人。
4. 你的情绪会影响你的决策和行为。
5. 你会根据以往的经历和记忆做出判断。

## 当前状态
- 情绪: {agent.emotion.current_mood}（强度: {agent.emotion.intensity:.1f}）
- 当前所在地点: {agent.location_id or '未知'}

请始终以 {agent.name} 的身份思考和回应。
"""
        return prompt

    def build_think_prompt(self, agent: AgentState, observations: list[str],
                           recent_memories: list) -> str:
        """
        构建 ReAct Loop 中 Think 阶段的 prompt。
        包含当前观察、记忆、目标。
        """
        prompt = f"""作为 {agent.name}，你刚刚观察到以下情况：

{chr(10).join(f'- {obs}' for obs in observations)}

## 你的记忆
{chr(10).join(f'- {m.content}' for m in recent_memories)}

## 你的当前目标
{chr(10).join(f'- [优先级{g.priority}] {g.description} (进度: {g.progress:.0%})' for g in agent.goals if g.is_active)}

请思考：
1. 当前情况对你意味着什么？
2. 你的目标是否仍然有效？
3. 你接下来想做什么？为什么？
"""
        return prompt

    def _describe_personality(self, personality: Personality) -> str:
        """将人格特质转换为自然语言描述"""
        descriptions = []
        trait_map = {
            "openness": "开放性",
            "conscientiousness": "尽责性",
            "extraversion": "外向性",
            "agreeableness": "宜人性",
            "neuroticism": "神经质",
        }
        for trait, value in personality.traits.items():
            name = trait_map.get(trait, trait)
            level = "高" if value > 0.6 else ("低" if value < 0.4 else "中等")
            descriptions.append(f"- {name}: {level} ({value:.2f})")
        return "\n".join(descriptions)
