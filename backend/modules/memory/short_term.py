# ============================================================
# agent/memory/short_term.py —— 短期记忆
# ============================================================
# 短期记忆 = 当前场景的即时信息。
# - 类似人类的"工作记忆"
# - 容量有限（默认最近 N 条）
# - 重要的条目会转移到长期记忆
# - 不重要的条目会随时间遗忘
# ============================================================

from backend.model.agent import MemoryEntry
from typing import Dict, List, Optional
from collections import deque


class ShortTermMemory:
    """
    短期记忆系统。
    每个 Agent 拥有独立的短期记忆。
    """

    MAX_SHORT_TERM = 50  # 最多保留最近 50 条

    def __init__(self):
        # agent_id -> deque[MemoryEntry]
        self._store: Dict[str, deque] = {}

    def add(self, agent_id: str, entry: MemoryEntry) -> None:
        """添加一条短期记忆"""
        if agent_id not in self._store:
            self._store[agent_id] = deque(maxlen=self.MAX_SHORT_TERM)
        self._store[agent_id].append(entry)

    def get_all(self, agent_id: str) -> List[MemoryEntry]:
        """获取某个 Agent 的所有短期记忆"""
        return list(self._store.get(agent_id, []))

    def get_recent(self, agent_id: str, n: int = 10) -> List[MemoryEntry]:
        """获取最近 N 条记忆"""
        queue = self._store.get(agent_id, deque())
        return list(queue)[-n:]

    def clear(self, agent_id: str) -> None:
        """清空某个 Agent 的短期记忆（场景切换时）"""
        self._store[agent_id] = deque(maxlen=self.MAX_SHORT_TERM)

    def rollback_after(
        self,
        tick: int,
        agent_id: Optional[str] = None,
        world_id: Optional[str] = None,
    ) -> int:
        """Remove memories after a tick. Returns the number of deleted entries."""
        target_ids = [agent_id] if agent_id else list(self._store.keys())
        deleted = 0

        for target_id in target_ids:
            queue = self._store.get(target_id)
            if queue is None:
                continue

            kept = [
                entry for entry in queue
                if entry.tick <= tick or (world_id and entry.world_id != world_id)
            ]
            deleted += len(queue) - len(kept)
            self._store[target_id] = deque(kept, maxlen=self.MAX_SHORT_TERM)

        return deleted

    def export_all(self) -> Dict[str, List[dict]]:
        """Export all short-term memories for simple file persistence."""
        return {
            agent_id: [entry.model_dump() for entry in queue]
            for agent_id, queue in self._store.items()
        }

    def import_all(self, data: Dict[str, List[dict]]) -> None:
        """Replace in-memory store with previously exported memory data."""
        self._store = {}
        for agent_id, entries in data.items():
            self._store[agent_id] = deque(maxlen=self.MAX_SHORT_TERM)
            for entry_data in entries[-self.MAX_SHORT_TERM:]:
                self._store[agent_id].append(MemoryEntry(**entry_data))

    def get_important_entries(self, agent_id: str, threshold: float = 0.7) -> List[MemoryEntry]:
        """
        获取重要性超过阈值且尚未转移到长期记忆的条目。
        用于决定哪些需要归档到长期记忆。
        """
        return [
            e for e in self.get_all(agent_id)
            if e.importance >= threshold and not e.is_retrieved
        ]
