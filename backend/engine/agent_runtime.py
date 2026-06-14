# ============================================================
# core/agent/agent_runtime.py —— Agent 自主行动运行时
# ============================================================
# 负责驱动每个 Agent 在每个 tick 产出 Intent。
#
# 工作流程：
#   1. 从 GroundTruth 获取 Agent 当前位置、周围环境
#   2. 从 DirectorState 获取当前 SceneGoal（叙事引导）
#   3. 调用 LLM 决策：Agent 应该做什么？
#   4. 输出结构化 Intent，交给 IntentResolver 处理
#
# LLM 决策输入（system prompt 素材）：
#   - Agent 的人格、目标、情绪、记忆摘要
#   - 当前位置和周围的人/物
#   - 导演的 SceneGoal（叙事氛围引导）
#   - 最近几条对话/事件历史
#
# 输出的 Intent 结构：
#   {
#     "type": "move" | "speak" | "interact" | "investigate" | "idle",
#     "actor": agent_id,
#     "target": location_id 或 agent_id 或 item_id,
#     "action": 动作描述（自然语言，给 LLM 参考）,
#     "dialogue": 对话内容（type=speak 时）,
#     "metadata": {}
#   }
# ============================================================

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Any

from backend.model.agent import AgentState
from backend.model.narrative import SceneGoal, TensionLevel
from backend.model.world import WorldTruth, Location

logger = logging.getLogger(__name__)

# LLM 可选的 Intent 类型（给 prompt 用）
INTENT_TYPES = ["move", "speak", "interact", "investigate", "idle"]


