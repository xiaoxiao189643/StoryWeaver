# ============================================================
# storage/dialogue_store.py —— 统一章节对话存储
# ============================================================
# 按章节拆分 JSON 文件，无容量上限，支持按章节/tick 范围加载。
# 替代旧的 feed_cache.json + dialogues.json 双存储。
# ============================================================

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChapterDialogueStore:
    """按章节组织的对话持久化存储。

    data/dialogues/
      index.json          # 章节索引
      chapter_1.json      # 第 1 章对话
      chapter_2.json      # 第 2 章对话
      ...
    """

    def __init__(self, storage_dir: str = "./data"):
        self._dir = os.path.join(storage_dir, "dialogues")
        os.makedirs(self._dir, exist_ok=True)

        self._index: Dict[str, Any] = {"chapters": [], "current_chapter_id": None}
        self._current_file: Optional[str] = None
        self._current_chapter_id: Optional[str] = None
        self._current_dialogues: List[Dict] = []  # 当前章节的内存缓存

        self._load_index()

    # ═══════════════════════════════════════════════════════════
    # 索引管理
    # ═══════════════════════════════════════════════════════════

    def _index_path(self) -> str:
        return os.path.join(self._dir, "index.json")

    def _load_index(self) -> None:
        try:
            path = self._index_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # 确保索引结构完整（兼容被清空的文件）
                if not isinstance(loaded, dict):
                    loaded = {}
                loaded.setdefault("chapters", [])
                loaded.setdefault("current_chapter_id", None)
                self._index = loaded
                # 恢复当前章节
                cur_id = self._index.get("current_chapter_id")
                if cur_id:
                    self._current_chapter_id = cur_id
                    ch = self._get_chapter_entry(cur_id)
                    if ch:
                        self._current_file = os.path.join(self._dir, ch["file"])
                        self._current_dialogues = self._read_file(self._current_file)
                logger.info(
                    f"[DialogueStore] 索引已加载: {len(self._index.get('chapters', []))} 个章节, "
                    f"当前章节={cur_id}"
                )
        except Exception as e:
            logger.warning(f"[DialogueStore] 索引加载失败: {e}")
            self._index = {"chapters": [], "current_chapter_id": None}

    def _save_index(self) -> None:
        try:
            with open(self._index_path(), "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[DialogueStore] 索引保存失败: {e}")

    def _get_chapter_entry(self, chapter_id: str) -> Optional[Dict]:
        for ch in self._index.get("chapters", []):
            if ch["id"] == chapter_id:
                return ch
        return None

    def _read_file(self, path: str) -> List[Dict]:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _write_file(self, path: str, data: List[Dict]) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[DialogueStore] 文件写入失败 {path}: {e}")

    # ═══════════════════════════════════════════════════════════
    # 章节生命周期
    # ═══════════════════════════════════════════════════════════

    def start_chapter(self, chapter_id: str, tick: int) -> None:
        """开始新章节，关闭上一章并创建新文件。"""
        # 结束当前章节
        if self._current_chapter_id and self._current_chapter_id != chapter_id:
            self._end_current_chapter(tick - 1)

        # 检查是否已存在
        existing = self._get_chapter_entry(chapter_id)
        if existing:
            self._current_chapter_id = chapter_id
            self._current_file = os.path.join(self._dir, existing["file"])
            self._current_dialogues = self._read_file(self._current_file)
            self._index["current_chapter_id"] = chapter_id
            self._save_index()
            logger.info(f"[DialogueStore] 切换到已有章节: {chapter_id} (tick={tick})")
            return

        # 创建新章节
        file_name = f"{chapter_id}.json"
        chapter_entry = {
            "id": chapter_id,
            "start_tick": tick,
            "end_tick": None,
            "file": file_name,
        }
        self._index["chapters"].append(chapter_entry)
        self._index["current_chapter_id"] = chapter_id
        self._save_index()

        self._current_chapter_id = chapter_id
        self._current_file = os.path.join(self._dir, file_name)
        self._current_dialogues = []
        self._write_file(self._current_file, [])
        logger.info(f"[DialogueStore] 新章节: {chapter_id} (tick={tick})")

    def _end_current_chapter(self, end_tick: int) -> None:
        """关闭当前章节，写入 end_tick。"""
        if not self._current_chapter_id:
            return
        ch = self._get_chapter_entry(self._current_chapter_id)
        if ch:
            ch["end_tick"] = end_tick
            self._save_index()
        # 刷新当前章节到磁盘
        if self._current_file:
            self._write_file(self._current_file, self._current_dialogues)
        logger.info(
            f"[DialogueStore] 章节结束: {self._current_chapter_id} (end_tick={end_tick})"
        )

    def get_current_chapter_id(self) -> Optional[str]:
        return self._current_chapter_id

    # ═══════════════════════════════════════════════════════════
    # 对话追加
    # ═══════════════════════════════════════════════════════════

    def append(self, dialogue: Dict[str, Any]) -> None:
        """追加一条对话到当前章节文件（实时写盘）。"""
        if not self._current_file:
            logger.warning("[DialogueStore] 无当前章节，跳过追加")
            return

        dialogue.setdefault("tick", 0)
        self._current_dialogues.append(dialogue)

        # 实时写盘：追加模式（单条追加，避免全量序列化开销）
        try:
            # 对于小文件（< 1000 条），直接全量写；大文件用追加技巧
            if len(self._current_dialogues) <= 500:
                self._write_file(self._current_file, self._current_dialogues)
            else:
                # 大文件：每 10 条写一次，减少 IO
                if len(self._current_dialogues) % 10 == 0:
                    self._write_file(self._current_file, self._current_dialogues)
        except Exception as e:
            logger.error(f"[DialogueStore] 对话写入失败: {e}")

    def append_batch(self, dialogues: List[Dict[str, Any]]) -> None:
        """批量追加对话。"""
        for d in dialogues:
            self.append(d)

    def flush(self) -> None:
        """强制刷新当前章节到磁盘。"""
        if self._current_file and self._current_dialogues:
            self._write_file(self._current_file, self._current_dialogues)

    # ═══════════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════════

    def load_chapter(self, chapter_id: str) -> List[Dict]:
        """加载指定章节的全部对话。"""
        ch = self._get_chapter_entry(chapter_id)
        if not ch:
            return []
        path = os.path.join(self._dir, ch["file"])
        return self._read_file(path)

    def load_range(self, start_tick: int, end_tick: Optional[int] = None) -> List[Dict]:
        """按 tick 范围加载对话（跨章节）。"""
        all_dialogues: List[Dict] = []
        for ch in self._index.get("chapters", []):
            ch_start = ch["start_tick"]
            ch_end = ch.get("end_tick")

            # 章节在范围之后 → 跳过
            if end_tick is not None and ch_start > end_tick:
                break
            # 章节在范围之前 → 跳过
            if ch_end is not None and ch_end < start_tick:
                continue

            # 加载该章节并在内存中过滤
            path = os.path.join(self._dir, ch["file"])
            ch_dialogues = self._read_file(path)
            for d in ch_dialogues:
                t = d.get("tick", 0)
                if t >= start_tick and (end_tick is None or t <= end_tick):
                    all_dialogues.append(d)

        return all_dialogues

    def load_all(self, up_to_tick: Optional[int] = None) -> List[Dict]:
        """加载全部对话（可选：只到指定 tick）。"""
        if up_to_tick is not None:
            return self.load_range(0, up_to_tick)
        all_dialogues: List[Dict] = []
        for ch in self._index.get("chapters", []):
            path = os.path.join(self._dir, ch["file"])
            all_dialogues.extend(self._read_file(path))
        return all_dialogues

    def get_recent(self, limit: int = 30) -> List[Dict]:
        """获取最近 N 条对话（从当前章节末尾取）。"""
        if not self._current_dialogues:
            return []
        return self._current_dialogues[-limit:]

    def get_index(self) -> Dict[str, Any]:
        """返回章节索引。"""
        return dict(self._index)

    # ═══════════════════════════════════════════════════════════
    # 回滚（时间线跳转用）
    # ═══════════════════════════════════════════════════════════

    def rollback_after(self, target_tick: int) -> int:
        """删除 target_tick 之后的所有对话，返回删除条数。"""
        deleted = 0
        chapters_to_keep: List[Dict] = []

        for ch in self._index.get("chapters", []):
            ch_start = ch["start_tick"]
            ch_end = ch.get("end_tick")

            if ch_start > target_tick:
                # 整章在目标之后 → 删除文件
                path = os.path.join(self._dir, ch["file"])
                if os.path.exists(path):
                    os.remove(path)
                deleted += 1
                continue

            if ch_end is not None and ch_end <= target_tick:
                # 整章在目标之前 → 保留
                chapters_to_keep.append(ch)
                continue

            # 目标在章节范围内 → 裁剪
            path = os.path.join(self._dir, ch["file"])
            dialogues = self._read_file(path)
            before = len(dialogues)
            dialogues = [d for d in dialogues if d.get("tick", 0) <= target_tick]
            deleted += before - len(dialogues)
            self._write_file(path, dialogues)
            ch["end_tick"] = target_tick
            chapters_to_keep.append(ch)

        # 更新索引
        self._index["chapters"] = chapters_to_keep
        if chapters_to_keep:
            self._current_chapter_id = chapters_to_keep[-1]["id"]
            self._index["current_chapter_id"] = self._current_chapter_id
            ch = chapters_to_keep[-1]
            self._current_file = os.path.join(self._dir, ch["file"])
            self._current_dialogues = self._read_file(self._current_file)
        else:
            self._current_chapter_id = None
            self._index["current_chapter_id"] = None
            self._current_file = None
            self._current_dialogues = []

        self._save_index()
        if deleted:
            logger.info(f"[DialogueStore] 回滚完成: 删除 {deleted} 条对话")
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计。"""
        total = 0
        for ch in self._index.get("chapters", []):
            path = os.path.join(self._dir, ch["file"])
            total += len(self._read_file(path))
        return {
            "chapter_count": len(self._index.get("chapters", [])),
            "total_dialogues": total,
            "current_chapter": self._current_chapter_id,
            "current_chapter_dialogues": len(self._current_dialogues),
        }
