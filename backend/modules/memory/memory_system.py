"""Unified memory service with short-term + long-term + global memory."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.model.agent import MemoryEntry
from backend.modules.memory.short_term import ShortTermMemory
from backend.modules.memory.vector_memory import VectorMemory
from backend.modules.memory.importance import score_importance

logger = logging.getLogger(__name__)


class MemorySystem:
    """统一记忆服务：短期 / 长期 / 全局。"""

    GLOBAL_MEMORY_AGENT_ID = "__global__"

    def __init__(self, storage_dir: str = "./data"):
        self._memory_dir = Path(storage_dir) / "memory"
        self._global_path = self._memory_dir / "global_memories.json"
        self._agent_memory_dir = self._memory_dir / "agent_memories"
        self.short_term = ShortTermMemory()
        self.vector = VectorMemory(storage_dir)
        # { entry_id: action_type } 用于重要性评估
        self._action_types: Dict[str, str] = {}
        self._load_short_term()

    @staticmethod
    def _safe_agent_filename(agent_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id) + ".json"

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_short_term(self) -> None:
        data: Dict[str, List[dict]] = {}
        global_entries = self._read_json(self._global_path, [])
        if global_entries:
            data[self.GLOBAL_MEMORY_AGENT_ID] = global_entries
        if self._agent_memory_dir.exists():
            for path in self._agent_memory_dir.glob("*.json"):
                data[path.stem] = self._read_json(path, [])
        self.short_term.import_all(data)

    def _save_short_term(self) -> None:
        exported = self.short_term.export_all()
        self._write_json(self._global_path, exported.get(self.GLOBAL_MEMORY_AGENT_ID, []))
        for agent_id, entries in exported.items():
            if agent_id == self.GLOBAL_MEMORY_AGENT_ID:
                continue
            path = self._agent_memory_dir / self._safe_agent_filename(agent_id)
            self._write_json(path, entries)

    # ═══════════════════════════════════════════════════════════
    # 短期记忆
    # ═══════════════════════════════════════════════════════════

    def add_short_term(self, agent_id: str, entry: MemoryEntry,
                       action_type: str = "") -> bool:
        """添加短期记忆。自动评估重要性。返回 True 表示成功。"""
        # 去重
        recent = self.short_term.get_recent(agent_id, 1)
        if recent and recent[0].content == entry.content:
            return False

        # 自动评估重要性
        if entry.importance == 0.5:  # 默认值 → 自动打分
            entry.importance = score_importance(entry, action_type)

        self.short_term.add(agent_id, entry)
        if action_type:
            self._action_types[entry.id] = action_type

        # 每次写入后立即持久化
        self._save_short_term()

        return True

    def add_global(self, content: str, tick: int, importance: float = 0.7,
                   emotion_tag: str = "neutral") -> MemoryEntry:
        """添加全局记忆（所有角色可见）。"""
        import uuid
        entry = MemoryEntry(
            id=f"global_{uuid.uuid4().hex[:8]}",
            tick=tick,
            content=content,
            importance=importance,
            emotion_tag=emotion_tag,
        )
        self.short_term.add(self.GLOBAL_MEMORY_AGENT_ID, entry)
        return entry

    def get_recent(self, agent_id: str, n: int = 10) -> List[MemoryEntry]:
        return self.short_term.get_recent(agent_id, n)

    def get_recent_with_global(
        self, agent_id: str, limit: int = 10,
        include_global: bool = True, world_id: Optional[str] = None,
    ) -> List[MemoryEntry]:
        entries = self.short_term.get_all(agent_id)
        if include_global and agent_id != self.GLOBAL_MEMORY_AGENT_ID:
            entries = self.short_term.get_all(self.GLOBAL_MEMORY_AGENT_ID) + entries
        if world_id:
            entries = [e for e in entries if e.world_id == world_id]
        entries.sort(key=lambda e: e.tick)
        return entries[-limit:]

    # ═══════════════════════════════════════════════════════════
    # 长期记忆
    # ═══════════════════════════════════════════════════════════

    async def consolidate(self, agent_id: str) -> int:
        """将短期记忆中的重要条目归档到长期记忆。"""
        all_entries = self.short_term.get_all(agent_id)
        if not all_entries:
            return 0
        action_types = {e.id: self._action_types.get(e.id, "") for e in all_entries}
        return await self.vector.consolidate(agent_id, all_entries, action_types)

    async def recall_relevant(
        self, agent_id: str, query: str, top_k: int = 5, current_tick: int = 0,
    ) -> List[MemoryEntry]:
        """从长期记忆中检索最相关的记忆。"""
        return await self.vector.retrieve_relevant(agent_id, query, top_k, current_tick)

    async def recall_by_emotion(
        self, agent_id: str, emotion: str, top_k: int = 5,
    ) -> List[MemoryEntry]:
        return await self.vector.retrieve_by_emotion(agent_id, emotion, top_k)

    async def forget_old(self, agent_id: str, before_tick: int) -> int:
        return await self.vector.forget_old(agent_id, before_tick)

    async def merge_similar(self, agent_id: str) -> int:
        return await self.vector.merge_similar(agent_id)

    # ═══════════════════════════════════════════════════════════
    # 组合检索（短期 + 长期）
    # ═══════════════════════════════════════════════════════════

    async def recall_combined(
        self, agent_id: str, situation: str = "", top_k: int = 10,
        current_tick: int = 0, include_global: bool = True,
    ) -> List[MemoryEntry]:
        """
        组合检索：短期最近 + 长期相关 + 全局。
        用于 Agent 决策时提供全面的记忆上下文。
        """
        seen_ids = set()
        combined = []

        # 1. 短期记忆（最近 N 条）
        short = self.get_recent(agent_id, 8)
        for e in short:
            if e.id not in seen_ids:
                seen_ids.add(e.id)
                combined.append(e)

        # 2. 长期相关记忆（语义检索）
        if situation:
            long = await self.vector.retrieve_relevant(
                agent_id, situation, top_k=5, current_tick=current_tick
            )
            for e in long:
                if e.id not in seen_ids:
                    seen_ids.add(e.id)
                    combined.append(e)

        # 3. 重要记忆（不受时间衰减）
        important = await self.vector.retrieve_important(agent_id, top_k=3)
        for e in important:
            if e.id not in seen_ids:
                seen_ids.add(e.id)
                combined.append(e)

        # 4. 全局记忆
        if include_global:
            globals = self.get_recent(self.GLOBAL_MEMORY_AGENT_ID, 3)
            for e in globals:
                if e.id not in seen_ids:
                    seen_ids.add(e.id)
                    combined.append(e)

        combined.sort(key=lambda e: (e.importance, e.tick), reverse=True)
        return combined[:top_k]

    # ═══════════════════════════════════════════════════════════
    # 记忆上下文构建（给 LLM 用）
    # ═══════════════════════════════════════════════════════════

    def build_context_for_llm(
        self, agent_id: str, current_situation: str = "",
        current_tick: int = 0, limit: int = 12,
    ) -> str:
        """
        为 LLM 构建结构化的记忆上下文文本。
        """
        memories = self.get_recent_with_global(agent_id, limit=limit)
        if not memories:
            return "（暂无记忆）"

        header = ""
        if current_situation:
            header = f"【当前情境】{current_situation}\n"

        lines = []
        # 按时间分组
        recent_tick = current_tick
        for mem in reversed(memories):
            time_gap = recent_tick - mem.tick
            gap_text = ""
            if time_gap > 20:
                gap_text = f"（{time_gap} tick前）"
            elif time_gap > 5:
                gap_text = f"（不久前）"

            importance_mark = "⭐" if mem.importance >= 0.7 else ("·" if mem.importance >= 0.5 else "  ")
            lines.append(f"{importance_mark}{gap_text} {mem.content}")
            recent_tick = mem.tick

        return header + "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # 搜索
    # ═══════════════════════════════════════════════════════════

    async def search(
        self, agent_id: str, query: str, limit: int = 10,
        include_global: bool = False, world_id: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """关键词搜索（短期 + 长期）。"""
        keyword = query.lower()
        candidates = self.short_term.get_all(agent_id)
        if include_global and agent_id != self.GLOBAL_MEMORY_AGENT_ID:
            candidates += self.short_term.get_all(self.GLOBAL_MEMORY_AGENT_ID)
        if world_id:
            candidates = [e for e in candidates if e.world_id == world_id]
        matches = [e for e in candidates if keyword in e.content.lower()
                   or keyword in e.emotion_tag.lower()]

        relevant = await self.vector.retrieve_relevant(agent_id, query, top_k=limit)
        if world_id:
            relevant = [e for e in relevant if e.world_id == world_id]

        seen = set()
        results = []
        for e in matches + relevant:
            if e.id in seen:
                continue
            seen.add(e.id)
            results.append(e)
            if len(results) >= limit:
                break
        return results

    def rollback_after(
        self, tick: int, agent_id: Optional[str] = None,
        world_id: Optional[str] = None,
    ) -> int:
        deleted = self.short_term.rollback_after(tick, agent_id, world_id)
        self._save_short_term()
        # 同时裁剪长期（向量）记忆，防止时间线跳转后保留"未来"记忆
        vector_deleted = self.vector.rollback_after(tick)
        if vector_deleted > 0:
            logger.info(f"[MemorySystem] 向量记忆已裁剪: {vector_deleted} 条")
        return deleted + vector_deleted

    async def initialize(self) -> None:
        await self.vector.initialize()

    # ═══════════════════════════════════════════════════════════
    # 统计
    # ═══════════════════════════════════════════════════════════

    def get_stats(self, agent_id: str) -> dict:
        short_count = len(self.short_term.get_all(agent_id))
        long_stats = self.vector.get_stats(agent_id)
        return {
            "short_term_count": short_count,
            "long_term": long_stats,
            "total": short_count + long_stats.get("count", 0),
        }