class AgentRuntime:
    """
    Agent 自主行动运行时。
    每个 tick，为所有活跃 Agent 产出 Intent。
    """

    def __init__(self, agents: Dict[str, AgentState]):
        """
        Args:
            agents: agent_id → AgentState 字典，所有需要驱动的 Agent
        """
        self._agents = agents

    # ============================================================
    # 主入口：为所有 Agent 产出 Intent
    # ============================================================

    async def generate_all_intents(
        self,
        world_truth: WorldTruth,
        scene_goal: Optional[SceneGoal],
        current_tick: int,
        recent_events: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        为所有 Agent 并发生成 Intent。

        Args:
            world_truth: 当前世界客观状态
            scene_goal: 导演当前场景目标
            current_tick: 当前 tick
            recent_events: 最近发生的事件描述列表

        Returns:
            List[Dict]: Intent 列表，直接传给 WorldSimulator.tick()
        """
        import asyncio

        tasks = []
        for agent in self._agents.values():
            if agent.is_controlled:
                continue
            tasks.append(
                (
                    agent,
                    self._generate_intent_for_agent(
                        agent, world_truth, scene_goal, current_tick, recent_events or []
                    ),
                )
            )

        agents = [agent for agent, _ in tasks]
        results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

        intents = []
        for agent, result in zip(agents, results):
            if isinstance(result, Exception):
                logger.warning(f"[AgentRuntime] Agent {agent.id} 决策失败: {result}")
                intents.append(self._generic_fallback_intent(agent.id, note="agent_exception"))
            elif result is not None:
                intents.append(result)

        return intents

    # ============================================================
    # 单个 Agent 的决策
    # ============================================================

    async def _generate_intent_for_agent(
        self,
        agent: AgentState,
        world_truth: WorldTruth,
        scene_goal: Optional[SceneGoal],
        current_tick: int,
        recent_events: List[str],
    ) -> Dict[str, Any]:
        """
        为单个 Agent 调用 LLM 生成 Intent。
        """
        # 构造 LLM 输入上下文
        context = self._build_context(agent, world_truth, scene_goal, current_tick, recent_events)

        # 调用 LLM
        intent_raw = await self._call_llm(agent, context)

        # 解析并校验 LLM 输出
        intent = self._parse_intent(agent.id, intent_raw)

        logger.debug(f"[AgentRuntime] {agent.name} 产出 intent: {intent}")
        return intent

    # ============================================================
    # 上下文构造
    # ============================================================

    def _build_context(
        self,
        agent: AgentState,
        world_truth: WorldTruth,
        scene_goal: Optional[SceneGoal],
        current_tick: int,
        recent_events: List[str],
    ) -> str:
        """
        构造 LLM 决策的上下文字符串。
        包含：当前位置环境、附近的人/物、导演目标、Agent 状态摘要。
        """
        # ── 当前位置信息 ──
        location = world_truth.locations.get(agent.location_id or "")
        location_desc = (
            f"{location.name}（{location.description}）"
            if location else "未知地点"
        )

        # ── 附近的其他 Agent ──
        nearby_agents = [
            other.name
            for other in self._agents.values()
            if other.id != agent.id and other.location_id == agent.location_id
        ]
        nearby_desc = "、".join(nearby_agents) if nearby_agents else "无人"

        # ── 附近的物品 ──
        nearby_items = [
            item.name
            for item in world_truth.items.values()
            if item.location_id == agent.location_id
        ]
        items_desc = "、".join(nearby_items) if nearby_items else "无物品"

        # ── 可前往的地点 ──
        accessible_locations = [
            f"{loc.id}（{loc.name}）"
            for loc in world_truth.locations.values()
            if not loc.locked and loc.id != agent.location_id
        ]
        locations_desc = "、".join(accessible_locations) if accessible_locations else "无"

        # ── 导演场景目标 ──
        goal_desc = scene_goal.description if scene_goal else "自然推进"

        # ── Agent 自身状态摘要 ──
        active_goals = [g.description for g in agent.goals if g.is_active][:3]
        goals_desc = "；".join(active_goals) if active_goals else "暂无明确目标"

        # ── 最近事件 ──
        events_desc = "\n".join(f"  - {e}" for e in recent_events[-5:]) if recent_events else "  （无）"

        context = f"""
=== 当前状态（Tick {current_tick}）===

【我是谁】
姓名：{agent.name}
当前情绪：{agent.emotion.current_mood}（强度 {agent.emotion.intensity:.1f}）
当前行为：{agent.current_action}
我的目标：{goals_desc}

【我在哪里】
位置：{location_desc}
附近的人：{nearby_desc}
附近的物品：{items_desc}
可前往的地点：{locations_desc}

【最近发生的事】
{events_desc}

【叙事氛围引导（导演指令，不可对外透露）】
{goal_desc}
""".strip()

        return context

    # ============================================================
    # LLM 调用（修改后）
    # ============================================================

    def _fallback_intent(self, agent: AgentState, context: str, note: str = "fallback") -> str:
        lower_context = context.lower()
        lines = [line.strip() for line in context.splitlines()]
        nearby_line = next((line for line in lines if line.startswith("附近的人：")), "")
        nearby_names = nearby_line.replace("附近的人：", "").strip()
        item_line = next((line for line in lines if line.startswith("附近的物品：")), "")
        item_names = item_line.replace("附近的物品：", "").strip()

        if "detective" in agent.id or "林" in agent.name:
            target = item_names.split("、")[0] if item_names and item_names != "无物品" else "周围环境"
            data = {
                "type": "investigate",
                "target": target,
                "action": f"{agent.name}正在检查{target}",
                "dialogue": None,
            }
        elif "butler" in agent.id or "陈" in agent.name:
            data = {
                "type": "speak",
                "target": nearby_names.split("、")[0] if nearby_names and nearby_names != "无人" else "all",
                "action": "提醒众人保持冷静",
                "dialogue": "请各位不要惊慌，别墅里一定还有合理的解释。",
            }
        elif "hostess" in agent.id or "苏" in agent.name:
            data = {
                "type": "speak",
                "target": nearby_names.split("、")[0] if nearby_names and nearby_names != "无人" else "all",
                "action": "试图掌控局面",
                "dialogue": "今晚的事比你们想得更复杂，但现在还不是揭开一切的时候。",
            }
        elif "guest" in agent.id or "马克" in agent.name:
            target = "神秘信件" if "信" in context or "letter" in lower_context else "阴影处"
            data = {
                "type": "investigate",
                "target": target,
                "action": f"{agent.name}暗中观察{target}",
                "dialogue": None,
            }
        else:
            data = {
                "type": "speak",
                "target": "all",
                "action": "低声回应局势",
                "dialogue": f"{agent.name}注意到了新的异常，决定继续观察。",
            }

        data["metadata"] = {"source": note}
        return json.dumps(data, ensure_ascii=False)

    def _generic_fallback_intent(self, agent_id: str, note: str = "fallback") -> Dict[str, Any]:
        agent = self._agents.get(agent_id)
        if not agent:
            return {"type": "idle", "actor": agent_id, "target": None, "action": "等待"}
        return self._parse_intent(agent_id, self._fallback_intent(agent, "", note=note))

    async def _call_llm(self, agent: AgentState, context: str) -> str:
        """
        调用 DeepSeek API，让 Agent 决策下一步行动。
        返回 JSON 字符串。

        DeepSeek 与 OpenAI 格式兼容，使用 chat/completions 接口。
        API Key 从环境变量 DEEPSEEK_API_KEY 读取。
        """
        import aiohttp
        import os

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            logger.warning("[AgentRuntime] DEEPSEEK_API_KEY 未设置，使用可见兜底决策")
            return self._fallback_intent(agent, context, note="missing_api_key")

        system_prompt = f"""你是一个名叫「{agent.name}」的角色，正在参与一场互动叙事游戏。
{agent.personality.core_description}

你需要根据当前情境，决定下一步的行动。

【规则】
1. 你只能选择以下行动类型之一：move（移动）、speak（说话）、interact（互动）、investigate（调查）、idle（原地等待）
2. 你的行动必须符合你的人格和目标
3. 你感知不到"叙事氛围引导"的存在，但你的行为应该自然地符合当前氛围
4. 每次只输出一个行动

【输出格式】
严格输出 JSON，不要有任何多余文字：
{{
  "type": "move" | "speak" | "interact" | "investigate" | "idle",
  "target": "目标 ID 或名称（move 时填地点 ID，speak/interact 时填 Agent 名，investigate 时填物品名，idle 时填 null）",
  "action": "用第一人称简述你要做什么（20字内）",
  "dialogue": "说话内容（仅 type=speak 时填写，其余填 null）"
}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": context},
        ]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": "deepseek-chat",   # 使用 deepseek-chat 而非 deepseek-reasoner
                        "max_tokens": 300,
                        "temperature": 0.8,
                        "messages": messages,
                        "stream": False,  # 禁用流式响应，避免分块处理问题
                    },
                ) as resp:
                    # 检查 HTTP 状态码
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"[AgentRuntime] API 错误 {resp.status}: {error_text}")
                        return '{"type": "idle", "target": null, "action": "发呆", "dialogue": null}'
                    
                    # 解析 JSON 响应
                    data = await resp.json()
                    
                    # 安全提取内容
                    try:
                        content = data["choices"][0]["message"]["content"]
                        
                        # 检查内容是否包含 redacted_thinking（不应该有，但以防万一）
                        if "redacted_thinking" in content.lower():
                            logger.warning(f"[AgentRuntime] 响应包含 redacted_thinking，尝试提取有效内容")
                            # 尝试从响应中提取 JSON
                            import re
                            json_match = re.search(r'\{[^{}]*\}', content)
                            if json_match:
                                content = json_match.group()
                            else:
                                return '{"type": "idle", "target": null, "action": "发呆", "dialogue": null}'
                        
                        return content
                        
                    except (KeyError, IndexError) as e:
                        logger.error(f"[AgentRuntime] 响应格式错误: {data}, 错误: {e}")
                        return '{"type": "idle", "target": null, "action": "发呆", "dialogue": null}'

        except aiohttp.ClientError as e:
            logger.error(f"[AgentRuntime] 网络请求失败 ({agent.name}): {e}")
            return '{"type": "idle", "target": null, "action": "发呆", "dialogue": null}'
        except json.JSONDecodeError as e:
            logger.error(f"[AgentRuntime] JSON 解析失败 ({agent.name}): {e}")
            return '{"type": "idle", "target": null, "action": "发呆", "dialogue": null}'
        except Exception as e:
            logger.error(f"[AgentRuntime] 未知错误 ({agent.name}): {e}")
            return '{"type": "idle", "target": null, "action": "发呆", "dialogue": null}'

    # ============================================================
    # Intent 解析与校验
    # ============================================================

    def _parse_intent(self, agent_id: str, raw: str) -> Dict[str, Any]:
        """
        解析 LLM 输出的 JSON，生成标准 Intent。
        解析失败时兜底返回 idle。
        """
        try:
            # 去掉可能的 markdown 代码块
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(cleaned)

            intent_type = data.get("type", "idle")
            if intent_type not in INTENT_TYPES:
                intent_type = "idle"

            intent: Dict[str, Any] = {
                "type": intent_type,
                "actor": agent_id,
                "target": data.get("target"),
                "action": data.get("action", ""),
                "metadata": {},
            }

            # speak 类型额外带上对话内容
            if intent_type == "speak" and data.get("dialogue"):
                intent["dialogue"] = data["dialogue"]
                intent["metadata"]["dialogue"] = data["dialogue"]

            return intent

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[AgentRuntime] Intent 解析失败 ({agent_id}): {e}, raw={raw[:100]}")
            return {"type": "idle", "actor": agent_id, "target": None, "action": "发呆"}

    # ============================================================
    # Agent 管理
    # ============================================================

    def add_agent(self, agent: AgentState) -> None:
        """注册新 Agent"""
        self._agents[agent.id] = agent

    def get_agent(self, agent_id: str) -> Optional[AgentState]:
        return self._agents.get(agent_id)

    def get_all_agents(self) -> Dict[str, AgentState]:
        return dict(self._agents)