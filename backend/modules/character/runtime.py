# ============================================================
# modules/character/runtime.py —— NPC 决策运行时
# ============================================================
# 导演调度：按优先级排序（被点名 > 新事件 > 空闲超时），轮转避免垄断。
# ============================================================

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.model.agent import AgentState, MemoryEntry
from backend.framework.bus import bus

logger = logging.getLogger(__name__)


class CharacterRuntime:
    """导演调度的 NPC 运行时。"""

    MAX_IDLE_TICKS = 1       # 空闲 1 tick 后主动行动（约5秒）
    MAX_ACTIONS_PER_TICK = 4 # 活跃对话时放宽上限

    def __init__(self):
        self._agents: Dict[str, AgentState] = {}
        self._idle_counters: Dict[str, int] = {}
        self._wake_events: Dict[str, List[str]] = {}
        self._last_acted_tick: Dict[str, int] = {}   # 每个 agent 上次行动的 tick
        self._round_robin_order: List[str] = []       # 轮转顺序

        # ── Tick 级上下文（由 WorldSimulator 每 tick 注入） ──
        self._tick_context: Dict[str, Any] = {}

    # ═══════════════════════════════════════════════════════════
    # Agent 管理
    # ═══════════════════════════════════════════════════════════

    def register_agent(self, agent: AgentState) -> None:
        self._agents[agent.id] = agent
        self._idle_counters[agent.id] = 0
        self._wake_events[agent.id] = []
        self._last_acted_tick[agent.id] = -999
        self._round_robin_order.append(agent.id)

    def get_agent(self, agent_id: str) -> Optional[AgentState]:
        return self._agents.get(agent_id)

    def get_all_agents(self) -> Dict[str, AgentState]:
        return dict(self._agents)

    def wake_agent(self, agent_id: str, event_desc: str) -> None:
        if agent_id in self._wake_events:
            self._wake_events[agent_id].append(event_desc)

    def set_tick_context(self, **kwargs) -> None:
        """由 WorldSimulator 每 tick 注入叙事上下文。"""
        self._tick_context = kwargs

    # ═══════════════════════════════════════════════════════════
    # 每 tick 主循环 — 导演调度
    # ═══════════════════════════════════════════════════════════

    async def tick(self, current_tick: int, world_id: str = "default") -> List[Dict[str, Any]]:
        intents = []

        # ── 1. 收集候选 + 计算优先级 ──
        candidates: List[tuple] = []  # (priority, agent_id, events)
        for agent_id, agent in self._agents.items():
            if agent.is_controlled:
                continue
            events = list(self._wake_events.get(agent_id, []))

            # 检查是否有"被点名"事件（别人直接对他说话）
            was_addressed = any("对你说" in e or "向你" in e for e in events)

            if events:
                # 被点名 = 最高优先级，必须先回
                priority = 0 if was_addressed else 1
            else:
                self._idle_counters[agent_id] = self._idle_counters.get(agent_id, 0) + 1
                if self._idle_counters[agent_id] >= self.MAX_IDLE_TICKS:
                    events = ["感到无事可做，决定主动行动"]
                    priority = 3  # 最低优先
                else:
                    continue

            # 轮转加分：越久没说话，优先级越高
            ticks_since_last = current_tick - self._last_acted_tick.get(agent_id, 0)
            priority -= min(ticks_since_last / 10, 0.5)  # 每10 tick 降 0.5 优先

            candidates.append((priority, agent_id, events, was_addressed))

        if not candidates:
            return intents

        # ── 2. 按优先级排序（数字越小越优先） ──
        candidates.sort(key=lambda x: x[0])

        # ── 3. 决定本 tick 行动上限 ──
        active_conversation = any(
            any("对你说" in e or "向你" in e for e in self._wake_events.get(aid, []))
            for aid in self._agents
        )
        max_actions = self.MAX_ACTIONS_PER_TICK if active_conversation else 4

        # ── 4. 收集本轮要执行的 agent（不超过 max_actions，但被点名的必须执行） ──
        to_execute: List[tuple] = []  # (agent_id, priority, was_addressed, events)
        for _, agent_id, events, was_addressed in candidates:
            if len(to_execute) >= max_actions and not was_addressed:
                continue
            to_execute.append((agent_id, _, was_addressed, list(events)))

        if not to_execute:
            return intents

        # ── 5. 清空状态（在并发调用之前） ──
        for agent_id, _priority, _wa, _evts in to_execute:
            self._idle_counters[agent_id] = 0
            self._wake_events[agent_id] = []
            self._last_acted_tick[agent_id] = current_tick

        # ── 5.5 收集所有角色最近发言（用于相互感知，避免重复） ──
        all_recent_dialogues: Dict[str, List[str]] = {}
        for agent_id in self._agents:
            try:
                mem_result = await bus.send(to="memory", type="memory_get_recent", payload={
                    "world_id": world_id, "agent_id": agent_id, "limit": 10,
                })
                mems = mem_result.get("memories", []) if mem_result else []
                all_recent_dialogues[agent_id] = [
                    m["content"] for m in mems
                    if m.get("content", "").startswith('"') or '"' in m.get("content", "")
                ][-4:]
            except Exception:
                all_recent_dialogues[agent_id] = []

        # ── 6. 并发执行所有 agent LLM 决策 ──
        async def decide_one(agent_id: str, evts: List[str]):
            agent = self._agents[agent_id]
            # 收集其他角色的最近发言
            others = []
            for aid, dlogs in all_recent_dialogues.items():
                if aid != agent_id:
                    for d in dlogs[-2:]:
                        name = self._agents[aid].name if aid in self._agents else aid
                        others.append(f"{name}: {d}")
            try:
                return await asyncio.wait_for(
                    self._decide(agent, evts, current_tick, world_id, other_dialogues=others),
                    timeout=20
                )
            except asyncio.TimeoutError:
                logger.warning(f"[Runtime] {agent.name} 决策超时，跳过")
                return {"type": "idle", "actor": agent.id, "action": "发呆",
                        "target": None, "dialogue": None, "reason": "超时"}
            except Exception as e:
                logger.exception(f"[Runtime] {agent.name} 决策异常: {e}")
                return {"type": "idle", "actor": agent.id, "action": "发呆",
                        "target": None, "dialogue": None, "reason": "异常"}

        tasks = [decide_one(aid, evts) for aid, _, _, evts in to_execute]
        results = await asyncio.gather(*tasks)

        # ── 6.5 限制每 tick 发言人数（从 tick 上下文读取，早期更少） ──
        MAX_SPEAK_PER_TICK = self._tick_context.get("max_speakers", 2)
        speak_count = 0
        for i, (agent_id, _, was_addressed, _) in enumerate(to_execute):
            intent = results[i]
            if intent.get("type") == "speak" and intent.get("dialogue"):
                if speak_count >= MAX_SPEAK_PER_TICK:
                    results[i] = {"type": "idle", "actor": agent_id,
                                  "action": "安静聆听", "target": None,
                                  "dialogue": None, "reason": "等待发言时机"}
                else:
                    speak_count += 1

        # ── 7. 去重：只检查与自己的最近发言完全匹配 ──
        for i, (agent_id, _, _, _) in enumerate(to_execute):
            intent = results[i]
            dialogue = intent.get("dialogue")
            if dialogue and len(dialogue) > 3:
                dialogue_clean = dialogue.strip().replace('"', "").replace("「", "").replace("」", "").replace(" ", "")
                for mem_text in all_recent_dialogues.get(agent_id, []):
                    mem_clean = str(mem_text).strip().replace('"', "").replace("「", "").replace("」", "").replace(" ", "")
                    # 只检查完全相同（去标点空格后）
                    if len(dialogue_clean) > 4 and dialogue_clean == mem_clean:
                        logger.info(f"[去重] {self._agents[agent_id].name} 完全重复被拦截: {dialogue_clean[:40]}")
                        results[i] = {"type": "investigate", "actor": agent_id,
                                       "action": "环顾四周寻找新线索", "target": None,
                                       "dialogue": None, "reason": "避免重复发言"}
                        break

        # ── 8. 按优先级排序后写入记忆 + 广播 ──
        for (agent_id, _priority, _wa, _evts), intent in zip(to_execute, results):
            intents.append(intent)

            try:
                dialogue_text = intent.get("dialogue") or ""
                if dialogue_text and dialogue_text != "null":
                    mem_content = f"\"{dialogue_text}\""
                else:
                    action = intent.get('action') or '进行了行动'
                    if action.startswith("我"):
                        action = action[1:]
                    if action == "null" or not action.strip():
                        action = "安静地等待着"
                    mem_content = f"{self._agents[agent_id].name}{action}"
                await bus.send(to="memory", type="memory_add", payload={
                    "world_id": world_id, "agent_id": agent_id,
                    "content": mem_content,
                    "action_type": intent.get("type", "idle"),
                    "type": "action", "tick": current_tick,
                })
            except Exception as e:
                logger.exception(f"[Memory] 记忆写入异常 — {agent_id}: {e}")

            self._broadcast_observation(agent_id, self._agents[agent_id].name, intent, current_tick)

        return intents

    def _broadcast_observation(self, actor_id: str, actor_name: str, intent: Dict, tick: int) -> None:
        intent_type = intent.get("type", "")
        dialogue = intent.get("dialogue", "")
        target = intent.get("target", "")

        # 说话：被点名的人获得明确回应信号；无目标=对所有人说，全员可回应
        if intent_type == "speak":
            if target and target in self._agents:
                # 定向对话：目标知道被点名，其他人只是观察
                target_name = self._agents[target].name
                obs_to_target = f"{actor_name}对你说：「{dialogue}」" if dialogue else f"{actor_name}向你搭话"
                obs_to_others = f"{actor_name}对{target_name}说了话"
                for aid in self._agents:
                    if aid == actor_id:
                        continue
                    if aid == target:
                        self._wake_events.setdefault(aid, []).append(obs_to_target)
                    else:
                        self._wake_events.setdefault(aid, []).append(f"【观察到】{obs_to_others}")
                    self._idle_counters[aid] = 0
            else:
                # 无目标 = 对所有人说，全员都可以接话
                obs = f"{actor_name}说：「{dialogue}」" if dialogue else f"{actor_name}说了话"
                for aid in self._agents:
                    if aid != actor_id:
                        self._wake_events.setdefault(aid, []).append(obs)
                        self._idle_counters[aid] = 0
        else:
            action = intent.get("action", "")
            if action:
                obs = f"【观察到】{actor_name}{action}"
            else:
                obs = f"【观察到】{actor_name}做了些事"
            for aid in self._agents:
                if aid != actor_id:
                    self._wake_events.setdefault(aid, []).append(obs)
                    self._idle_counters[aid] = 0

    # ═══════════════════════════════════════════════════════════
    # 决策（走框架 → LLM 模块）
    # ═══════════════════════════════════════════════════════════

    async def _decide(self, agent: AgentState, events: List[str],
                      tick: int, world_id: str,
                      other_dialogues: List[str] = None) -> Dict[str, Any]:
        # ── Tick 级上下文（先获取，后续多处使用） ──
        ctx = self._tick_context

        # ── 提取本角色对玩家的信任值 ──
        player_trust_all = ctx.get("player_trust", {})
        my_player_trust = player_trust_all.get(agent.id, {})
        player_trust_value = my_player_trust.get("trust", 0.0)

        instruction_result = await bus.send(to="director", type="request_instruction", payload={
            "world_id": world_id, "agent_id": agent.id,
            "phase": ctx.get("phase", {}),
            "stagnation": ctx.get("stagnation", False),
        })
        director_instruction = instruction_result.get("instruction", "自然推进剧情") if instruction_result else "自然推进剧情"

        # 组合记忆：短期最近 + 长期相关 + 重要记忆（新记忆系统）
        try:
            mem_result = await bus.send(to="memory", type="memory_get_recent", payload={
                "world_id": world_id, "agent_id": agent.id, "limit": 30,
            })
            all_mems = list(mem_result.get("memories", []) if mem_result else [])
        except Exception:
            all_mems = []

        if len(all_mems) > 15:
            import random
            recent_12 = all_mems[-12:]
            older = all_mems[:-12]
            sampled_older = random.sample(older, min(3, len(older)))
            selected = recent_12 + sampled_older
            selected.sort(key=lambda m: m.get("tick", 0))
        else:
            selected = all_mems
        recent_memories = [m["content"] for m in selected]

        rel_result = await bus.send(to="memory", type="memory_relationship_get_all", payload={
            "world_id": world_id, "agent_id": agent.id,
        })
        relationships = {}
        if rel_result:
            for r in rel_result.get("relationships", []):
                relationships[r["target_id"]] = r["value"]

        # ── 角色认知（知道什么/不知道什么） ──
        all_knowledge = ctx.get("character_knowledge", {})
        my_knowledge = all_knowledge.get(agent.name, [])
        others_knowledge = {n: k for n, k in all_knowledge.items() if n != agent.name}

        active_goals = "；".join([g.description for g in agent.goals if g.is_active][:3]) or "暂无明确目标"
        decision = await bus.send(to="llm", type="llm_decide_action", payload={
            "agent_id": agent.id,
            "agent_name": agent.name,
            "personality_desc": agent.personality.core_description if agent.personality else "普通的角色",
            "emotion": agent.emotion.current_mood if agent.emotion else "平静",
            "emotion_intensity": agent.emotion.intensity if agent.emotion else 0.5,
            "goals": active_goals,
            "events": events,
            "recent_memories": recent_memories,
            "relationships": relationships,
            "instruction": director_instruction,
            "other_dialogues": other_dialogues or [],
            # 新增：叙事上下文 + 角色认知
            "phase": ctx.get("phase", {}),
            "incident": ctx.get("incident", ""),
            "stagnation": ctx.get("stagnation", False),
            "fix_hints": ctx.get("fix_hints", ""),
            "my_knowledge": my_knowledge,
            "others_knowledge": others_knowledge,
            "opening_narration": ctx.get("opening_narration"),
            "player_directive": ctx.get("player_directive", ""),
            "player_trust": player_trust_value,
            "player_intervention": ctx.get("player_intervention", {}),
        })

        if not decision:
            decision = {"type": "idle", "action": "发呆", "target": None, "dialogue": None, "reason": "框架返回空"}

        # 去重：检查最近3条记忆，避免重复发言
        dialogue = decision.get("dialogue")
        if dialogue and recent_memories:
            dialogue_clean = dialogue.strip().replace("\"", "").replace("「", "").replace("」", "")
            for mem in recent_memories[-3:]:
                mem_clean = str(mem).strip().replace("\"", "").replace("「", "").replace("」", "")
                if len(dialogue_clean) > 3 and dialogue_clean == mem_clean:
                    logger.info(f"[Runtime] {agent.name} 重复发言被拦截: {dialogue_clean[:30]}")
                    decision = {"type": "investigate", "action": "环顾四周，寻找新的线索",
                               "target": None, "dialogue": None, "reason": "避免重复发言"}
                    break

        # 防止 None 值输出为 "null"
        action = decision.get("action") or agent.current_action or "等待"
        target = decision.get("target") or None
        dialogue_out = decision.get("dialogue") or None

        return {
            "type": decision.get("type") or "idle",
            "actor": agent.id,
            "action": action,
            "target": target,
            "dialogue": dialogue_out,
            "emotion": decision.get("emotion") or "平静",
            "emotion_intensity": decision.get("emotion_intensity", 0.5),
            "reason": decision.get("reason") or "",
        }
