# ============================================================
# modules/memory/vector_memory.py —— 长期记忆系统
# ============================================================
# 三层检索：
#   1. 关键词匹配（快速）
#   2. 语义相关性评分（中等）
#   3. 情绪标签匹配
# 支持记忆衰减、合并压缩、JSON 持久化。
# ============================================================

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from backend.model.agent import MemoryEntry

logger = logging.getLogger(__name__)


class VectorMemory:
    """长期记忆存储和语义检索系统。"""

    # 每个 agent 最多保留的长期记忆数
    MAX_LONG_TERM = 200
    # 记忆衰减系数（每次 recall 时，旧记忆的相关度降低）
    DECAY_PER_TICK = 0.001

    def __init__(self, storage_dir: str = "./data", collection_name: str = "agent_memories"):
        self._collection_name = collection_name
        self._initialized = False
        self._storage_dir = Path(storage_dir)
        # { agent_id: [MemoryEntry, ...] }
        self._long_term: Dict[str, List[MemoryEntry]] = {}
        # { agent_id: set(content_hash) } 用于快速去重
        self._content_hashes: Dict[str, set] = {}

    async def initialize(self) -> None:
        self._initialized = True
        self._load_from_disk()

    # ═══════════════════════════════════════════════════════════
    # 存储
    # ═══════════════════════════════════════════════════════════

    async def store_memory(self, agent_id: str, entry: MemoryEntry) -> bool:
        """存储记忆到长期记忆。返回 True 表示成功存入。"""
        if entry.importance < 0.4:
            return False
        if agent_id not in self._long_term:
            self._long_term[agent_id] = []
            self._content_hashes[agent_id] = set()

        # 去重：完全相同的内容不重复存
        content_hash = self._hash_content(entry.content)
        if content_hash in self._content_hashes[agent_id]:
            return False

        self._long_term[agent_id].append(entry)
        self._content_hashes[agent_id].add(content_hash)

        # 数量限制
        if len(self._long_term[agent_id]) > self.MAX_LONG_TERM:
            # 按重要性排序，保留最重要的
            self._long_term[agent_id].sort(key=lambda e: e.importance, reverse=True)
            removed = self._long_term[agent_id][self.MAX_LONG_TERM:]
            self._long_term[agent_id] = self._long_term[agent_id][:self.MAX_LONG_TERM]
            for r in removed:
                self._content_hashes[agent_id].discard(self._hash_content(r.content))

        self._save_to_disk()
        return True

    # ═══════════════════════════════════════════════════════════
    # 检索
    # ═══════════════════════════════════════════════════════════

    async def retrieve_relevant(
        self, agent_id: str, query: str, top_k: int = 5, current_tick: int = 0
    ) -> List[MemoryEntry]:
        """
        检索与 query 语义相关的长期记忆。
        三层评分：关键词 + 情绪匹配 + 时间衰减
        """
        memories = self._long_term.get(agent_id, [])
        if not memories:
            return []

        query_lower = query.lower()
        query_keywords = set(query_lower.split())

        scored = []
        for mem in memories:
            score = 0.0
            content_lower = mem.content.lower()
            content_words = set(content_lower.split())

            # 1. 关键词命中（权重 0.6）
            overlap = query_keywords & content_words
            if overlap:
                score += 0.6 * (len(overlap) / max(len(query_keywords), 1))

            # 2. 子串匹配（权重 0.2）
            for kw in query_keywords:
                if len(kw) >= 2 and kw in content_lower:
                    score += 0.2

            # 3. 情绪匹配（权重 0.1）
            if mem.emotion_tag != "neutral" and mem.emotion_tag in query_lower:
                score += 0.1

            # 4. 重要性加权
            score *= (0.5 + mem.importance * 0.5)

            # 5. 时间衰减（tick 越新越相关）
            if current_tick > 0:
                age = current_tick - mem.tick
                decay = max(0.3, 1.0 - age * self.DECAY_PER_TICK)
                score *= decay

            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    async def retrieve_by_emotion(
        self, agent_id: str, emotion: str, top_k: int = 5
    ) -> List[MemoryEntry]:
        """按情绪标签检索记忆。"""
        memories = self._long_term.get(agent_id, [])
        matches = [m for m in memories if m.emotion_tag == emotion]
        matches.sort(key=lambda m: m.importance, reverse=True)
        return matches[:top_k]

    async def retrieve_important(
        self, agent_id: str, top_k: int = 10, min_importance: float = 0.6
    ) -> List[MemoryEntry]:
        """获取最重要的记忆（不受时间衰减影响）。"""
        memories = self._long_term.get(agent_id, [])
        important = [m for m in memories if m.importance >= min_importance]
        important.sort(key=lambda m: m.importance, reverse=True)
        return important[:top_k]

    # ═══════════════════════════════════════════════════════════
    # 记忆管理
    # ═══════════════════════════════════════════════════════════

    async def consolidate(
        self, agent_id: str, short_term_entries: List[MemoryEntry],
        action_types: Dict[str, str] = None,
    ) -> int:
        """
        将短期记忆中重要的条目归档到长期记忆。
        返回归档数量。
        """
        from backend.modules.memory.importance import should_consolidate

        action_types = action_types or {}
        consolidated = 0
        for entry in short_term_entries:
            action_type = action_types.get(entry.id, "")
            if should_consolidate(entry, action_type):
                if await self.store_memory(agent_id, entry):
                    consolidated += 1
        return consolidated

    async def forget_old(self, agent_id: str, before_tick: int) -> int:
        """遗忘某个 tick 之前的低重要性记忆。返回删除数量。"""
        if agent_id not in self._long_term:
            return 0
        before = len(self._long_term[agent_id])
        self._long_term[agent_id] = [
            m for m in self._long_term[agent_id]
            if m.tick >= before_tick or m.importance >= 0.7
        ]
        deleted = before - len(self._long_term[agent_id])
        if deleted > 0:
            self._content_hashes[agent_id] = {
                self._hash_content(m.content) for m in self._long_term[agent_id]
            }
            self._save_to_disk()
        return deleted

    def rollback_after(self, target_tick: int) -> int:
        """时间线跳转时裁剪所有角色在 target_tick 之后的长期记忆。返回删除总数。"""
        total_deleted = 0
        for agent_id in list(self._long_term.keys()):
            before = len(self._long_term[agent_id])
            self._long_term[agent_id] = [
                m for m in self._long_term[agent_id]
                if m.tick <= target_tick
            ]
            deleted = before - len(self._long_term[agent_id])
            total_deleted += deleted
            if deleted > 0:
                self._content_hashes[agent_id] = {
                    self._hash_content(m.content) for m in self._long_term[agent_id]
                }
        if total_deleted > 0:
            self._save_to_disk()
        return total_deleted

    async def merge_similar(self, agent_id: str) -> int:
        """合并相似记忆（内容相似度 > 80% 的只保留最重要的）。"""
        if agent_id not in self._long_term:
            return 0
        memories = self._long_term[agent_id]
        before = len(memories)
        kept = []
        for i, m1 in enumerate(memories):
            is_dup = False
            for m2 in memories[i + 1:]:
                if self._similarity(m1.content, m2.content) > 0.8:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(m1)
        self._long_term[agent_id] = kept
        self._content_hashes[agent_id] = {self._hash_content(m.content) for m in kept}
        deleted = before - len(kept)
        if deleted > 0:
            self._save_to_disk()
        return deleted

    def get_stats(self, agent_id: str) -> dict:
        """获取某角色记忆统计。"""
        memories = self._long_term.get(agent_id, [])
        if not memories:
            return {"count": 0}
        importances = [m.importance for m in memories]
        emotions = [m.emotion_tag for m in memories]
        from collections import Counter
        return {
            "count": len(memories),
            "avg_importance": sum(importances) / len(importances),
            "max_importance": max(importances),
            "oldest_tick": min(m.tick for m in memories),
            "newest_tick": max(m.tick for m in memories),
            "top_emotions": Counter(emotions).most_common(3),
        }

    # ═══════════════════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _hash_content(content: str) -> str:
        """内容哈希用于去重。"""
        # 归一化：去空格、转小写
        normalized = re.sub(r"\s+", "", content.lower())
        # 取前 80 字符的哈希就是够用的去重键
        return normalized[:80]

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """简单文本相似度（基于共同词）。"""
        words_a = set(a)
        words_b = set(b)
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / max(len(words_a), len(words_b))

    def _save_to_disk(self) -> None:
        """JSON 持久化长期记忆。"""
        try:
            path = self._storage_dir / "long_term_memories.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for agent_id, entries in self._long_term.items():
                data[agent_id] = [
                    {
                        "id": e.id, "tick": e.tick, "content": e.content,
                        "importance": e.importance, "emotion_tag": e.emotion_tag,
                    }
                    for e in entries
                ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"长期记忆持久化失败: {e}")

    def _load_from_disk(self) -> None:
        """从磁盘加载长期记忆。"""
        try:
            path = self._storage_dir / "long_term_memories.json"
            if not path.exists():
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for agent_id, entries in data.items():
                self._long_term[agent_id] = []
                self._content_hashes[agent_id] = set()
                for e in entries:
                    entry = MemoryEntry(**e)
                    self._long_term[agent_id].append(entry)
                    self._content_hashes[agent_id].add(self._hash_content(entry.content))
            logger.info(f"长期记忆加载完成: {len(self._long_term)} 个角色")
        except Exception as e:
            logger.error(f"长期记忆加载失败: {e}")
