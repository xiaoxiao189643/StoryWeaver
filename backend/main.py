# ============================================================
# main.py —— 项目主入口（框架化 v0.2）
# ============================================================
# 所有请求统一走 framework/gateway → bus → 模块 handler。
# 不再手动注册各模块的 HTTP router。
# ============================================================

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.config import settings
from backend.framework.gateway import setup_gateway
from backend.modules.director.handler import register_director_handler
from backend.modules.memory.handler import register_memory_handler
from backend.modules.llm.handler import register_llm_handler
from backend.modules.character.handler import CharacterHandler
from backend.framework.bus import bus
from backend.framework.event_bus import global_event_bus

from backend.engine.world_simulator import WorldSimulator
from backend.engine.ground_truth import GroundTruthManager
from backend.modules.character.belief_system import BeliefSystem
from backend.modules.character.player_influence import PlayerInfluenceSystem
from backend.modules.memory.memory_system import MemorySystem
from backend.modules.director.director_service import DirectorService
from backend.modules.memory.relation_store import RelationshipStore
from backend.modules.memory.dialogue_store import DialogueStore
from backend.storage.dialogue_store import ChapterDialogueStore
from backend.modules.character.runtime import CharacterRuntime
from backend.model.agent import AgentState, Personality, EmotionalState, Goal
from backend.model.world import Location, Item
from backend.modules.narrative.story_state import StoryState, Clue
from backend.modules.narrative.logic_validator import LogicValidator
from backend.modules.narrative.plot_manager import PlotManager
from backend.utils.i18n import cn_emotion

