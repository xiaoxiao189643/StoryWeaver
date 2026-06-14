# ============================================================
# framework/bus.py —— 模块间消息总线
# ============================================================
# 所有模块间通信走这里，不直接 import。
# send(msg) → 根据 msg.to + msg.type 路由到对应 handler
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Dict

logger = logging.getLogger(__name__)

Handler = Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]


class MessageBus:
    """进程内消息总线。每个模块注册自己的 handler，运行时路由消息。"""

    def __init__(self):
        # { "module_name": { "message_type": handler_fn } }
        self._routes: Dict[str, Dict[str, Handler]] = {}

    def register(self, module: str, handlers: Dict[str, Handler]) -> None:
        """注册一个模块的所有消息处理器"""
        self._routes[module] = handlers
        logger.info(f"[Bus] 注册模块 {module}: {list(handlers.keys())}")

    async def send(self, to: str, type: str, payload: Dict[str, Any]) -> Any:
        """
        发送消息到指定模块。
        返回 handler 的执行结果。
        """
        module_routes = self._routes.get(to)
        if not module_routes:
            logger.warning(f"[Bus] 未找到模块 {to}")
            return None

        handler = module_routes.get(type)
        if not handler:
            logger.warning(f"[Bus] 模块 {to} 未注册消息类型 {type}")
            return None

        try:
            return await handler(payload)
        except Exception as e:
            logger.error(f"[Bus] {to}.{type} 处理失败: {e}")
            raise


# 全局单例
bus = MessageBus()
