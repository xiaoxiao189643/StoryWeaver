# ============================================================
# timeline/handler.py —— 时间线 REST 端点 + 总线消息处理
# ============================================================
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional

from backend.framework.bus import bus

logger = logging.getLogger(__name__)


class TimelineHandler:
    """时间线模块消息处理器。"""

    def __init__(self, store, world_simulator=None, director=None):
        self._store = store
        self._world = world_simulator
        self._director = director

    def set_world(self, world_simulator):
        self._world = world_simulator

    def set_director(self, director):
        self._director = director

    # ═══════════════════════════════════════════════════════════
    # REST 处理
    # ═══════════════════════════════════════════════════════════

    async def handle_get_timeline_tree(self, payload: Dict) -> Dict:
        """返回时间线节点列表 + 当前状态。"""
        nodes = self._store.get_nodes()
        current_tick = self._world._tick_count if self._world else 0
        snapshots = self._store.list_snapshots()

        return {
            "nodes": nodes,
            "current_tick": current_tick,
            "snapshot_ticks": snapshots,
            "total_nodes": len(nodes),
        }

    async def handle_get_snapshots(self, payload: Dict) -> List[int]:
        """列出所有快照 tick 列表。"""
        return self._store.list_snapshots()

    async def handle_jump_to_tick(self, payload: Dict) -> Dict:
        """跳转到指定 tick 并恢复世界状态。同时广播新状态给所有 WS 客户端。"""
        target_tick = int(payload.get("tick", 0))
        mode = payload.get("mode", "rewrite")

        if mode == "view":
            return {
                "success": True,
                "mode": "view",
                "tick": target_tick,
                "current_tick": self._world._tick_count if self._world else 0,
                "message": f"已进入只读回看 tick {target_tick}",
            }

        # 防止与正在进行的 tick 死锁：等待 tick 锁释放（最多 5 秒）
        import asyncio, time as _time
        if self._world and getattr(self._world, "_tick_in_progress", False):
            logger.info(f"[Timeline] tick 进行中，等待其完成后再跳转...")
            waited = 0
            while getattr(self._world, "_tick_in_progress", False) and waited < 5:
                await asyncio.sleep(0.5)
                waited += 0.5
            if getattr(self._world, "_tick_in_progress", False):
                return {
                    "success": False,
                    "message": "当前 tick 仍在执行中，请稍后再试。",
                }

        # 找最近的快照
        available_tick = self._store.get_available_snapshot_tick(target_tick)
        if available_tick is None:
            return {
                "success": False,
                "message": f"没有可用的快照（目标 tick={target_tick}）。请先推进一些 tick 生成快照。",
            }

        if available_tick != target_tick:
            logger.info(
                f"[Timeline] 请求的 tick={target_tick} 无快照，"
                f"使用最近的快照 tick={available_tick}"
            )

        # 加载快照
        snapshot_data = self._store.load_snapshot(available_tick)
        if not snapshot_data:
            return {
                "success": False,
                "message": f"无法加载快照 tick={available_tick}",
            }

        # 恢复状态
        from backend.timeline.snapshot import restore_from_snapshot

        result = await restore_from_snapshot(
            self._world,
            self._director,
            self._world._memory if hasattr(self._world, "_memory") else None,
            snapshot_data,
        )

        # 恢复后强制清除 tick 锁，防止残留锁定
        if self._world:
            self._world._tick_in_progress = False

        pruned = self._store.rollback_after(result.get("tick", available_tick))

        # 裁剪统一章节对话存储
        if hasattr(self._world, '_chapter_dialogue_store') and self._world._chapter_dialogue_store:
            try:
                d_deleted = self._world._chapter_dialogue_store.rollback_after(available_tick)
                if d_deleted:
                    logger.info(f"[Timeline] ChapterDialogueStore 已裁剪: {d_deleted} 条")
            except Exception as e:
                logger.error(f"[Timeline] ChapterDialogueStore 裁剪失败: {e}")
        result["mode"] = "rewrite"
        result["requested_tick"] = target_tick
        result["available_tick"] = available_tick
        result["pruned"] = pruned

        # 广播新状态给所有 WS 客户端
        try:
            from backend.framework.websocket import manager, _message, WSMessageType

            frontend = self._world.get_frontend_snapshot()
            await manager.broadcast(_message(WSMessageType.WORLD_STATE, frontend.get("world_state")))
            for agent in frontend.get("agents", []):
                await manager.broadcast(_message(WSMessageType.AGENT_STATE, agent))
        except Exception as e:
            logger.warning(f"[Timeline] WS 广播失败: {e}")

        return result


# ═══════════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════════

def register_timeline_handler(
    store,
    world_simulator=None,
    director=None,
):
    """在消息总线上注册时间线处理程序。"""
    h = TimelineHandler(store, world_simulator, director)

    bus.register("timeline", {
        "get_timeline_tree": h.handle_get_timeline_tree,
        "get_snapshots": h.handle_get_snapshots,
        "jump_to_tick": h.handle_jump_to_tick,
    })

    logger.info("[Timeline] 时间线处理程序已注册")
    return h
