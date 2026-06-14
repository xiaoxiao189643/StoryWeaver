# ============================================================
# modules/director/handler.py —— 导演模块消息处理器
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List
from backend.framework.bus import bus
from backend.utils.i18n import cn_weather, cn_emotion


class DirectorHandler:
    def __init__(self, director_service, ground_truth, world_simulator):
        self._director = director_service
        self._ground_truth = ground_truth
        self._world_simulator = world_simulator

    async def handle_init_world(self, payload: Dict) -> Dict:
        world = self._world_simulator
        truth = self._ground_truth.get_truth()
        rooms = [
            {"id": loc.id, "name": loc.name, "description": getattr(loc, "description", ""),
             "width": 800, "height": 600, "connectedTo": getattr(loc, "connected_to", []), "npcs": []}
            for loc in truth.locations.values()
        ] or [{"id": "room-001", "name": "大厅", "width": 800, "height": 600, "npcs": [], "description": "", "connectedTo": []}]
        agents = []
        all_agents = world._agent_runtime.get_all_agents() if world._agent_runtime else {}
        for a in all_agents.values():
            agents.append({
                "id": a.id, "name": a.name, "x": 300, "y": 300,
                "state": a.current_action or "idle", "spriteKey": "npc",
                "emotion": cn_emotion(a.emotion.current_mood) if hasattr(a, 'emotion') and a.emotion else "平静",
                "trustPlayer": getattr(a, "trust_player", 0.0),
            })
        if not agents:
            agents = [{"id": "npc-001", "name": "Alice", "x": 200, "y": 300, "state": "idle", "spriteKey": "npc", "emotion": "平静", "trustPlayer": 0.2}]
        return {"world_state": {"rooms": rooms}, "agents": agents}

    async def handle_get_world_state(self, payload: Dict) -> Dict:
        truth = self._ground_truth.get_truth()
        status = self._director.get_status()
        weather = cn_weather(getattr(truth, "weather", "sunny"))
        current_room_id = getattr(truth, "current_room_id", "hall")
        return {"tick": truth.time.tick, "time": truth.time.model_dump(), "weather": weather, "tension": status.get("tension", 50), "currentRoomId": current_room_id}

    async def handle_get_director_status(self, payload: Dict) -> Dict:
        return self._director.get_status()

    async def handle_get_upcoming_events(self, payload: Dict) -> Dict:
        events = self._director.get_upcoming_events()
        return {"events": events}

    async def handle_get_world_map(self, payload: Dict) -> Dict:
        truth = self._ground_truth.get_truth()
        regions = [{"id": loc.id, "name": loc.name, "description": loc.description} for loc in truth.locations.values()]
        connections = [{"from": loc.id, "to": target, "isPassable": not loc.locked} for loc in truth.locations.values() for target in loc.connected_to]
        return {"regions": regions, "connections": connections}

    async def handle_get_world_timeline(self, payload: Dict) -> List[Dict]:
        limit = int(payload.get("limit", 50))
        truth = self._ground_truth.get_truth()
        events = []
        for i, entry in enumerate(truth.event_log):
            events.append({"tick": i + 1, "event": "world_event", "description": entry, "timestamp": 0})
        for ev in self._director.state.triggered_events:
            events.append({"tick": ev.scheduled_tick, "event": ev.type, "description": ev.description, "timestamp": int(ev.created_at)})
        events.sort(key=lambda e: e["tick"], reverse=True)
        return events[:limit]

    async def handle_world_tick(self, payload: Dict) -> Dict:
        await self._world_simulator.tick(player_intents=payload.get("player_intents"))
        return {"success": True}

    async def handle_request_instruction(self, payload: Dict) -> Dict:
        goal = self._director.state.scene_goal
        base = goal.description if goal else "自然推进剧情"
        agent_id = payload.get("agent_id", "")

        # 阶段目标注入
        phase = payload.get("phase", {})
        phase_goal = phase.get("goal", "")
        phase_deadline = phase.get("deadline", "")
        stagnation = payload.get("stagnation", False)

        # 根据角色身份给出差异化指令
        role_hints = {
            "hostess_su": f"你是女主人苏晚晴。用优雅的言辞掌控局面，暗中观察每个人的反应。{base}",
            "detective_jiang": f"你是侦探江策。用冷静的提问和观察来挖掘线索。不要附和别人，提出你的独立判断。{base}",
            "artist_gu": f"你是画家顾言。用诗意但尖锐的比喻表达观点。你的视角独特，说的话应该和别人不一样。{base}",
            "butler_zhong": f"你是管家钟叔。回答要恭敬但有所保留。你知道很多秘密，但选择性地透露。不要主动建议去书房。{base}",
        }
        instruction = role_hints.get(agent_id, base)

        # 追加阶段目标（来自 PhaseManager 或 phase dict）
        if phase_goal and len(phase_goal) > 10:
            instruction += f"\n\n【阶段叙事指令】\n{phase_goal}"
        elif phase_goal:
            instruction += f" 【本阶段任务：{phase_goal}】"
        if phase_deadline:
            instruction += f" 【截止要求：{phase_deadline}】"
        if stagnation:
            instruction += " 【警告：对话停滞！你必须主动推动剧情，做出与之前不同的行动！】"

        return {"instruction": instruction, "priority": goal.priority if goal else 0}

    async def handle_report_action(self, payload: Dict) -> Dict:
        result = self._director.report_agent_action(
            agent_id=payload.get("agent_id", ""),
            agent_name=payload.get("agent_name", payload.get("actor", "")),
            action_type=payload.get("action_type", payload.get("type", "idle")),
            action=payload.get("action", ""),
            target=payload.get("target", ""),
            dialogue=payload.get("dialogue", ""),
            thought=payload.get("thought", ""),
            emotion=payload.get("emotion", payload.get("emotion_tag", "neutral")),
        )
        return {"success": True, **result}

    async def handle_get_story_chapters(self, payload: Dict) -> List[Dict]:
        return self._director.get_chapters()

    async def handle_get_world_items(self, payload: Dict) -> Dict:
        truth = self._ground_truth.get_truth()
        items = []
        for item in truth.items.values():
            items.append({
                "id": item.id,
                "name": item.name,
                "description": getattr(item, "description", ""),
                "location": getattr(item, "location_id", None),
                "heldBy": getattr(item, "held_by", None),
                "isHidden": getattr(item, "is_hidden", False),
                "isKeyItem": getattr(item, "is_key_item", False),
            })
        return {"items": items}


def register_director_handler(director_service, ground_truth, world_simulator):
    h = DirectorHandler(director_service, ground_truth, world_simulator)
    bus.register("director", {
        "init_world":          h.handle_init_world,
        "get_world_state":     h.handle_get_world_state,
        "get_director_status": h.handle_get_director_status,
        "get_upcoming_events": h.handle_get_upcoming_events,
        "get_world_map":       h.handle_get_world_map,
        "get_world_timeline":  h.handle_get_world_timeline,
        "world_tick":          h.handle_world_tick,
        "request_instruction": h.handle_request_instruction,
        "report_action":       h.handle_report_action,
        "get_world_items":     h.handle_get_world_items,
        "get_story_chapters": h.handle_get_story_chapters,
    })
    return h
