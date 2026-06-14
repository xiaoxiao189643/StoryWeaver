# ============================================================
# framework/websocket.py —— 前端协议 WebSocket 桥
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.framework.event_bus import global_event_bus

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info(f"WebSocket 连接已建立。当前连接数: {len(self._connections)}")

    async def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info(f"WebSocket 连接已断开。当前连接数: {len(self._connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        dead_connections = set()
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.add(ws)
        for ws in dead_connections:
            await self.disconnect(ws)

    async def send_to(self, ws: WebSocket, message: Dict[str, Any]) -> None:
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            await self.disconnect(ws)

    def has_connections(self) -> bool:
        return bool(self._connections)


manager = ConnectionManager()


class WSMessageType:
    # ── 基础流 (PVE核心) ──
    SETUP_OUTLINE = "setup:outline"
    STORY_INITIALIZED = "story:initialized"
    DIALOGUE = "dialogue"
    DIALOGUE_TOKEN_STREAM = "dialogue:token_stream"
    DIRECTOR_PROMPT = "director:prompt"
    WORLD_STATE = "world_state"
    AGENT_STATE = "agent_state"
    NARRATIVE_EVENT = "narrative_event"

    # ── 控制流 (时空操控) ──
    GAME_CONTROL = "game:control"
    STORY_ROLLBACK_RESULT = "story:rollback_result"

    # ── 时间线跳转 ──
    TIMELINE_JUMP = "timeline:jump"              # 客户端上行：请求跳转
    TIMELINE_JUMP_RESULT = "timeline:jump_result" # 服务端下行：跳转完成

    # ── 沉浸流 (跨媒体调度) ──
    SYSTEM_SKILL_CHECK = "system:skill_check"
    DIRECTOR_ATMOSPHERE = "director:atmosphere"
    STORY_SETTLEMENT = "story:settlement"
    INTERVENTION_RESULT = "intervention_result"

    # ── 上行指令 (Client → Server) ──
    SETUP_START_GENERATION = "setup:start_generation"
    PLAYER_INTERVENTION = "player:intervention"
    STORY_ROLLBACK = "story:rollback"
    SYNC_REQUEST = "sync_request"
    PING = "ping"

    # ── 下行响应 (Server → Client) ──
    PONG = "pong"
    SYSTEM_ERROR = "system:error"


def _world(app: FastAPI):
    world = getattr(app.state, "world_simulator", None)
    if not world:
        raise RuntimeError("WorldSimulator 尚未初始化")
    return world


def _message(type_: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"type": type_, "data": data or {}}


def _outline_payload(app: FastAPI) -> Dict[str, Any]:
    snapshot = _world(app).get_frontend_snapshot()
    return {
        "background": snapshot.get("background", "雪山别墅中的秘密正在发酵。"),
        "summary": snapshot.get("summary", "多名角色围绕线索、关系和隐藏动机自然演化故事。"),
        "initial_quest": snapshot.get("initial_quest", "推动角色调查线索并保持叙事张力。"),
    }


def _player_dialogue_payload(content: str) -> Dict[str, Any]:
    return {
        "id": f"player_{int(time.time() * 1000)}",
        "speakerId": "player_01",
        "speakerName": "降下旨意的玩家",
        "thought": "",
        "content": content,
        "emotion": "neutral",
    }


def _intervention_to_intent(data: Dict[str, Any]) -> Dict[str, Any]:
    """将玩家干预数据转换为后端 Intent 字典。

    前端干预类型 → 后端意图类型映射：
      observation / suggestion / persuasion / speak → "speak"
      move / override                           → "move"
      interact                                  → "interact"
      investigate                               → "investigate"
    """
    # ── 前端干预类型 → 后端意图类型 ──
    _TYPE_MAP = {
        "observation": "speak",
        "suggestion": "speak",
        "persuasion": "speak",
        "speak": "speak",
        "move": "move",
        "override": "move",
        "interact": "interact",
        "investigate": "investigate",
    }
    frontend_type = data.get("type") or "persuasion"
    intent_type = _TYPE_MAP.get(frontend_type, "speak")

    # 优先取 content 字段（简化格式），兼容旧格式
    content = data.get("content") or ""
    if not content:
        detail = data.get(frontend_type, {}) if isinstance(data.get(frontend_type), dict) else {}
        content = detail.get("claim") or data.get("text") or ""

    target = data.get("target_agent_id") or "all"
    return {
        "type": intent_type,
        "actor": "player_01",
        "target": target,
        "action": content or "玩家介入",
        "dialogue": content,
        "frontend_type": frontend_type,  # 保留原始类型，供 LLM 评估使用
        "metadata": {},
    }


async def _send_initial_state(ws: WebSocket, app: FastAPI) -> None:
    world = _world(app)
    await manager.send_to(ws, _message(WSMessageType.SETUP_OUTLINE, _outline_payload(app)))
    await manager.send_to(ws, _message(WSMessageType.STORY_INITIALIZED, {"message": "故事宇宙已就绪"}))
    await manager.send_to(ws, _message(WSMessageType.WORLD_STATE, world.get_frontend_world_state()))
    for agent in world.get_frontend_agents():
        await manager.send_to(ws, _message(WSMessageType.AGENT_STATE, agent))


async def _broadcast_tick_result(app: FastAPI, tick_result: Dict[str, Any]) -> None:
    events = tick_result.get("frontend_events") or _world(app).extract_frontend_events(tick_result)
    for payload in events.get("world_state", []):
        await manager.broadcast(_message(WSMessageType.WORLD_STATE, payload))
    for payload in events.get("agent_state", []):
        await manager.broadcast(_message(WSMessageType.AGENT_STATE, payload))
    for payload in events.get("dialogue", []):
        # 全量对话
        await manager.broadcast(_message(WSMessageType.DIALOGUE, payload))
        # 同时拆分为 token_stream 格式（逐字推送）
        content = payload.get("content", "")
        msg_id = payload.get("id", f"msg_{int(time.time() * 1000)}")
        speaker_id = payload.get("speakerId", "")
        # 整段作为单 token 发送（完整对话），设置 is_end=True
        await manager.broadcast(_message(WSMessageType.DIALOGUE_TOKEN_STREAM, {
            "msg_id": msg_id,
            "speakerId": speaker_id,
            "token": content,
            "is_thought": bool(payload.get("thought", "")),
            "is_end": True,
        }))
    for payload in events.get("narrative_event", []):
        await manager.broadcast(_message(WSMessageType.NARRATIVE_EVENT, payload))


async def run_one_tick(app: FastAPI):
    """执行一个 tick"""
    tick_result = await _world(app).tick()
    await _broadcast_tick_result(app, tick_result)

async def _tick_loop_removed(app: FastAPI) -> None:
    while True:
        if not getattr(app.state, "tick_started", False):
            await asyncio.sleep(5)
            continue

        # 暂停时不推进 tick
        if getattr(app.state, "story_paused", False):
            await asyncio.sleep(1)
            continue

        # 玩家干预进行中——等待完成，不抢锁
        if getattr(app.state, "player_intervention_pending", False):
            await asyncio.sleep(1)
            continue

        try:
            tick_result = await _world(app).tick()
            await _broadcast_tick_result(app, tick_result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"tick 循环异常: {e}")

        # 玩家刚干预完——短暂等待让前端轮询到 NPC 回应
        last_player = getattr(app.state, "_last_player_tick_time", 0)
        if last_player > 0:
            elapsed = time.time() - last_player
            if elapsed < 3:
                await asyncio.sleep(3 - elapsed)
            app.state._last_player_tick_time = 0

        await asyncio.sleep(8)  # tick 间间隔


async def start_tick_loop(app: FastAPI) -> None:
    """前端点击开始后调用——立即推首个 tick + 启动后台循环"""
    if getattr(app.state, "tick_started", False):
        return  # 已经开始，不重复
    app.state.tick_started = True
    _ensure_tick_loop(app)
    try:
        tick_result = await _world(app).tick()
        await _broadcast_tick_result(app, tick_result)
    except Exception as e:
        logger.exception(f"首次 tick 失败: {e}")

def _ensure_tick_loop(app: FastAPI) -> None:
    task = getattr(app.state, "story_tick_task", None)
    if task and not task.done():
        return
    app.state.story_tick_task = asyncio.create_task(_tick_loop_removed(app))


def _ensure_event_bridge(app: FastAPI) -> None:
    if getattr(app.state, "event_bus_subscriptions", None):
        return

    async def forward_narrative(_event_type: str, **data):
        payload = {
            "tick": data.get("tick", 0),
            "event_type": data.get("event_type") or data.get("type") or _event_type,
            "description": data.get("description", ""),
            "timestamp": data.get("timestamp", int(time.time())),
        }
        await manager.broadcast(_message(WSMessageType.NARRATIVE_EVENT, payload))

    async def forward_directive(_event_type: str, **data):
        await manager.broadcast(_message(WSMessageType.DIRECTOR_PROMPT, data))

    async def forward_time(_event_type: str, **data):
        payload = _world(app).get_frontend_world_state()
        await manager.broadcast(_message(WSMessageType.WORLD_STATE, payload))

    async def forward_goal(_event_type: str, **data):
        goal = data.get("goal", {})
        # 导演 SceneGoal 是内部指令（如"让侦探去调查厨房"），不应作为旁白展示给玩家。
        # 真正的导演旁白已通过 extract_frontend_events → dialogue 消息正确送达前端。
        await manager.broadcast(_message(WSMessageType.DIRECTOR_PROMPT, {
            "goal": goal,
            "tick": data.get("tick", 0),
        }))

    async def forward_atmosphere(_event_type: str, **data):
        await manager.broadcast(_message(WSMessageType.DIRECTOR_ATMOSPHERE, data))

    async def forward_skill_check(_event_type: str, **data):
        await manager.broadcast(_message(WSMessageType.SYSTEM_SKILL_CHECK, data))

    async def forward_settlement(_event_type: str, **data):
        await manager.broadcast(_message(WSMessageType.STORY_SETTLEMENT, data))

    async def forward_token_stream(_event_type: str, **data):
        await manager.broadcast(_message(WSMessageType.DIALOGUE_TOKEN_STREAM, data))

    app.state.event_bus_subscriptions = [
        global_event_bus.subscribe("narrative_event", forward_narrative),
        global_event_bus.subscribe("directive", forward_directive),
        global_event_bus.subscribe("world:time_changed", forward_time),
        global_event_bus.subscribe("director:goal_updated", forward_goal),
        global_event_bus.subscribe("director:atmosphere", forward_atmosphere),
        global_event_bus.subscribe("system:skill_check", forward_skill_check),
        global_event_bus.subscribe("story:settlement", forward_settlement),
        global_event_bus.subscribe("dialogue:token_stream", forward_token_stream),
    ]


async def handle_websocket(ws: WebSocket, app: FastAPI) -> None:
    await manager.connect(ws)
    _ensure_event_bridge(app)

    try:
        await _send_initial_state(ws, app)
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")
            msg_data = data.get("data", {}) or {}

            if msg_type == WSMessageType.PING:
                await manager.send_to(ws, _message(WSMessageType.PONG))
            elif msg_type == WSMessageType.SETUP_START_GENERATION:
                await manager.broadcast(_message(WSMessageType.STORY_INITIALIZED, {"message": "故事引擎已启动"}))
                tick_result = await _world(app).tick()
                await _broadcast_tick_result(app, tick_result)
                await manager.broadcast(_message(WSMessageType.WORLD_STATE, _world(app).get_frontend_world_state()))
            elif msg_type == WSMessageType.GAME_CONTROL:
                await _handle_game_control(app, msg_data)
            elif msg_type == WSMessageType.PLAYER_INTERVENTION:
                await _handle_player_intervention(ws, app, msg_data)
            elif msg_type == WSMessageType.STORY_ROLLBACK:
                await _handle_story_rollback(ws, msg_data)
            elif msg_type == WSMessageType.TIMELINE_JUMP:
                await _handle_timeline_jump(ws, app, msg_data)
            elif msg_type == WSMessageType.SYNC_REQUEST:
                # 断线重连同步：返回当前完整状态快照
                await _send_initial_state(ws, app)
                await manager.send_to(ws, _message(WSMessageType.WORLD_STATE, _world(app).get_frontend_world_state()))
                await manager.send_to(ws, _message(WSMessageType.STORY_INITIALIZED, {
                    "message": "重连同步完成",
                    "reconnected": True,
                    "last_tick": msg_data.get("lastTick", 0),
                }))
            else:
                await manager.send_to(ws, _message(WSMessageType.SYSTEM_ERROR, {"message": f"未知消息类型: {msg_type}"}))
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception as e:
        logger.exception(f"WebSocket 处理异常: {e}")
        await manager.send_to(ws, _message(WSMessageType.SYSTEM_ERROR, {"message": str(e)}))
        await manager.disconnect(ws)


async def _handle_game_control(app: FastAPI, data: Dict[str, Any]) -> None:
    action = data.get("action", "")
    if action == "pause":
        app.state.story_paused = True
    elif action == "resume":
        app.state.story_paused = False
    await manager.broadcast(_message(WSMessageType.GAME_CONTROL, {
        "action": action,
        "paused": getattr(app.state, "story_paused", False)
    }))


async def _handle_player_intervention(ws: WebSocket, app: FastAPI, data: Dict[str, Any]) -> None:
    if getattr(app.state, "player_intervention_pending", False):
        await manager.send_to(ws, _message(WSMessageType.INTERVENTION_RESULT, {
            "success": False,
            "effectiveness": 0.0,
            "narrative_response": "上一条干预仍在处理中，请稍后再试。",
            "tick": _world(app)._tick_count,
        }))
        return

    cooldown_seconds = 2.0
    last_at = getattr(app.state, "last_intervention_at", 0.0)
    now = time.time()
    remaining = cooldown_seconds - (now - last_at)
    if remaining > 0:
        await manager.send_to(ws, _message(WSMessageType.INTERVENTION_RESULT, {
            "success": False,
            "effectiveness": 0.0,
            "narrative_response": f"干预过于频繁，请 {remaining:.1f} 秒后再试。",
            "cooldown_remaining": remaining,
            "tick": _world(app)._tick_count,
        }))
        return
    app.state.last_intervention_at = now

    intent = _intervention_to_intent(data)

    # 如果自动 tick 未启动，则启动它
    if not getattr(app.state, "tick_started", False):
        app.state.tick_started = True
        _ensure_tick_loop(app)

    # 标记玩家干预进行中——阻止自动 tick 抢锁
    app.state.player_intervention_pending = True
    try:
        tick_result = await _world(app).tick(player_intents=[intent])
    finally:
        app.state.player_intervention_pending = False
        app.state._last_player_tick_time = time.time()

    # 检查 tick 是否被跳过/超时/暂停 —— 不广播虚假成功
    tick_status = tick_result.get("status", "")
    if tick_status in ("skipped", "timeout", "paused", "error"):
        reason = tick_result.get("reason", tick_status)
        await manager.send_to(ws, _message(WSMessageType.INTERVENTION_RESULT, {
            "success": False,
            "effectiveness": 0.0,
            "narrative_response": f"干预未能执行：{reason}",
            "tick": tick_result.get("tick"),
        }))
        return

    await _broadcast_tick_result(app, tick_result)
    await manager.send_to(ws, _message(WSMessageType.INTERVENTION_RESULT, {
        "success": True,
        "effectiveness": tick_result.get("intervention_effectiveness", 1.0),
        "narrative_response": tick_result.get("intervention_narration", "") or "你的干预已经进入世界模拟器。",
        "tick": tick_result.get("tick"),
    }))


async def _handle_story_rollback(ws: WebSocket, data: Dict[str, Any]) -> None:
    """旧版回滚：告知前端使用 timeline:jump 代替。"""
    await manager.send_to(ws, _message(WSMessageType.STORY_ROLLBACK_RESULT, {
        "success": True,
        "current_tick": data.get("target_tick", 0),
        "chapter_id": data.get("chapter_id"),
        "message": "请使用 timeline:jump 消息进行时间线跳转。",
    }))


async def _handle_timeline_jump(ws: WebSocket, app: FastAPI, data: Dict[str, Any]) -> None:
    """时间线跳转：委托给 TimelineHandler（统一实现，避免与 REST 路径重复）。"""
    target_tick = data.get("tick") or data.get("target_tick", 0)
    mode = data.get("mode", "rewrite")

    try:
        from backend.framework.bus import bus
        result = await bus.send(to="timeline", type="jump_to_tick", payload={"tick": target_tick, "mode": mode})
    except Exception as e:
        logger.exception(f"[WebSocket] 时间线跳转失败: {e}")
        await manager.send_to(ws, _message(WSMessageType.TIMELINE_JUMP_RESULT, {
            "success": False,
            "mode": mode,
            "message": f"状态恢复失败: {e}",
        }))
        return

    if result is None:
        await manager.send_to(ws, _message(WSMessageType.TIMELINE_JUMP_RESULT, {
            "success": False,
            "message": "时间线模块未就绪（TimelineHandler 未注册）",
        }))
        return

    if not result.get("success"):
        await manager.send_to(ws, _message(WSMessageType.TIMELINE_JUMP_RESULT, {
            "success": False,
            "mode": mode,
            "message": result.get("message", "跳转失败"),
        }))
        return

    # TimelineHandler 已完成 rewrite restore + 广播 world_state / agent_state；view 不改变后端状态
    await manager.send_to(ws, _message(WSMessageType.TIMELINE_JUMP_RESULT, {
        "success": True,
        "mode": result.get("mode", mode),
        "current_tick": result.get("current_tick", result.get("tick")),
        "target_tick": result.get("tick", target_tick),
        "available_tick": result.get("available_tick"),
        "agent_count": result.get("agent_count"),
        "pruned": result.get("pruned", {}),
        "message": result.get("message") or f"已恢复到 tick {result.get('tick')}",
    }))
    logger.info(f"[WebSocket] 时间线跳转成功: mode={result.get('mode', mode)}, tick={result.get('tick')}")