# ── 日志 ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _init_demo_scene(gt, director, world):
    locations = [
        Location(id="hall", name="大厅", description="宽敞的入口大厅，摆着一架古老的落地钟", locked=False, connected_to=["study", "kitchen", "garden"]),
        Location(id="study", name="书房", description="昏暗的书房，书架上摆满了泛黄的典籍", locked=False, connected_to=["hall", "cellar"]),
        Location(id="kitchen", name="厨房", description="散发着食物香气的厨房，刀具整齐排列", locked=False, connected_to=["hall", "garden"]),
        Location(id="garden", name="花园", description="月光下的花园，远处传来水声", locked=False, connected_to=["hall", "kitchen"]),
        Location(id="cellar", name="地窖", description="阴冷潮湿的地窖，门上挂着一把锁", locked=True, connected_to=["study"]),
    ]
    for loc in locations: gt.add_location(loc)
    items = [
        Item(id="clock", name="落地钟", description="指针停在午夜12点", location_id="hall"),
        Item(id="letter", name="神秘信件", description="信封上没有署名", location_id="study"),
        Item(id="knife", name="厨刀", description="刀刃上有可疑的污渍", location_id="kitchen"),
        Item(id="key", name="地窖钥匙", description="生锈的铁钥匙", location_id="garden"),
    ]
    for item in items: gt.add_item(item)

    secret_keys = ["victim_identity", "murderer_identity", "motive", "cellar_secret"]
    scheduled_events = [
        {"tick": 10, "type": "broadcast", "description": "别墅的广播系统突然开启，播放了一段诡异的音乐"},
        {"tick": 30, "type": "blackout", "description": "别墅突然全部停电，陷入一片黑暗"},
        {"tick": 60, "type": "murder", "description": "一声惊叫从书房传来……"},
    ]

    background = "一座孤立的暴雪山庄，暴风雪切断了所有通讯和退路。女主人召集了几位客人，没人知道真正原因。暗处隐藏着不可告人的秘密。"

    # 固定角色阵容（暴雪山庄悬疑剧）
    agents_data = [
        {"id": "hostess_su", "name": "苏晚晴", "location_id": "hall",
         "trust_player": 0.15,
         "personality": {"core_description": "苏晚晴是这座雪山别墅的女主人，三十五岁，优雅从容，心思缜密。丈夫三年前离奇失踪后，她独自管理着偌大的家业。说话温婉有礼，但字里行间总透着不容置疑的掌控力。她邀请众人来别墅的原因成谜。",
         "traits": {"openness": 0.5, "conscientiousness": 0.9, "extraversion": 0.6, "agreeableness": 0.4, "neuroticism": 0.3}},
         "emotion": {"current_mood": "冷静", "intensity": 0.3},
         "goals": [{"id": "g1", "description": "查明丈夫失踪的真相", "priority": 10, "is_active": True},
                   {"id": "g2", "description": "在客人面前维持体面与掌控", "priority": 7, "is_active": True}]},
        {"id": "detective_jiang", "name": "江策", "location_id": "study",
         "trust_player": -0.2,
         "personality": {"core_description": "江策，四十二岁，前刑警，因一桩旧案被调离一线，如今以私家侦探身份接受委托。性格沉稳寡言，观察力极强，习惯在暗处审视每个人的微表情和小动作。对苏晚晴的邀请始终保持警惕。",
         "traits": {"openness": 0.7, "conscientiousness": 0.9, "extraversion": 0.2, "agreeableness": 0.3, "neuroticism": 0.2}},
         "emotion": {"current_mood": "怀疑", "intensity": 0.5},
         "goals": [{"id": "g1", "description": "调查暴雪山庄隐藏的秘密", "priority": 9, "is_active": True},
                   {"id": "g2", "description": "保护无辜者不受伤害", "priority": 8, "is_active": True}]},
        {"id": "artist_gu", "name": "顾言", "location_id": "garden",
         "trust_player": 0.25,
         "personality": {"core_description": "顾言，二十八岁，年轻油画家，苏晚晴亡夫的远房表弟。性格外放张扬，言辞犀利，爱用诗意的比喻表达尖锐的观点。他声称是受邀来小住采风，但似乎对别墅的结构和秘密通道异常熟悉。",
         "traits": {"openness": 0.9, "conscientiousness": 0.3, "extraversion": 0.8, "agreeableness": 0.2, "neuroticism": 0.7}},
         "emotion": {"current_mood": "兴奋", "intensity": 0.6},
         "goals": [{"id": "g1", "description": "找到表哥留下的遗物或隐藏的画作", "priority": 9, "is_active": True},
                   {"id": "g2", "description": "用艺术家的直觉解读每个人隐藏的情绪", "priority": 5, "is_active": True}]},
        {"id": "butler_zhong", "name": "钟叔", "location_id": "kitchen",
         "trust_player": 0.05,
         "personality": {"core_description": "钟叔，六十岁，在苏家服务了四十年，看着苏晚晴长大。表面恭敬顺从，实则心思深沉。他知道的秘密切片太多，但三十年来养成的忠诚让他选择沉默。说话慢条斯理，语气谦卑却从不真正回答问题。",
         "traits": {"openness": 0.2, "conscientiousness": 0.9, "extraversion": 0.3, "agreeableness": 0.6, "neuroticism": 0.5}},
         "emotion": {"current_mood": "紧张", "intensity": 0.5},
         "goals": [{"id": "g1", "description": "守住苏家的秘密，不让外人窥探", "priority": 10, "is_active": True},
                   {"id": "g2", "description": "暗中观察江策，判断他是否会威胁苏家", "priority": 7, "is_active": True}]},
    ]

    valid_location_ids = {loc.id for loc in locations}
    for a in agents_data:
        loc_id = a.get("location_id", "hall")
        if loc_id not in valid_location_ids:
            loc_id = locations[0].id
        personality_data = a.get("personality", {})
        emotion_data = a.get("emotion", {})
        raw_traits = personality_data.get("traits", {}) or {}
        # LLM 可能返回 0-1 或 0-100，统一归一化到 0-1
        clamped_traits = {}
        if raw_traits:
            vals = [float(v) for v in raw_traits.values()]
            scale = 100.0 if max(vals) > 10 else 1.0
            clamped_traits = {k: max(0.0, min(1.0, float(v) / scale)) for k, v in raw_traits.items()}
            logger.info(f"性格归一化: raw={raw_traits} -> scale={scale} -> {clamped_traits}")
        agent = AgentState(
            id=a.get("id", ""), name=a.get("name", ""),
            location_id=loc_id,
            trust_player=a.get("trust_player", 0.0),
            current_action=a.get("current_action", "idle"),
            personality=Personality(
                core_description=personality_data.get("core_description", ""),
                **({"traits": clamped_traits} if clamped_traits else {}),
            ),
            emotion=EmotionalState(
                current_mood=emotion_data.get("current_mood", "平静"),
                intensity=emotion_data.get("intensity", 0.5),
            ),
            goals=[Goal(**g) for g in a.get("goals", [])],
        )
        world.register_agent(agent)

    # 将初始信任值同步到 PlayerInfluenceSystem（仅首次启动，避免覆盖已有存档）
    if hasattr(world, '_player_influence') and world._player_influence:
        if not world._player_influence._influences:
            for a in agents_data:
                tp = a.get("trust_player", 0.0)
                world._player_influence.get_influence(a["id"]).trust = tp
            world._player_influence.save()

    director.initialize(start_tick=0,
        secret_keys=secret_keys,
        scheduled_events=[
            {"type": "broadcast", "tick": 10, "description": "别墅的广播系统突然开启，播放了一段诡异的音乐", "affected_locations": [], "priority": 1},
            {"type": "blackout", "tick": 30, "description": "别墅突然全部停电，陷入一片黑暗", "affected_locations": ["hall", "study", "kitchen"], "priority": 3},
            {"type": "murder", "tick": 60, "description": "一声惊叫从书房传来……", "affected_locations": ["study"], "priority": 5, "metadata": {"location": "study"}},
        ])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("StoryWeaver v0.2 — 框架化架构启动中...")
    logger.info("=" * 60)

    # 1. 初始化所有服务
    sd = settings.STORAGE_DIR
    gt = GroundTruthManager()
    bs = BeliefSystem(sd)
    pi = PlayerInfluenceSystem(sd)
    mem = MemorySystem(sd)
    rel_store = RelationshipStore(sd)
    dl_store = DialogueStore(sd)                # 旧存储（保留兼容，逐步迁移）
    ch_dl_store = ChapterDialogueStore(sd)      # 新统一章节对话存储
    chr_runtime = CharacterRuntime()
    chr_handler = CharacterHandler(runtime=chr_runtime, belief_system=bs, memory_system=mem,
                                   relation_store=rel_store, dialogue_store=dl_store, event_bus=global_event_bus)

    world = WorldSimulator(gt, bs, pi, mem)
    world.set_chapter_dialogue_store(ch_dl_store)  # 注入统一章节对话存储
    world._dialogue_store = dl_store            # 旧存储（供快照恢复兼容）
    director = DirectorService(gt, bs)
    world.set_director(director)
    world.set_character_runtime(chr_runtime)

    # ── 叙事逻辑层 ──
    story_state = StoryState()
    story_state.init_characters(["hostess_su", "detective_jiang", "artist_gu", "butler_zhong"])
    for sid, desc in [("victim_identity", "受害者的真实身份"), ("murderer_identity", "凶手的身份"),
                       ("motive", "作案的动机"), ("cellar_secret", "地窖中隐藏的秘密")]:
        story_state.register_secret(sid, desc)
    plot_manager = PlotManager(story_state)
    validator = LogicValidator(story_state)
    world.set_narrative_layer(story_state, plot_manager, validator)
    register_llm_handler()

    # ── 时间线模块 ──
    from backend.timeline import TimelineStore, register_timeline_handler
    from backend.timeline.snapshot import restore_from_snapshot
    timeline_store = TimelineStore(sd)
    world.set_timeline_store(timeline_store)
    director.set_timeline_store(timeline_store)
    director.set_dialogue_store(ch_dl_store)
    tl_handler = register_timeline_handler(timeline_store, world, director)
    logger.info("[Timeline] 时间线模块已注册")

    # ── 检测已有快照：选最新且含角色数据的快照自动恢复 ──
    snapshot_ticks = timeline_store.list_snapshots()
    restored_from_snapshot = False

    if snapshot_ticks:
        # 从最新快照往前找第一个含 agents 的有效快照
        import json as _json
        valid_tick = None
        valid_data = None
        for t in reversed(snapshot_ticks):
            data = timeline_store.load_snapshot(t)
            if data:
                agents = data.get("agents", {})
                if isinstance(agents, dict) and len(agents) > 0:
                    valid_tick = t
                    valid_data = data
                    break

        if valid_data:
            logger.info(
                f"[启动] 检测到 {len(snapshot_ticks)} 个快照，"
                f"选用 tick={valid_tick}（含 {len(valid_data.get('agents', {}))} 个角色）"
            )
            try:
                from backend.engine.agent_runtime import AgentRuntime
                if world._agent_runtime is None:
                    world._agent_runtime = AgentRuntime({})
                result = await restore_from_snapshot(world, director, mem, valid_data)
                logger.info(f"[启动] 快照恢复成功: tick={result.get('tick')}, agents={result.get('agent_count')}")
                restored_from_snapshot = True

                # 修复旧快照中所有角色信任值相同的问题
                if hasattr(world, '_player_influence') and world._player_influence:
                    trusts = [inf.trust for inf in world._player_influence._influences.values()]
                    if len(trusts) >= 2 and len(set(round(t, 4) for t in trusts)) == 1:
                        logger.info("[启动] 检测到旧快照中信任值全相同，重新种子差异化信任值")
                        seed_trust = {
                            "hostess_su": 0.15, "detective_jiang": -0.2,
                            "artist_gu": 0.25, "butler_zhong": 0.05,
                        }
                        for aid, tp in seed_trust.items():
                            if aid in world._player_influence._influences:
                                world._player_influence._influences[aid].trust = tp
                        world._player_influence.save()
            except Exception as e:
                logger.error(f"[启动] 快照恢复失败: {e}，回退到初始化演示场景")
        else:
            logger.warning(f"[启动] {len(snapshot_ticks)} 个快照中无有效角色数据，回退到初始化演示场景")

    if not restored_from_snapshot:
        # 示例场景（LLM 生成角色，world.register_agent 自动同步到 CharacterRuntime）
        await _init_demo_scene(gt, director, world)

        # 为初始章节创建时间线节点 + 同步到统一对话存储
        for ch in director._chapters:
            timeline_store.add_node({
                "node_id": ch.id,
                "tick": ch.start_tick,
                "title": ch.title,
                "summary": ch.summary or "",
                "tension": ch.tension,
                "key_events": ch.key_events or [],
            })
            ch_dl_store.start_chapter(ch.id, ch.start_tick)

    # 注册其余模块 handler 到 bus
    register_director_handler(director, gt, world)
    register_memory_handler(mem, rel_store, dl_store)
    bus.register("character", {
        "get_agent_list": chr_handler.handle_get_agent_list,
        "get_agent_detail": chr_handler.handle_get_agent_detail,
        "get_agent_relationships": chr_handler.handle_get_agent_relationships,
        "get_agent_belief": chr_handler.handle_get_agent_belief,
        "write_agent_belief": chr_handler.handle_write_agent_belief,
        "get_dialogue_history": chr_handler.handle_get_dialogue_history,
        "report_agent_event": chr_handler.handle_report_agent_event,
        "debug_tick": chr_handler.handle_debug_tick,
    })

    # 3. 启动 world
    await world.start()

    # 4. 暴露运行时上下文给 framework gateway / websocket
    app.state.ground_truth = gt
    app.state.belief_system = bs
    app.state.player_influence = pi
    app.state.memory_system = mem
    app.state.relationship_store = rel_store
    app.state.dialogue_store = dl_store
    app.state.chapter_dialogue_store = ch_dl_store
    app.state.character_runtime = chr_runtime
    app.state.world_simulator = world
    app.state.director_service = director
    app.state.story_paused = False
    app.state.tick_started = False
    app.state.story_tick_task = None
    app.state.event_bus_subscriptions = []

    logger.info("[OK] 所有模块已注册到框架层")
    logger.info("[OK] 服务启动完成")

    yield
    # ── 优雅关闭：刷新 feed 缓存到磁盘 ──
    if hasattr(world, "flush_feed_cache"):
        try:
            await world.flush_feed_cache()
            logger.info("[Shutdown] feed_cache 已刷新")
        except Exception as e:
            logger.warning(f"[Shutdown] feed_cache 刷新失败: {e}")
    logger.info("服务关闭")


