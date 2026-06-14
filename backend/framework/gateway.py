 # ============================================================
# framework/gateway.py —— 前端统一入口
# ============================================================
# 所有前端 HTTP 请求到这里 → 转消息 → bus.send → 返回结果
# 前端不接触任何模块的内部实现。
# ============================================================

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from backend.framework.router import resolve
from backend.framework.bus import bus
from backend.model.dialogue import DialogueRecord

logger = logging.getLogger(__name__)


def ok(data: Any, message: str = "ok") -> Dict[str, Any]:
    return {"code": 0, "data": data, "message": message}


def fail(message: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": 1, "data": None, "message": message})


def _world(app: FastAPI):
    world = getattr(app.state, "world_simulator", None)
    if not world:
        raise RuntimeError("WorldSimulator 尚未初始化")
    return world


def _director_service(app: FastAPI):
    svc = getattr(app.state, "director_service", None)
    if not svc:
        raise RuntimeError("DirectorService 尚未初始化")
    return svc


def _ground_truth(app: FastAPI):
    gt = getattr(app.state, "ground_truth", None)
    if not gt:
        raise RuntimeError("GroundTruthManager 尚未初始化")
    return gt


def _memory_system(app: FastAPI):
    mem = getattr(app.state, "memory_system", None)
    if not mem:
        raise RuntimeError("MemorySystem 尚未初始化")
    return mem


def _dialogue_store(app: FastAPI):
    ds = getattr(app.state, "dialogue_store", None)
    if not ds:
        raise RuntimeError("DialogueStore 尚未初始化")
    return ds


def _relation_store(app: FastAPI):
    rs = getattr(app.state, "relation_store", None)
    if not rs:
        raise RuntimeError("RelationshipStore 尚未初始化")
    return rs


def _story_session(session_id: str, user_prompt: str = "") -> Dict[str, Any]:
    return {
        "id": session_id,
        "title": "雪山别墅谜案",
        "userPrompt": user_prompt or "在封闭别墅中，让多名各怀秘密的角色围绕线索、停电和真相自然演化。",
        "status": "running",
        "background": "暴风雪封住了山路，别墅中的每个人都无法离开。",
        "summary": "侦探、管家、女主人和神秘访客在同一个夜晚被迫面对隐藏已久的秘密。",
    }


# 内存中存储创建的故事会话
_story_sessions_store: Dict[str, Dict[str, Any]] = {
    "default_session": _story_session("default_session", "在封闭别墅中，让多名各怀秘密的角色围绕线索、停电和真相自然演化。"),
}


def _belief_for_frontend(agent_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "agentId": agent_id,
        "knownFacts": data.get("facts", []),
        "suspicions": data.get("suspicions", []),
        "secrets": data.get("secrets", []),
        "misconceptions": data.get("misconceptions", []),
    }


def _player_intent_from_intervention(world_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    target = payload.get("target") or payload.get("target_agent_id") or "all"
    content = payload.get("content") or payload.get("claim") or payload.get("text") or ""
    action = payload.get("action") or payload.get("type") or "persuasion"
    return {
        "type": "speak",
        "actor": "player_01",
        "target": target,
        "action": content or f"玩家发起 {action}",
        "dialogue": content,
        "metadata": {"world_id": world_id, "intervention_type": action},
    }


def setup_gateway(app: FastAPI) -> None:
    """
    给 FastAPI app 注册统一网关路由。
    替换原来手动注册的各个 router。
    """

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/")
    async def root():
        return {"name": "StoryWeaver", "version": "0.2.0"}

    @app.get("/api/v1/ping")
    async def api_v1_ping():
        return {"pong": True}

    # ── 前端接口文档兼容层：包装响应 + /worlds 路径 ──

    @app.get("/worlds/{world_id}/snapshot")
    async def frontend_snapshot(world_id: str):
        try:
            return ok(_world(app).get_frontend_snapshot())
        except Exception as e:
            logger.error(f"前端快照接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/state")
    async def frontend_world_state(world_id: str):
        try:
            state = _world(app).get_frontend_world_state()
            # 补充 weather 字段（API 文档要求）
            if "weather" not in state:
                state["weather"] = "暴风雪"
            # 确保 time 是字符串格式
            if isinstance(state.get("time"), dict):
                state["time"] = str(state["time"])
            return ok(state)
        except Exception as e:
            logger.error(f"前端世界状态接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/agents")
    async def frontend_agent_list(world_id: str):
        try:
            return ok(_world(app).get_frontend_agents())
        except Exception as e:
            logger.error(f"前端 Agent 列表接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/agents/{agent_id}")
    async def frontend_agent_detail(world_id: str, agent_id: str):
        try:
            data = await bus.send(to="character", type="get_agent_detail", payload={"world_id": world_id, "agent_id": agent_id})
            return ok(data)
        except ValueError as e:
            return fail(str(e), status_code=404)
        except Exception as e:
            logger.error(f"前端 Agent 详情接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/agents/{agent_id}/relationships")
    async def frontend_agent_relationships(world_id: str, agent_id: str):
        try:
            data = await bus.send(to="character", type="get_agent_relationships", payload={"world_id": world_id, "agent_id": agent_id})
            return ok(data)
        except Exception as e:
            logger.error(f"前端 Agent 关系接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/agents/{agent_id}/beliefs")
    async def frontend_agent_beliefs(world_id: str, agent_id: str):
        try:
            data = await bus.send(to="character", type="get_agent_belief", payload={"world_id": world_id, "agent_id": agent_id})
            return ok(_belief_for_frontend(agent_id, data or {}))
        except Exception as e:
            logger.error(f"前端 Agent 认知接口失败: {e}")
            return fail(str(e))


    @app.get("/worlds/{world_id}/items")
    async def frontend_world_items(world_id: str):
        try:
            data = await bus.send(
            to="director",                          # 发给导演模块
            type="get_world_items",                 # 自定义消息类型
            payload={"world_id": world_id}
            )
            return ok(data)                             # ✅ 统一返回格式
        except Exception as e:
            logger.error(f"获取物品列表失败: {e}")
        return fail(str(e))
    
    @app.get("/worlds/{world_id}/director/status")
    async def frontend_director_status(world_id: str):
        try:
            return ok(await bus.send(to="director", type="get_director_status", payload={"world_id": world_id}))
        except Exception as e:
            logger.error(f"前端导演状态接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/director/outline")
    async def frontend_director_outline(world_id: str):
        try:
            outline = await bus.send(to="director", type="get_director_outline", payload={"world_id": world_id})
            if not outline:
                outline = {
                    "theme": "悬疑",
                    "background": "暴风雪封住山路的冬夜，别墅中每个人都在隐藏着什么。",
                    "main_conflict": "封闭空间中的信任与背叛",
                    "world_parameters": {},
                }
            return ok(outline)
        except Exception as e:
            logger.error(f"前端导演大纲接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/director/upcoming-events")
    async def frontend_director_upcoming_events(world_id: str):
        try:
            return ok(await bus.send(to="director", type="get_upcoming_events", payload={"world_id": world_id}))
        except Exception as e:
            logger.error(f"前端导演事件接口失败: {e}")
            return fail(str(e))

    @app.get("/worlds/{world_id}/dialogues")
    async def frontend_dialogues(world_id: str, limit: int = 50, cursor: str = ""):
        try:
            data = await bus.send(to="memory", type="memory_dialogue_history", payload={"world_id": world_id, "limit": limit, "cursor": cursor or None})
            return ok(data)
        except Exception as e:
            logger.error(f"前端对话历史接口失败: {e}")
            return fail(str(e))

    @app.post("/worlds/{world_id}/interventions")
    async def frontend_intervention(world_id: str, request: Request):
        try:
            body = await request.json()
            intent = _player_intent_from_intervention(world_id, body)
            tick_result = await _world(app).tick(player_intents=[intent])
            event_id = f"intervene_{uuid.uuid4().hex[:8]}"
            return ok({
                "success": True,
                "message": "干预已注入世界模拟器",
                "eventId": event_id,
            })
        except Exception as e:
            logger.error(f"前端干预接口失败: {e}")
            return fail(str(e))

    @app.get("/story-sessions/{session_id}")
    async def frontend_story_session(session_id: str):
        return ok(_story_session(session_id))

    @app.get("/story-sessions/{session_id}/chapters")
    async def frontend_story_chapters(session_id: str):
        try:
            # 尝试从导演模块获取更真实的章节数据
            data = await bus.send(to="director", type="get_world_timeline", payload={"world_id": "default_world", "limit": 100})
            if data and len(data) > 0:
                # 按 tick 分组为章节（每 30 tick 一个章节）
                chapters = []
                chapter_id = 1
                for i in range(0, len(data), 30):
                    chunk = data[i:i + 30]
                    first = chunk[0]
                    last = chunk[-1]
                    chapters.append({
                        "id": f"chapter_{chapter_id}",
                        "title": f"第{'一二三四五六七八九十'[chapter_id - 1] if chapter_id <= 10 else chapter_id}章",
                        "summary": chunk[0].get("description", "剧情推进中…"),
                        "tick": first.get("tick", 0),
                        "timestamp": first.get("timestamp", ""),
                        "events": [e.get("description", "") for e in chunk],
                    })
                    chapter_id += 1
                return ok(chapters)
        except Exception:
            pass
        # 降级返回默认章节
        return ok([
            {
                "id": "chapter_1",
                "title": "第一章：别墅夜宴",
                "summary": "所有角色抵达别墅，秘密开始浮现。",
                "tick": 0,
                "timestamp": "2025-01-01T20:00:00Z",
                "events": ["角色们陆续抵达别墅", "大厅里的气氛略显紧张"],
            },
            {
                "id": "chapter_2",
                "title": "第二章：停电前兆",
                "summary": "广播与异常事件推动猜疑升级。",
                "tick": 30,
                "timestamp": "2025-01-01T21:00:00Z",
                "events": ["广播系统突然开启", "别墅陷入一片黑暗"],
            },
        ])

    @app.get("/story-sessions/{session_id}/events")
    async def frontend_story_events(session_id: str, limit: int = 50):
        try:
            data = await bus.send(to="director", type="get_world_timeline", payload={"world_id": "default_world", "limit": limit})
            # 标准化为 doc 格式：{ tick, description, timestamp }
            if data and isinstance(data, list):
                normalized = []
                for ev in data:
                    normalized.append({
                        "tick": ev.get("tick", 0),
                        "description": ev.get("description", ev.get("event", "")),
                        "timestamp": ev.get("timestamp", ""),
                    })
                return ok(normalized)
            return ok(data or [])
        except Exception as e:
            logger.error(f"前端故事事件接口失败: {e}")
            return fail(str(e))

    # ═══════════════════════════════════════════════════════════
    # 新增接口：POST /story/sessions — 创建新故事会话
    # ═══════════════════════════════════════════════════════════

    @app.post("/story-sessions")
    async def frontend_create_story_session(request: Request):
        try:
            body = await request.json()
            user_prompt = body.get("user_prompt", "")
            session_id = f"session_{uuid.uuid4().hex[:8]}"
            new_session = _story_session(session_id, user_prompt)
            _story_sessions_store[session_id] = new_session

            # 调用导演模块初始化世界
            try:
                await bus.send(to="director", type="init_world", payload={
                    "world_id": f"world_{session_id[-8:]}",
                    "user_prompt": user_prompt,
                })
            except Exception as e:
                logger.warning(f"初始化世界（非关键）: {e}")

            return ok({
                "session_id": session_id,
                "title": new_session["title"],
                "message": "故事会话已创建",
            })
        except Exception as e:
            logger.error(f"创建故事会话失败: {e}")
            return fail(str(e))


    #初始化世界状态


    # ═══════════════════════════════════════════════════════════
    # 新增接口：GET /story/sessions — 拉取用户历史故事会话列表
    # ═══════════════════════════════════════════════════════════

    @app.get("/story/sessions")
    async def frontend_story_sessions_list(user_id: str = Query("", description="用户 ID（可选）")):
        try:
            sessions = list(_story_sessions_store.values())
            # 按创建时间倒序（暂时按 id 排序）
            sessions.reverse()
            result = [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "userPrompt": s["userPrompt"],
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "isActive": s["status"] == "running",
                }
                for s in sessions
            ]
            return result
        except Exception as e:
            logger.error(f"获取故事会话列表失败: {e}")
            return fail(str(e))

    # ═══════════════════════════════════════════════════════════
    # 新增接口：POST /api/intervene — 玩家文本干预（HTTP 通道）
    # ═══════════════════════════════════════════════════════════

    @app.post("/api/intervene")
    async def api_intervene(request: Request):
        try:
            body = await request.json()
            target = body.get("target", "all")
            action = body.get("action", "persuasion")
            content = body.get("content", "")

            intent = {
                "type": "speak",
                "actor": "player_01",
                "target": target,
                "action": content or f"玩家发起 {action}",
                "dialogue": content,
                "metadata": {"intervention_type": action},
            }

            tick_result = await _world(app).tick(player_intents=[intent])
            event_id = f"intervene_{uuid.uuid4().hex[:8]}"

            return {
                "success": True,
                "message": "干预已注入世界模拟器",
                "eventId": event_id,
            }
        except Exception as e:
            logger.error(f"API 干预接口失败: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": str(e), "eventId": ""},
            )

    @app.get("/users/{user_id}/story-sessions")
    async def frontend_story_sessions(user_id: str):
        return ok(list(_story_sessions_store.values()))

    # ═══════════════════════════════════════════════════════════
    # 导演后端 (Director Backend)
    # ═══════════════════════════════════════════════════════════

    @app.get("/world/state")
    async def director_world_state(world_id: str = Query("", description="世界ID")):
        """获取宏观世界状态"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="director", type="get_world_state", payload={"world_id": wid})
            if not data:
                gt = _ground_truth(app)
                truth = gt.get_truth()
                data = {
                    "tick": truth.time.tick if hasattr(truth.time, "tick") else 0,
                    "time": truth.time.model_dump() if hasattr(truth.time, "model_dump") else {},
                    "weather": getattr(truth, "weather", "晴朗"),
                    "tension": 0,
                }
            return data
        except Exception as e:
            logger.error(f"导演世界状态接口失败: {e}")
            return {"tick": 0, "time": {}, "weather": "晴朗", "tension": 0}

    @app.get("/director/outline")
    async def director_outline(world_id: str = Query("", description="世界ID")):
        """获取世界背景设定"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="director", type="get_director_outline", payload={"world_id": wid})
            if not data:
                data = {
                    "theme": "悬疑",
                    "background": "暴风雪封住山路的冬夜，别墅中每个人都在隐藏着什么。",
                    "main_conflict": "封闭空间中的信任与背叛",
                    "world_parameters": {},
                }
            return ok(data)
        except Exception as e:
            logger.error(f"导演大纲接口失败: {e}")
            return fail(str(e))

    @app.get("/director/status")
    async def director_status(world_id: str = Query("", description="世界ID")):
        """获取导演运行调控指标"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="director", type="get_director_status", payload={"world_id": wid})
            if not data:
                data = {
                    "tension": 0,
                    "target": "平稳推进",
                    "phase": "开端",
                    "narrativeStage": "故事刚刚开始，角色们正在熟悉环境。",
                    "intensity": 0.0,
                }
            return data
        except Exception as e:
            logger.error(f"导演状态接口失败: {e}")
            return {"tension": 0, "target": "平稳推进", "phase": "开端", "narrativeStage": "", "intensity": 0.0}

    @app.get("/director/upcoming_events")
    async def director_upcoming_events(world_id: str = Query("", description="世界ID")):
        """获取未来即将爆出的剧情伏笔队列"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="director", type="get_upcoming_events", payload={"world_id": wid})
            return data or []
        except Exception as e:
            logger.error(f"导演即将事件接口失败: {e}")
            return []

    @app.get("/director/agent/{agent_id}")
    async def director_agent_detail(agent_id: str, world_id: str = Query("", description="世界ID")):
        """获取NPC完整设定（导演视角）"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="director", type="get_director_agent", payload={"world_id": wid, "agent_id": agent_id})
            if not data:
                return fail(f"Agent {agent_id} 不存在", status_code=404)
            # 标准化为文档格式
            return ok({
                "id": data.get("agent_id", agent_id),
                "name": data.get("name", ""),
                "personality": data.get("personality", ""),
                "goal": (data.get("goals") or [""])[0] if data.get("goals") else "",
                "trust_player": data.get("trust_player", 0),
                "emotion": data.get("emotion", "neutral"),
                "motivation": data.get("motivation", ""),
            })
        except Exception as e:
            logger.error(f"导演 Agent 详情接口失败: {e}")
            return fail(str(e))

    @app.get("/director/agent/{agent_id}/scene")
    async def director_agent_scene(agent_id: str, world_id: str = Query("", description="世界ID")):
        """获取NPC当前所在位置"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="director", type="get_director_agent_scene", payload={"world_id": wid, "agent_id": agent_id})
            if not data:
                return fail(f"Agent {agent_id} 场景不存在", status_code=404)
            return ok({"scene": data.get("location_name", data.get("location_id", ""))})
        except Exception as e:
            logger.error(f"导演 Agent 场景接口失败: {e}")
            return fail(str(e))

    # ═══════════════════════════════════════════════════════════
    # 角色后端 (Character Backend)
    # ═══════════════════════════════════════════════════════════

    @app.get("/agent/list")
    async def character_agent_list(world_id: str = Query("", description="世界/剧本ID")):
        """获取NPC列表"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="character", type="get_agent_list", payload={"world_id": wid})
            return data or []
        except Exception as e:
            logger.error(f"角色列表接口失败: {e}")
            return []

    @app.get("/agent/{agent_id}")
    async def character_agent_detail(agent_id: str, world_id: str = Query("", description="世界/剧本ID")):
        """获取NPC详情"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="character", type="get_agent_detail", payload={"world_id": wid, "agent_id": agent_id})
            return data or {}
        except Exception as e:
            logger.error(f"角色详情接口失败: {e}")
            return {}

    @app.get("/agent/{agent_id}/relationships")
    async def character_agent_relationships(agent_id: str, world_id: str = Query("", description="世界/剧本ID")):
        """获取NPC关系网"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="character", type="get_agent_relationships", payload={"world_id": wid, "agent_id": agent_id})
            return data or {"agent_id": agent_id, "relationships": []}
        except Exception as e:
            logger.error(f"角色关系网接口失败: {e}")
            return {"agent_id": agent_id, "relationships": []}

    @app.get("/agent/{agent_id}/belief")
    async def character_agent_belief(agent_id: str, world_id: str = Query("", description="NPC ID")):
        """获取NPC认知"""
        try:
            wid = world_id or "default_world"
            data = await bus.send(to="character", type="get_agent_belief", payload={"world_id": wid, "agent_id": agent_id})
            return data or {"facts": [], "suspicions": [], "secrets": [], "misconceptions": []}
        except Exception as e:
            logger.error(f"角色认知接口失败: {e}")
            return {"facts": [], "suspicions": [], "secrets": [], "misconceptions": []}

    @app.post("/agent/{agent_id}/belief")
    async def character_write_agent_belief(agent_id: str, request: Request, world_id: str = Query("", description="世界/剧本ID")):
        """修改NPC认知"""
        try:
            wid = world_id or "default_world"
            body = await request.json()
            payload = {"world_id": wid, "agent_id": agent_id, **body}
            result = await bus.send(to="character", type="write_agent_belief", payload=payload)
            return result or {"success": True, "message": "认知已更新"}
        except Exception as e:
            logger.error(f"写入角色认知接口失败: {e}")
            return {"success": False, "message": str(e)}

    @app.post("/memory/event/from-agent")
    async def character_report_agent_event(request: Request):
        """上报角色行动事件"""
        try:
            body = await request.json()
            result = await bus.send(to="character", type="report_agent_event", payload=body)
            return result or {"success": True, "event_id": ""}
        except Exception as e:
            logger.error(f"上报角色事件接口失败: {e}")
            return {"success": False, "event_id": ""}

    # ═══════════════════════════════════════════════════════════
    # 记忆后端 (Memory Backend)
    # ═══════════════════════════════════════════════════════════

    @app.post("/memory/add")
    async def memory_add(request: Request):
        """添加记忆"""
        try:
            body = await request.json()
            agent_id = body.get("agent_id", "__global__")
            content = body.get("content", "")
            importance = body.get("importance", 0.5)
            emotion_tag = body.get("emotion_tag", "neutral")
            tick = body.get("tick", 0)
            world_id = body.get("world_id", "default_world")

            # 尝试通过 bus 发送
            result = await bus.send(to="memory", type="memory_add", payload=body)
            if result:
                return ok({
                    "ok": True,
                    "world_id": world_id,
                    "agent_id": agent_id,
                    "scope": body.get("scope", "agent"),
                    "memory": {
                        "id": result.get("memory_id", f"mem_{uuid.uuid4().hex[:8]}"),
                        "tick": tick,
                        "content": content,
                        "importance": importance,
                        "emotion_tag": emotion_tag,
                        "metadata": body.get("metadata", {}),
                    },
                })
            # 降级：直接用 memory_system
            from backend.model.agent import MemoryEntry
            entry = MemoryEntry(
                id=f"mem_{uuid.uuid4().hex[:8]}",
                tick=tick,
                content=content,
                importance=importance,
                emotion_tag=emotion_tag,
            )
            _memory_system(app).add_short_term(agent_id, entry)
            return ok({
                "ok": True,
                "world_id": world_id,
                "agent_id": agent_id,
                "scope": body.get("scope", "agent"),
                "memory": {
                    "id": entry.id,
                    "tick": tick,
                    "content": content,
                    "importance": importance,
                    "emotion_tag": emotion_tag,
                    "metadata": body.get("metadata", {}),
                },
            })
        except Exception as e:
            logger.error(f"添加记忆接口失败: {e}")
            return fail(str(e))

    @app.get("/memory/recent")
    async def memory_get_recent(
        world_id: str = Query("", description="世界ID"),
        agent_id: str = Query("", description="角色ID"),
        limit: int = Query(10, description="返回数量"),
        include_global: bool = Query(True, description="是否包含全局记忆"),
    ):
        """获取最近记忆"""
        try:
            # 尝试通过 bus
            result = await bus.send(to="memory", type="memory_get_recent", payload={
                "world_id": world_id, "agent_id": agent_id, "limit": limit, "include_global": include_global,
            })
            if result:
                memories = result.get("memories", [])
                fmt_memories = []
                for m in memories:
                    fmt_memories.append({
                        "id": m.get("id", ""),
                        "tick": m.get("tick", 0),
                        "content": m.get("content", ""),
                        "importance": m.get("importance", 0.5),
                        "emotion_tag": m.get("emotion_tag", m.get("emotion", "neutral")),
                        "scope": m.get("type", "agent"),
                    })
                return ok({
                    "world_id": world_id,
                    "agent_id": agent_id,
                    "include_global": include_global,
                    "memories": fmt_memories,
                })
            # 降级
            raw = _memory_system(app).get_recent(agent_id, limit)
            memories = []
            for m in raw:
                memories.append({
                    "id": m.id if hasattr(m, "id") else "",
                    "tick": m.tick if hasattr(m, "tick") else 0,
                    "content": m.content if hasattr(m, "content") else str(m),
                    "importance": m.importance if hasattr(m, "importance") else 0.5,
                    "emotion_tag": m.emotion_tag if hasattr(m, "emotion_tag") else "neutral",
                    "scope": "agent",
                })
            return ok({
                "world_id": world_id,
                "agent_id": agent_id,
                "include_global": include_global,
                "memories": memories,
            })
        except Exception as e:
            logger.error(f"获取最近记忆接口失败: {e}")
            return ok({"world_id": world_id, "agent_id": agent_id, "include_global": include_global, "memories": []})

    @app.get("/memory/search")
    async def memory_search(
        world_id: str = Query(..., description="世界ID"),
        agent_id: str = Query(..., description="角色ID"),
        query: str = Query(..., description="搜索关键词"),
        limit: int = Query(10, description="返回数量"),
    ):
        """搜索记忆"""
        try:
            result = await bus.send(to="memory", type="memory_search", payload={
                "world_id": world_id, "agent_id": agent_id, "query": query, "limit": limit,
            })
            if result:
                return result
            return {"world_id": world_id, "agent_id": agent_id, "query": query, "memories": []}
        except Exception as e:
            logger.error(f"搜索记忆接口失败: {e}")
            return {"world_id": world_id, "agent_id": agent_id, "query": query, "memories": []}

    @app.post("/memory/dialogue/add")
    async def memory_dialogue_add(request: Request):
        """记录对话历史"""
        try:
            body = await request.json()
            world_id = body.get("world_id", "default_world")
            speaker_id = body.get("speaker_id", "")
            content = body.get("content", "")
            tick = body.get("tick", 0)
            metadata = body.get("metadata", {})

            record = DialogueRecord(
                id=f"dialogue_{uuid.uuid4().hex[:8]}",
                world_id=world_id,
                speaker_id=speaker_id,
                speaker_name=body.get("speaker_name", ""),
                content=content,
                timestamp=datetime.now(timezone.utc).isoformat(),
                target_id=body.get("listener_id"),
            )
            _dialogue_store(app).append(record)

            return {
                "ok": True,
                "world_id": world_id,
                "dialogue": {
                    "id": record.id,
                    "tick": tick,
                    "speaker_id": speaker_id,
                    "listener_id": body.get("listener_id"),
                    "content": content,
                    "metadata": metadata,
                },
            }
        except Exception as e:
            logger.error(f"添加对话历史接口失败: {e}")
            return {"ok": False, "world_id": "", "dialogue": {}}

    @app.get("/memory/dialogue/list")
    async def memory_dialogue_list(
        world_id: str = Query(..., description="世界ID"),
        agent_id: str = Query("", description="查询与该角色有关的对话"),
        other_agent_id: str = Query("", description="查询另一个相关角色"),
        limit: int = Query(50, description="返回数量"),
    ):
        """获取对话历史"""
        try:
            records, has_more = _dialogue_store(app).get_history(
                world_id, limit=limit, cursor=None
            )
            dialogues = []
            for r in records:
                # 如果有 agent_id 过滤
                if agent_id and r.speaker_id != agent_id and r.target_id != agent_id:
                    continue
                if other_agent_id and r.speaker_id != other_agent_id and r.target_id != other_agent_id:
                    continue
                dialogues.append({
                    "id": r.id,
                    "tick": 0,
                    "speaker_id": r.speaker_id,
                    "listener_id": r.target_id,
                    "content": r.content,
                    "metadata": {},
                })
            return {
                "world_id": world_id,
                "dialogues": dialogues,
            }
        except Exception as e:
            logger.error(f"获取对话历史列表接口失败: {e}")
            return {"world_id": world_id, "dialogues": []}

    @app.patch("/memory/relationship/update")
    async def memory_relationship_update(request: Request):
        """更新角色关系"""
        try:
            body = await request.json()
            world_id = body.get("world_id", "default_world")
            agent_a = body.get("agent_a", "")
            agent_b = body.get("agent_b", "")

            # 尝试通过 bus
            bus_result = await bus.send(to="memory", type="memory_relationship_update", payload={
                "world_id": world_id,
                "agent_id": agent_a,
                "target_id": agent_b,
                **{k: v for k, v in body.items() if k in ("trust", "familiarity", "sentiment", "last_interaction_tick")},
            })
            if bus_result:
                return {
                    "ok": True,
                    "world_id": world_id,
                    "relationship": {
                        "agent_a": agent_a,
                        "agent_b": agent_b,
                        "trust": body.get("trust", 0.0),
                        "familiarity": body.get("familiarity", 0.0),
                        "sentiment": body.get("sentiment", 0.0),
                        "last_interaction_tick": body.get("last_interaction_tick", 0),
                    },
                }

            # 降级：直接使用 relation_store
            delta = body.get("trust", 0.0) if "trust" in body else 0.0
            _relation_store(app).update(agent_a, agent_b, delta=delta, reason="玩家干预/系统更新")
            return {
                "ok": True,
                "world_id": world_id,
                "relationship": {
                    "agent_a": agent_a,
                    "agent_b": agent_b,
                    "trust": body.get("trust", 0.0),
                    "familiarity": body.get("familiarity", 0.0),
                    "sentiment": body.get("sentiment", 0.0),
                    "last_interaction_tick": body.get("last_interaction_tick", 0),
                },
            }
        except Exception as e:
            logger.error(f"更新角色关系接口失败: {e}")
            return {"ok": False, "world_id": "", "relationship": {}}

    @app.post("/memory/rollback")
    async def memory_rollback(request: Request):
        """回滚记忆"""
        try:
            body = await request.json()
            world_id = body.get("world_id", "default_world")
            tick = body.get("tick", 0)
            agent_id = body.get("agent_id")
            include_dialogue = body.get("include_dialogue_history", True)

            # 尝试通过 bus
            result = await bus.send(to="memory", type="memory_rollback", payload=body)
            if result:
                return result

            # 降级
            mem_sys = _memory_system(app)
            deleted_memories = 0
            if agent_id:
                # 清除该 agent 的所有短期记忆
                old = mem_sys.get_recent(agent_id, 1000)
                for m in old:
                    if hasattr(m, "tick") and m.tick > tick:
                        deleted_memories += 1
            else:
                for aid in list(getattr(mem_sys, "_short_term", {}).keys()):
                    old = mem_sys.get_recent(aid, 1000)
                    for m in old:
                        if hasattr(m, "tick") and m.tick > tick:
                            deleted_memories += 1

            deleted_dialogues = 0
            if include_dialogue:
                ds = _dialogue_store(app)
                #  DialogueStore 需要支持按 tick 删除
                try:
                    from backend.modules.memory.dialogue_store import DialogueStore
                    if hasattr(ds, "delete_after_tick"):
                        deleted_dialogues = ds.delete_after_tick(world_id, tick)
                except Exception:
                    pass

            return {
                "ok": True,
                "world_id": world_id,
                "rollback_tick": tick,
                "agent_id": agent_id,
                "deleted_memories": deleted_memories,
                "deleted_dialogues": deleted_dialogues,
            }
        except Exception as e:
            logger.error(f"回滚记忆接口失败: {e}")
            return {"ok": False, "world_id": "", "rollback_tick": 0, "agent_id": None, "deleted_memories": 0, "deleted_dialogues": 0}

    # ── 统一 API 网关 ──
    # 所有 /api/v1/* 请求走这里，按路径+方法分发到对应模块

    @app.api_route("/api/v1/{rest_of_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def api_gateway(request: Request, rest_of_path: str = ""):
        method = request.method
        path = "/" + rest_of_path

        # 解析路由
        to_module, msg_type, path_params = resolve(method, path)

        if to_module is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"未找到路由: {method} {path}"},
            )

        # 组装 payload：query 参数 + 路径参数
        payload: Dict[str, Any] = dict(request.query_params)
        payload.update(path_params)

        # POST body
        if method in ("POST", "PUT") and request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
                payload.update(body)
            except Exception:
                pass

        # 通过 bus 发给目标模块
        try:
            result = await bus.send(to=to_module, type=msg_type, payload=payload)
            return result if result is not None else {}
        except ValueError as e:
            return JSONResponse(status_code=404, content={"detail": str(e)})
        except Exception as e:
            logger.error(f"网关错误: {method} {path} → {to_module}.{msg_type}: {e}")
            return JSONResponse(status_code=500, content={"detail": str(e)})

    # ── api/init 特殊路由（GET query 参数） ──
    @app.get("/api/init")
    async def api_init(world_id: str = "default_world"):
        try:
            # 导演模块：获取世界基础状态 + Agent 列表
            init_data = await bus.send(to="director", type="init_world", payload={"world_id": world_id})
            world_state = init_data.get("world_state", {})
            agents = init_data.get("agents", [])

            # 记忆模块：获取对话历史（标准化为文档格式）
            try:
                dialogue_data = await bus.send(to="memory", type="memory_dialogue_history", payload={"world_id": world_id, "limit": 50})
                raw_messages = (dialogue_data or {}).get("messages", [])
                dialogue_history = []
                for msg in raw_messages:
                    dialogue_history.append({
                        "id": msg.get("id", ""),
                        "speakerId": msg.get("speaker_id", msg.get("speakerId", "")),
                        "speakerName": msg.get("speaker_name", msg.get("speakerName", "")),
                        "thought": msg.get("thought", ""),
                        "content": msg.get("content", ""),
                        "emotion": msg.get("emotion", msg.get("emotion_tag", "neutral")),
                    })
            except Exception:
                dialogue_history = []

            # 导演模块：获取事件时间轴（标准化为文档格式）
            try:
                raw_events = await bus.send(to="director", type="get_world_timeline", payload={"world_id": world_id, "limit": 50})
                events = []
                for ev in (raw_events or []):
                    events.append({
                        "tick": str(ev.get("tick", 0)),
                        "description": ev.get("description", ev.get("event", "")),
                        "timestamp": ev.get("timestamp", ""),
                    })
            except Exception:
                events = []

            # 标准化 agents 字段名
            normalized_agents = []
            for a in agents:
                normalized_agents.append({
                    "id": a.get("id", ""),
                    "name": a.get("name", ""),
                    "state": a.get("state", a.get("current_action", "idle")),
                    "emotion": a.get("emotion", "neutral"),
                })

            return {
                "world_state": world_state,
                "agents": normalized_agents,
                "dialogue_history": dialogue_history,
                "events": events,
            }
        except Exception as e:
            logger.error(f"API init 接口失败: {e}")
            return {"world_state": {}, "agents": [], "dialogue_history": [], "events": []}

    logger.info("[Gateway] 网关已注册")
