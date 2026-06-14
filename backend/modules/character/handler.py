# ============================================================
# modules/character/handler.py —— 框架消息处理器
# ============================================================
# 角色模块通过此文件接收框架层转发的消息。
# 每个消息类型对应一个异步处理函数。
#
# TODO（框架化完成后）：
#   - character_router.py 删掉，前端请求统一走框架 → handler
#   - runtime 里的直接 import 换成发框架消息
# ============================================================

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.model.agent import MemoryEntry
from backend.model.dialogue import DialogueRecord
from backend.utils.i18n import cn_emotion


class CharacterHandler:
    """
    角色模块消息处理器。
    框架层把消息路由到这里，处理后返回结果。
    """

    def __init__(self, runtime, belief_system, memory_system, relation_store, dialogue_store, event_bus):
        self._runtime = runtime
        self._belief_system = belief_system
        self._memory_system = memory_system
        self._relation_store = relation_store
        self._dialogue_store = dialogue_store
        self._event_bus = event_bus

    # ═══════════════════════════════════════════════════════════
    # 前端请求处理（7 个）
    # ═══════════════════════════════════════════════════════════

    async def handle_get_agent_list(self, payload: Dict) -> List[Dict]:
        agents = self._runtime.get_all_agents()
        return [{"id": a.id, "name": a.name, "state": a.current_action or "待机",
                 "emotion": cn_emotion(a.emotion.current_mood) if a.emotion else "平静"} for a in agents.values()]

    async def handle_get_agent_detail(self, payload: Dict) -> Dict:
        agent = self._runtime.get_agent(payload["agent_id"])
        if not agent:
            raise ValueError(f"Agent {payload['agent_id']} 不存在")
        active_goal = next((g.description for g in agent.goals if g.is_active), "")
        personality = {}
        if agent.personality:
            for trait, val in agent.personality.traits.items():
                personality[trait.value] = int(val * 100)
        return {
            "id": agent.id, "name": agent.name, "state": agent.current_action or "待机",
            "emotion": cn_emotion(agent.emotion.current_mood) if agent.emotion else "平静",
            "trustPlayer": int((agent.trust_player + 1.0) / 2.0 * 100), "goal": active_goal,
            "personality": personality,
            "motivation": agent.personality.core_description if agent.personality else "",
        }

    async def handle_get_agent_relationships(self, payload: Dict) -> Dict:
        rels = self._relation_store.get_relationships(payload["agent_id"])
        return {
            "agent_id": payload["agent_id"],
            "relationships": [{"targetId": r.target_id, "value": int(r.trust_value),
                               "attitude": r.attitude, "history": r.history} for r in rels],
        }

    async def handle_get_agent_belief(self, payload: Dict) -> Dict:
        belief = self._belief_system.get_belief(payload["agent_id"])
        if not belief:
            return {"facts": [], "suspicions": [], "secrets": [], "misconceptions": []}
        return {
            "facts": list(belief.facts.values()) if belief.facts else [],
            "suspicions": [f"{k}: {v:.0%}" for k, v in belief.suspicions.items()] if belief.suspicions else [],
            "secrets": [],
            "misconceptions": [],
        }

    async def handle_write_agent_belief(self, payload: Dict) -> Dict:
        agent_id = payload["agent_id"]
        op = payload["operation"]
        btype = payload["belief_type"]
        content = payload["content"]

        if btype == "suspicions":
            if op == "add":
                self._belief_system.add_suspicion(agent_id, content, 0.5)
            elif op == "remove":
                belief = self._belief_system.ensure_belief(agent_id)
                to_remove = [k for k in belief.suspicions if content in k]
                for k in to_remove:
                    del belief.suspicions[k]
            elif op == "replace":
                belief = self._belief_system.ensure_belief(agent_id)
                belief.suspicions.clear()
                self._belief_system.add_suspicion(agent_id, content, 0.5)
        elif btype == "facts":
            if op in ("add", "replace"):
                self._belief_system.set_fact(agent_id, content, content, certainty=1.0)
            elif op == "remove":
                belief = self._belief_system.ensure_belief(agent_id)
                to_remove = [k for k, v in belief.facts.items() if v == content]
                for k in to_remove:
                    del belief.facts[k]
                    belief.certainty.pop(k, None)
        else:
            key = f"__{btype}__{uuid.uuid4().hex[:8]}"
            if op in ("add", "replace"):
                self._belief_system.set_fact(agent_id, key, content, certainty=1.0)
            elif op == "remove":
                belief = self._belief_system.ensure_belief(agent_id)
                to_remove = [k for k, v in belief.facts.items() if v == content and k.startswith(f"__{btype}__")]
                for k in to_remove:
                    del belief.facts[k]
                    belief.certainty.pop(k, None)
        op_label = {"add": "已新增", "remove": "已移除", "replace": "已替换"}.get(op, "已更新")
        return {"success": True, "message": f"{op_label}{btype}认知: {content}"}

    async def handle_get_dialogue_history(self, payload: Dict) -> Dict:
        records, has_more = self._dialogue_store.get_history(
            payload["world_id"], limit=payload.get("limit", 20), cursor=payload.get("cursor"))
        return {
            "messages": [{"id": r.id, "speaker_id": r.speaker_id, "speaker_name": r.speaker_name,
                          "content": r.content, "timestamp": r.timestamp} for r in records],
            "hasMore": has_more,
        }

    async def handle_report_agent_event(self, payload: Dict) -> Dict:
        event_id = f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        agent_id = payload["agent_id"]

        # 记忆
        parts = [f"我{payload['action']}"]
        if payload.get("target_id"):
            parts.append(f"对 {payload['target_id']}")
        if payload.get("result"):
            parts.append(f"，结果：{payload['result']}")
        if payload.get("dialogue"):
            parts.append(f"，我说：「{payload['dialogue']}」")
        emo = payload.get("emotion_change", {})
        if emo:
            parts.append(f"，情绪从{emo.get('from', '?')}变为{emo.get('to', '?')}")

        entry = MemoryEntry(id=event_id, tick=0, content="".join(parts), importance=0.6,
                            emotion_tag=emo.get("to", "neutral") if emo else "neutral")
        self._memory_system.add_short_term(agent_id, entry)

        # EventBus
        await self._event_bus.publish("agent:action", agent_id=agent_id, action=payload["action"],
                                      target_id=payload.get("target_id"), result=payload.get("result"),
                                      dialogue=payload.get("dialogue"))

        # 对白
        if payload.get("dialogue"):
            self._dialogue_store.append(DialogueRecord(
                id=f"msg_{event_id}", world_id=payload["world_id"], speaker_id=agent_id,
                speaker_name="", content=payload["dialogue"],
                timestamp=datetime.now(timezone.utc).isoformat(), target_id=payload.get("target_id")))

        return {"success": True, "event_id": event_id}

    # ═══════════════════════════════════════════════════════════
    # NPC Tick 调试
    # ═══════════════════════════════════════════════════════════

    async def handle_debug_tick(self, payload: Dict) -> Dict:
        world_id = payload.get("world_id", "default")
        force_all = payload.get("force_all", False)

        if force_all:
            for aid in self._runtime.get_all_agents():
                self._runtime.wake_agent(aid, "调试触发：强制决策")

        intents = await self._runtime.tick(
            current_tick=payload.get("tick", 1),
            world_id=world_id,
        )
        return {
            "tick": payload.get("tick", 1),
            "agent_count": len(self._runtime.get_all_agents()),
            "decisions": [
                {"npc_id": i.get("actor"),
                 "npc_name": self._runtime.get_agent(i.get("actor", "")).name if self._runtime.get_agent(i.get("actor", "")) else "",
                 "action_type": i.get("type"), "action": i.get("action"),
                 "target": i.get("target"), "dialogue": i.get("dialogue"), "reason": i.get("reason")}
                for i in intents
            ],
        }