# ═══════════════════════════════════════════════════════════════
# FastAPI app
# ═══════════════════════════════════════════════════════════════

app = FastAPI(title="StoryWeaver API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# 统一网关（替代原来的 include_router）
setup_gateway(app)

# 故事时钟控制
@app.get("/story/status")
async def story_status(request: Request):
    paused = getattr(request.app.state, "story_paused", False)
    tick = getattr(request.app.state, "world_simulator", None)
    return {"paused": paused, "tick": tick._tick_count if tick else 0}

@app.api_route("/story/resume", methods=["GET", "POST"])
async def story_resume(request: Request):
    request.app.state.story_paused = False
    from backend.framework.websocket import run_one_tick, start_tick_loop
    await start_tick_loop(request.app)
    return {"message": "故事时钟已恢复", "paused": False}

# 全部对话（从头开始，供跳转后前端重新加载）
# 支持查询参数：?to_tick=N 只返回到指定 tick 的对话
@app.get("/feed/all")
async def all_feed(request: Request, to_tick: int = 0):
    world = getattr(request.app.state, "world_simulator", None)
    store = getattr(request.app.state, "chapter_dialogue_store", None)

    name_map: dict = {}
    if world:
        for a in world.get_frontend_agents():
            name_map[a["id"]] = a.get("name", a["id"])

    # 从统一章节存储加载
    # 注意：重启后 world._tick_count=0，不能用 0 做上限（会过滤掉所有历史对话）
    items: list = []
    if store:
        current_tick = world._tick_count if world else 999999
        # to_tick 显式传入时用它；current_tick==0 说明刚重启，不加过滤
        if to_tick > 0:
            max_tick = to_tick
        elif current_tick > 0:
            max_tick = current_tick
        else:
            max_tick = None  # None = 不过滤，返回全部
        dialogues = store.load_all(up_to_tick=max_tick)
        for dlg in dialogues:
            sp_id = dlg.get("speakerId", "")
            items.append({
                "tick": dlg.get("tick", 0),
                "agent_id": sp_id,
                "agent_name": name_map.get(sp_id, dlg.get("speakerName", sp_id)),
                "content": dlg.get("content", ""),
                "emotion": cn_emotion(dlg.get("emotion", "neutral")),
                "actionType": dlg.get("actionType", ""),
                "thought": dlg.get("thought", ""),
            })

    # 去重 + tick 升序
    seen = set()
    unique = []
    for item in sorted(items, key=lambda x: x["tick"]):
        core = item.get("content", "").replace("我说：「", "").replace("」", "").strip()
        key = f'{item["tick"]}_{item["agent_id"]}_{core[:40]}'
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# 最近对话动态（供前端实时增量使用）
@app.get("/feed")
async def recent_feed(request: Request, limit: int = 30):
    world = getattr(request.app.state, "world_simulator", None)
    store = getattr(request.app.state, "chapter_dialogue_store", None)

    name_map: dict = {}
    if world:
        for a in world.get_frontend_agents():
            name_map[a["id"]] = a.get("name", a["id"])

    # 从统一章节存储取最近 N 条
    items: list = []
    if store:
        dialogues = store.get_recent(limit)
        for dlg in dialogues:
            sp_id = dlg.get("speakerId", "")
            items.append({
                "tick": dlg.get("tick", 0),
                "agent_id": sp_id,
                "agent_name": name_map.get(sp_id, dlg.get("speakerName", sp_id)),
                "content": dlg.get("content", ""),
                "emotion": cn_emotion(dlg.get("emotion", "neutral")),
                "actionType": dlg.get("actionType", ""),
                "thought": dlg.get("thought", ""),
            })
    elif world:
        # 回退：从内存缓存取
        mem_items = getattr(world, "_last_tick_dialogues", []) or []
        for dlg in mem_items[-limit:]:
            sp_id = dlg.get("speakerId", "")
            items.append({
                "tick": dlg.get("tick", 0),
                "agent_id": sp_id,
                "agent_name": name_map.get(sp_id, dlg.get("speakerName", sp_id)),
                "content": dlg.get("content", ""),
                "emotion": cn_emotion(dlg.get("emotion", "neutral")),
                "actionType": dlg.get("actionType", ""),
                "thought": dlg.get("thought", ""),
            })

    return items

# WebSocket
from backend.framework.websocket import handle_websocket

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await handle_websocket(ws, app)

# 测试页
@app.get("/play", response_class=HTMLResponse)
async def play_page():
    return """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StoryWeaver</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#0b1120;color:#e2e8f0;min-height:100vh}
.container{max-width:700px;margin:0 auto;padding:20px}
h1{text-align:center;padding:30px 0 10px;font-size:22px;color:#94a3b8;font-weight:400;letter-spacing:4px}
.stage{background:#111827;border-radius:12px;min-height:500px;max-height:70vh;overflow-y:auto;padding:20px;margin-bottom:20px}
.dialogue{margin-bottom:16px;display:flex;gap:10px;align-items:flex-start}
.avatar{width:40px;height:40px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:18px;color:#1f2937;flex-shrink:0;border:1.5px solid #d1d5db}
.msg{flex:1}
.name{font-size:13px;color:#64748b;margin-bottom:4px}
.bubble{background:#1e293b;border-radius:4px 16px 16px 16px;padding:12px 16px;font-size:15px;line-height:1.6}
.empty{text-align:center;padding:60px 20px}
.btn-start{padding:14px 56px;font-size:16px;font-weight:600;background:#fff;color:#374151;border:1.5px solid #d1d5db;border-radius:8px;cursor:pointer;letter-spacing:1px}
.btn-start:hover{background:#f3f4f6}
.loading-text{font-size:15px;color:#94a3b8;letter-spacing:2px}
.controls{display:flex;gap:10px;justify-content:center;margin-bottom:20px}
.tick-info{text-align:center;font-size:12px;color:#475569;margin-top:10px}
</style></head>
<body>
<div class="container">
<h1>STORY WEAVER</h1>
<div class="stage" id="stage"><div class="empty">
  <div id="startArea">
    <div style="font-size:15px;color:#94a3b8;margin-bottom:24px;letter-spacing:2px">点击按钮，故事开始</div>
    <button class="btn-start" onclick="startStory()">开始</button>
  </div>
  <div id="loadingArea" style="display:none"><div class="loading-text">角色正在思考中...</div></div>
</div></div>
<div class="tick-info">Tick: <span id="tickNum">0</span></div>
</div>
<script>
var seen=new Set(),tickCount=0;

async function startStory(){
  document.getElementById('startArea').style.display='none';
  document.getElementById('loadingArea').style.display='block';
  try{ await fetch('/api/v1/world/tick?world_id=default',{method:'POST'}); }catch(e){}
  pollFeed();
  setInterval(pollFeed,5000);
}

async function pollFeed(){
  try{
    var r=await fetch('/feed?limit=30');
    var items=await r.json();
    var stage=document.getElementById('stage');
    var first=!stage.querySelector('.dialogue');
    for(var i=items.length-1;i>=0;i--){
      var item=items[i],key=item.tick+'_'+item.agent_id+'_'+item.content;
      if(seen.has(key))continue;
      seen.add(key);
      if(item.tick>tickCount)tickCount=item.tick;
      document.getElementById('tickNum').textContent=tickCount;
      var text=item.content||'',m=text.match(/：「(.+?)」/);
      if(m)text=m[1];else text=text.replace(/^我/,'');
      var div=document.createElement('div');div.className='dialogue';
      var name=item.agent_name||item.agent_id;
      div.innerHTML='<div class="avatar">'+name.charAt(0)+'</div><div class="msg"><div class="name">'+name+'</div><div class="bubble">'+text+'</div></div>';
      if(first){stage.innerHTML='';first=false;}
      stage.appendChild(div);
      stage.scrollTop=stage.scrollHeight;
    }
    document.getElementById('loadingArea').style.display='none';
  }catch(e){}
}
</script>
</body></html>"""

@app.get("/test")
async def test_page():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/play")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
