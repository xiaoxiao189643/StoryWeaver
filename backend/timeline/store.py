# ============================================================
# timeline/store.py —— 时间线数据持久化（JSON 文件）
# ============================================================
from __future__ import annotations

import json
import os
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TimelineStore:
    """时间线存储：管理 timeline nodes 和世界快照的 JSON 文件读写。"""

    def __init__(self, data_dir: str = "./data"):
        self._data_dir = data_dir
        self._timeline_dir = os.path.join(data_dir, "timeline")
        self._snapshots_dir = os.path.join(data_dir, "snapshots")
        self._nodes_file = os.path.join(self._timeline_dir, "nodes.json")

        # 确保目录存在
        os.makedirs(self._timeline_dir, exist_ok=True)
        os.makedirs(self._snapshots_dir, exist_ok=True)

        # 内存缓存
        self._nodes: List[Dict[str, Any]] = []
        self._load_nodes()

    # ═══════════════════════════════════════════════════════════
    # Timeline Nodes
    # ═══════════════════════════════════════════════════════════

    def _load_nodes(self) -> None:
        """从文件加载节点列表。"""
        if os.path.exists(self._nodes_file):
            try:
                with open(self._nodes_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._nodes = data.get("nodes", [])
            except Exception as e:
                logger.warning(f"[TimelineStore] 加载 nodes.json 失败: {e}")
                self._nodes = []
        else:
            self._nodes = []

    def _save_nodes(self) -> None:
        """将节点列表保存到文件。"""
        try:
            with open(self._nodes_file, "w", encoding="utf-8") as f:
                json.dump({"nodes": self._nodes}, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"[TimelineStore] 保存 nodes.json 失败: {e}")

    def add_node(self, node: Dict[str, Any]) -> str:
        """添加一个时间线节点。返回 node_id。按 node_id 去重，同时清理同 tick 的旧节点。"""
        node_id = node.get("node_id", "")
        tick = node.get("tick", 0)

        # 1. 按 node_id 去重：同一 node_id 的节点更新而非新增
        for i, existing in enumerate(self._nodes):
            if existing.get("node_id") == node_id:
                existing.update(node)
                self._save_nodes()
                return node_id

        # 2. 清理同 tick 的旧节点（防止 React 重复 key）
        self._nodes = [n for n in self._nodes if n.get("tick") != tick]

        # 3. 追加新节点
        self._nodes.append(node)
        self._nodes.sort(key=lambda n: n.get("tick", 0))
        self._save_nodes()
        logger.info(f"[TimelineStore] 添加节点: tick={tick}, node_id={node_id}, title={node.get('title', '')[:30]}")
        return node_id

    def get_nodes(self) -> List[Dict[str, Any]]:
        """返回所有节点（按 tick 升序）。"""
        return list(self._nodes)

    def get_node_at_tick(self, tick: int) -> Optional[Dict[str, Any]]:
        """查找最接近目标 tick 的节点。"""
        best = None
        for node in self._nodes:
            if node.get("tick", 0) <= tick:
                best = node
            else:
                break
        return best

    def rollback_after(self, tick: int, prune_snapshots: bool = True) -> Dict[str, int]:
        """删除目标 tick 之后的时间线节点和快照。"""
        before_nodes = len(self._nodes)
        self._nodes = [node for node in self._nodes if int(node.get("tick", 0)) <= tick]
        deleted_nodes = before_nodes - len(self._nodes)
        if deleted_nodes:
            self._save_nodes()

        deleted_snapshots = 0
        if prune_snapshots and os.path.exists(self._snapshots_dir):
            for snapshot_tick in self.list_snapshots():
                if snapshot_tick <= tick:
                    continue
                try:
                    os.remove(self.snapshot_path(snapshot_tick))
                    deleted_snapshots += 1
                except OSError as e:
                    logger.warning(f"[TimelineStore] 删除快照失败 tick={snapshot_tick}: {e}")

        return {"nodes": deleted_nodes, "snapshots": deleted_snapshots}

    # ═══════════════════════════════════════════════════════════
    # Snapshots
    # ═══════════════════════════════════════════════════════════

    def snapshot_path(self, tick: int) -> str:
        """返回指定 tick 的快照文件路径。"""
        return os.path.join(self._snapshots_dir, f"tick_{tick}.json")

    def save_snapshot(self, tick: int, data: Dict[str, Any]) -> str:
        """保存世界快照到 JSON 文件。返回文件路径。"""
        filepath = self.snapshot_path(tick)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"[TimelineStore] 快照已保存: tick={tick} ({len(json.dumps(data, default=str))} bytes)")
            return filepath
        except Exception as e:
            logger.error(f"[TimelineStore] 保存快照失败 tick={tick}: {e}")
            raise

    def load_snapshot(self, tick: int) -> Optional[Dict[str, Any]]:
        """加载指定 tick 的快照。如果文件不存在，尝试找最近的不超过 target 的快照。"""
        # 精确匹配
        filepath = self.snapshot_path(tick)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[TimelineStore] 加载快照失败 tick={tick}: {e}")
                return None

        # 回退：找最近的不超过 target tick 的快照
        best_tick = None
        if os.path.exists(self._snapshots_dir):
            for fname in os.listdir(self._snapshots_dir):
                if fname.startswith("tick_") and fname.endswith(".json"):
                    try:
                        t = int(fname.replace("tick_", "").replace(".json", ""))
                        if t <= tick and (best_tick is None or t > best_tick):
                            best_tick = t
                    except ValueError:
                        continue

        if best_tick is not None:
            logger.info(f"[TimelineStore] 精确快照 tick={tick} 不存在，回退到 tick={best_tick}")
            return self.load_snapshot(best_tick)

        return None

    def list_snapshots(self) -> List[int]:
        """列出所有快照的 tick 列表（升序）。"""
        ticks = []
        if os.path.exists(self._snapshots_dir):
            for fname in os.listdir(self._snapshots_dir):
                if fname.startswith("tick_") and fname.endswith(".json"):
                    try:
                        ticks.append(int(fname.replace("tick_", "").replace(".json", "")))
                    except ValueError:
                        continue
        return sorted(ticks)

    def get_available_snapshot_tick(self, target_tick: int) -> Optional[int]:
        """查找不超过 target_tick 的最近可用快照 tick。"""
        all_ticks = self.list_snapshots()
        best = None
        for t in all_ticks:
            if t <= target_tick:
                best = t
            else:
                break
        return best
