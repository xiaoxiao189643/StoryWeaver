from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from backend.framework.bus import bus
from backend.model.agent import MemoryEntry
from backend.modules.memory.schema import DialogueRecord


class MemoryHandler:
    """Message handlers for memories, dialogue history, and relationships."""

    def __init__(self, memory_system, relation_store, dialogue_store, ground_truth=None):
        self._memory = memory_system
        self._relation = relation_store
        self._dialogue = dialogue_store
        self._ground_truth = ground_truth

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}

    def _tick(self, payload: Dict) -> int:
        if payload.get("tick") is not None:
            return int(payload["tick"])
        if self._ground_truth is not None:
            return self._ground_truth.get_truth().time.tick
        return 0

    def _make_entry(self, payload: Dict) -> MemoryEntry:
        return MemoryEntry(
            id=payload.get("id") or str(uuid4()),
            world_id=payload.get("world_id", "default_world"),
            tick=self._tick(payload),
            content=payload.get("content", ""),
            importance=float(payload.get("importance", 0.5)),
            emotion_tag=payload.get("emotion_tag", "neutral"),
            scope=payload.get("scope", "agent"),
            metadata=payload.get("metadata", {}),
        )

    @staticmethod
    def _entry_to_dict(entry: MemoryEntry) -> Dict[str, Any]:
        return entry.model_dump(exclude={"is_retrieved"})

    @staticmethod
    def _dialogue_to_dict(record: DialogueRecord) -> Dict[str, Any]:
        result = record.model_dump()
        result["listener_id"] = result.pop("target_id")
        return result

    @staticmethod
    def _relationship_to_dict(relationship) -> Dict[str, Any]:
        return {
            "agent_a": relationship.agent_id,
            "agent_b": relationship.target_id,
            "trust": relationship.trust_value / 100.0,
            "familiarity": relationship.familiarity,
            "sentiment": relationship.sentiment,
            "last_interaction_tick": relationship.last_interaction_tick,
        }

    async def handle_add(self, payload: Dict) -> Dict:
        payload = {**payload, "scope": "agent"}
        entry = self._make_entry(payload)
        agent_id = payload["agent_id"]
        action_type = payload.get("action_type", "")
        self._memory.add_short_term(agent_id, entry, action_type)
        return {
            "ok": True,
            "world_id": entry.world_id,
            "agent_id": agent_id,
            "scope": "agent",
            "importance": entry.importance,
            "memory": self._entry_to_dict(entry),
        }

    async def handle_director_add(self, payload: Dict) -> Dict:
        is_global = payload.get("scope") == "global" or not payload.get("agent_id")
        agent_id = self._memory.GLOBAL_MEMORY_AGENT_ID if is_global else payload["agent_id"]
        payload = {**payload, "scope": "global" if is_global else "agent"}
        entry = self._make_entry(payload)
        action_type = payload.get("action_type", "")
        self._memory.add_short_term(agent_id, entry, action_type)
        if (
            self._ground_truth is not None
            and is_global
        ):
            self._ground_truth.add_event_log(f"[tick {entry.tick}] {entry.content}")
        return {
            "ok": True,
            "world_id": entry.world_id,
            "agent_id": agent_id,
            "scope": entry.scope,
            "memory": self._entry_to_dict(entry),
        }

    async def handle_get_recent(self, payload: Dict) -> Dict:
        agent_id = payload["agent_id"]
        limit = int(payload.get("limit", 10))
        include_global = self._as_bool(payload.get("include_global"), True)
        world_id = payload.get("world_id", "default_world")
        memories = self._memory.get_recent_with_global(agent_id, limit, include_global, world_id)
        return {
            "world_id": world_id,
            "agent_id": agent_id,
            "include_global": include_global,
            "memories": [self._entry_to_dict(m) for m in memories],
        }

    async def handle_search(self, payload: Dict) -> Dict:
        agent_id = payload["agent_id"]
        query = payload.get("query", "")
        if not query:
            raise ValueError("query is required")
        limit = int(payload.get("limit", 10))
        world_id = payload.get("world_id", "default_world")
        memories = await self._memory.search(
            agent_id,
            query,
            limit,
            self._as_bool(payload.get("include_global"), False),
            world_id,
        )
        return {
            "world_id": world_id,
            "agent_id": agent_id,
            "query": query,
            "memories": [self._entry_to_dict(m) for m in memories],
        }

    async def handle_rollback(self, payload: Dict) -> Dict:
        tick = int(payload["tick"])
        world_id = payload.get("world_id", "default_world")
        deleted_memories = self._memory.rollback_after(tick, payload.get("agent_id"), world_id)
        deleted_dialogues = 0
        if self._as_bool(payload.get("include_dialogue_history"), True):
            deleted_dialogues = self._dialogue.rollback_after(tick, world_id)
        return {
            "ok": True,
            "world_id": world_id,
            "rollback_tick": tick,
            "agent_id": payload.get("agent_id"),
            "deleted_memories": deleted_memories,
            "deleted_dialogues": deleted_dialogues,
        }

    async def handle_dialogue_record(self, payload: Dict) -> Dict:
        record = DialogueRecord(
            id=payload.get("id") or str(uuid4()),
            world_id=payload.get("world_id", "default_world"),
            speaker_id=payload["speaker_id"],
            speaker_name=payload.get("speaker_name", ""),
            content=payload["content"],
            timestamp=payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            target_id=payload.get("listener_id") or payload.get("target_id"),
            tick=self._tick(payload),
            metadata=payload.get("metadata", {}),
        )
        self._dialogue.append(record)
        return {
            "ok": True,
            "world_id": record.world_id,
            "dialogue": self._dialogue_to_dict(record),
        }

    async def handle_dialogue_history(self, payload: Dict) -> Dict:
        records, has_more = self._dialogue.get_history(
            payload.get("world_id", "default_world"),
            limit=int(payload.get("limit", 20)),
            cursor=payload.get("cursor"),
            agent_id=payload.get("agent_id"),
            other_agent_id=payload.get("other_agent_id"),
        )
        return {
            "world_id": payload.get("world_id", "default_world"),
            "dialogues": [self._dialogue_to_dict(record) for record in records],
            "has_more": has_more,
        }

    async def handle_relationship_get(self, payload: Dict) -> Dict:
        agent_id = payload.get("agent_id") or payload["agent_a"]
        target_id = payload.get("target_id") or payload["agent_b"]
        world_id = payload.get("world_id", "default_world")
        relationship = self._relation.get_relationship(agent_id, target_id, world_id)
        if not relationship:
            return {"world_id": world_id, "relationship": None}
        return {
            "world_id": world_id,
            "relationship": self._relationship_to_dict(relationship),
        }

    async def handle_relationship_update(self, payload: Dict) -> Dict:
        agent_id = payload.get("agent_id") or payload["agent_a"]
        target_id = payload.get("target_id") or payload["agent_b"]
        world_id = payload.get("world_id", "default_world")
        if payload.get("delta") is not None:
            relationship = self._relation.update(
                agent_id,
                target_id,
                delta=float(payload["delta"]),
                reason=payload.get("reason", ""),
            )
        elif any(payload.get(field) is not None for field in (
            "trust", "familiarity", "sentiment", "last_interaction_tick"
        )):
            current = self._relation.get_relationship(agent_id, target_id, world_id)
            trust = payload.get("trust")
            trust_value = current.trust_value if trust is None and current else float(trust or 0.0) * 100
            trust_value = max(-100.0, min(100.0, trust_value))
            attitude = "friendly" if trust_value >= 60 else ("neutral" if trust_value >= -20 else "hostile")
            relationship = self._relation.set_relationship(
                agent_id,
                target_id,
                trust_value=trust_value,
                attitude=attitude,
                history=(current.history if current else []) + [payload.get("reason", "relationship updated")],
                world_id=world_id,
                familiarity=payload.get("familiarity", current.familiarity if current else None),
                sentiment=payload.get("sentiment", current.sentiment if current else None),
                last_interaction_tick=payload.get(
                    "last_interaction_tick",
                    current.last_interaction_tick if current else None,
                ),
            )
        else:
            raise ValueError("at least one relationship field is required")
        return {
            "ok": True,
            "world_id": world_id,
            "relationship": self._relationship_to_dict(relationship),
        }

    async def handle_relationship_get_all(self, payload: Dict) -> Dict:
        relationships = self._relation.get_relationships(payload["agent_id"])
        return {
            "relationships": [
                {
                    "target_id": relationship.target_id,
                    "value": relationship.trust_value,
                    "attitude": relationship.attitude,
                    "history": relationship.history,
                }
                for relationship in relationships
            ]
        }

    async def handle_relationship_decay_all(self, payload: Dict) -> Dict:
        """对所有 NPC 间关系执行信任衰减"""
        rate = float(payload.get("rate", 0.003))
        count = self._relation.decay_all(rate)
        return {"ok": True, "decayed": count}


    # ═══════════════════════════════════════════════════════════
    # 记忆统计 & 管理
    # ═══════════════════════════════════════════════════════════

    async def handle_memory_stats(self, payload: Dict) -> Dict:
        agent_id = payload["agent_id"]
        return self._memory.get_stats(agent_id)

    async def handle_memory_context(self, payload: Dict) -> Dict:
        """构建 LLM 用的结构化记忆上下文。"""
        agent_id = payload["agent_id"]
        situation = payload.get("situation", "")
        current_tick = int(payload.get("tick", 0))
        context_text = self._memory.build_context_for_llm(
            agent_id, situation, current_tick, limit=12,
        )
        return {"agent_id": agent_id, "context": context_text}

    async def handle_memory_consolidate(self, payload: Dict) -> Dict:
        agent_id = payload.get("agent_id")
        if agent_id:
            count = await self._memory.consolidate(agent_id)
        else:
            count = 0
            # 不指定 agent_id 时，合并所有有短期记忆的角色
            for aid in self._memory.short_term._store:
                count += await self._memory.consolidate(aid)
        return {"ok": True, "consolidated": count}

    async def handle_memory_forget(self, payload: Dict) -> Dict:
        agent_id = payload["agent_id"]
        before_tick = int(payload.get("before_tick", 0))
        count = await self._memory.forget_old(agent_id, before_tick)
        return {"ok": True, "forgotten": count}

    async def handle_memory_merge(self, payload: Dict) -> Dict:
        agent_id = payload["agent_id"]
        count = await self._memory.merge_similar(agent_id)
        return {"ok": True, "merged": count}


def register_memory_handler(memory_system, relation_store, dialogue_store, ground_truth=None):
    handler = MemoryHandler(memory_system, relation_store, dialogue_store, ground_truth)
    bus.register("memory", {
        "memory_add": handler.handle_add,
        "add_memory": handler.handle_director_add,
        "memory_get_recent": handler.handle_get_recent,
        "get_recent_memories": handler.handle_get_recent,
        "memory_search": handler.handle_search,
        "memory_rollback": handler.handle_rollback,
        "memory_dialogue_record": handler.handle_dialogue_record,
        "memory_dialogue_add": handler.handle_dialogue_record,
        "memory_dialogue_history": handler.handle_dialogue_history,
        "memory_relationship_get": handler.handle_relationship_get,
        "memory_relationship_update": handler.handle_relationship_update,
        "memory_relationship_get_all": handler.handle_relationship_get_all,
        "memory_relationship_decay_all": handler.handle_relationship_decay_all,
        "memory_stats": handler.handle_memory_stats,
        "memory_context": handler.handle_memory_context,
        "memory_consolidate": handler.handle_memory_consolidate,
        "memory_forget": handler.handle_memory_forget,
        "memory_merge": handler.handle_memory_merge,
    })
    return handler
