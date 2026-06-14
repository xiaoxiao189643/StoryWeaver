# ============================================================
# timeline/snapshot.py —— 快照构建与状态恢复引擎
# ============================================================
from __future__ import annotations

import json
import logging
import time
from typing import Dict, Any, Optional, TYPE_CHECKING

from backend.model.world import WorldTruth
from backend.model.narrative import DirectorState

if TYPE_CHECKING:
    from backend.engine.world_simulator import WorldSimulator
    from backend.modules.director.director_service import DirectorService

logger = logging.getLogger(__name__)


def build_snapshot(world_simulator, director, tick: int) -> Dict[str, Any]:
    """构建当前世界状态的完整快照。"""
    gt = world_simulator._ground_truth

    # Agent 状态（双源：优先 _agent_runtime，回退到 _character_runtime）
    agents = {}
    source_runtime = world_simulator._agent_runtime
    # 如果 _agent_runtime 为空但 _character_runtime 有角色，回退读取
    if (not source_runtime or not source_runtime.get_all_agents()) \
       and hasattr(world_simulator, "_character_runtime") \
       and world_simulator._character_runtime:
        source_runtime = world_simulator._character_runtime

    if source_runtime:
        for aid, agent in source_runtime.get_all_agents().items():
            try:
                agents[aid] = agent.model_dump()
            except Exception as e:
                logger.warning(f"[Snapshot] Agent {aid} 序列化失败: {e}")

    # Director 状态
    director_state = {}
    try:
        director_state = director.state.model_dump()
    except Exception as e:
        logger.warning(f"[Snapshot] DirectorState 序列化失败: {e}")

    # 章节
    chapters = []
    director_runtime = {}
    try:
        for ch in director._chapters:
            chapters.append(ch.model_dump())
        director_runtime = {
            "current_chapter_start_tick": getattr(director, "_current_chapter_start_tick", 0),
            "chapter_event_log": list(getattr(director, "_chapter_event_log", [])),
            "chapter_dialogue_snippets": list(getattr(director, "_chapter_dialogue_snippets", [])),
        }
    except Exception as e:
        logger.warning(f"[Snapshot] Chapters 序列化失败: {e}")

    # CharacterRuntime 状态
    character_runtime_state = {}
    if hasattr(world_simulator, "_character_runtime") and world_simulator._character_runtime:
        cr = world_simulator._character_runtime
        character_runtime_state = {
            "idle_counters": dict(cr._idle_counters) if hasattr(cr, "_idle_counters") else {},
            "wake_events": {k: list(v) for k, v in cr._wake_events.items()} if hasattr(cr, "_wake_events") else {},
            "last_acted_tick": dict(cr._last_acted_tick) if hasattr(cr, "_last_acted_tick") else {},
            "round_robin_order": list(cr._round_robin_order) if hasattr(cr, "_round_robin_order") else [],
        }

    # 叙事层状态（StoryState + PlotManager）
    narrative_state = {}
    if hasattr(world_simulator, "_story_state") and world_simulator._story_state:
        try:
            narrative_state["story_state"] = world_simulator._story_state.to_dict()
        except Exception as e:
            logger.warning(f"[Snapshot] StoryState 序列化失败: {e}")
    if hasattr(world_simulator, "_plot_manager") and world_simulator._plot_manager:
        pm = world_simulator._plot_manager
        narrative_state["plot_manager"] = {
            "last_speakers": list(pm._last_speakers),
            "speak_counts": dict(pm._speak_counts),
            "silent_warnings": dict(pm._silent_warnings),
        }

    # 玩家影响力状态
    player_influence_state = {}
    if hasattr(world_simulator, "_player_influence") and world_simulator._player_influence:
        try:
            player_influence_state = world_simulator._player_influence._to_dict()
        except Exception as e:
            logger.warning(f"[Snapshot] PlayerInfluence 序列化失败: {e}")

    # 信念系统状态
    belief_state = {}
    if hasattr(world_simulator, "_belief") and world_simulator._belief:
        try:
            belief_state = world_simulator._belief._to_dict() if hasattr(world_simulator._belief, "_to_dict") else {}
        except Exception as e:
            logger.warning(f"[Snapshot] BeliefSystem 序列化失败: {e}")

    snapshot = {
        "tick": tick,
        "timestamp": time.time(),
        "world_truth": gt.get_truth().model_dump(),
        "agents": agents,
        "director_state": director_state,
        "director_chapters": chapters,
        "director_runtime": director_runtime,
        "recent_events": list(world_simulator._recent_events) if hasattr(world_simulator, "_recent_events") else [],
        "character_runtime": character_runtime_state,
        "narrative": narrative_state,
        "player_influence": player_influence_state,
        "beliefs": belief_state,
    }

    return snapshot


async def restore_from_snapshot(
    world_simulator,
    director,
    memory_system,
    snapshot_data: Dict[str, Any],
) -> Dict[str, Any]:
    """从快照恢复完整世界状态。返回恢复结果摘要。"""
    target_tick = snapshot_data["tick"]
    logger.info(f"[Snapshot] 开始恢复状态到 tick={target_tick}")

    # ── 1. 恢复 GroundTruth ──
    try:
        from backend.model.world import WorldTruth
        truth = WorldTruth.model_validate(snapshot_data["world_truth"])
        world_simulator._ground_truth._truth = truth
        logger.info(f"[Snapshot] GroundTruth 已恢复")
    except Exception as e:
        logger.error(f"[Snapshot] GroundTruth 恢复失败: {e}")

    # ── 2. 恢复 DirectorState ──
    try:
        from backend.model.narrative import DirectorState
        restored_state = DirectorState.model_validate(snapshot_data.get("director_state", {}))
        director.state = restored_state
        logger.info(f"[Snapshot] DirectorState 已恢复 (tension={restored_state.current_tension})")
    except Exception as e:
        logger.error(f"[Snapshot] DirectorState 恢复失败: {e}")

    # ── 3. 恢复章节 ──
    try:
        from backend.model.narrative import Chapter
        chapters_data = snapshot_data.get("director_chapters", [])
        if chapters_data:
            director._chapters = [Chapter.model_validate(ch) for ch in chapters_data]
            # 更新当前章节起始 tick
            if director._chapters:
                last = director._chapters[-1]
                if last.end_tick is None or last.end_tick >= target_tick:
                    director._current_chapter_start_tick = last.start_tick
            runtime_data = snapshot_data.get("director_runtime", {})
            if runtime_data:
                director._current_chapter_start_tick = runtime_data.get("current_chapter_start_tick", director._current_chapter_start_tick)
                director._chapter_event_log = list(runtime_data.get("chapter_event_log", []))
                director._chapter_dialogue_snippets = list(runtime_data.get("chapter_dialogue_snippets", []))
            logger.info(f"[Snapshot] {len(director._chapters)} 个章节已恢复")
    except Exception as e:
        logger.error(f"[Snapshot] Chapters 恢复失败: {e}")

    # ── 4. 恢复 Agent 状态 ──
    agent_count = 0
    try:
        from backend.model.agent import AgentState
        agents_data = snapshot_data.get("agents", {})
        if agents_data and world_simulator._agent_runtime:
            # 先存一份旧数据防回滚失败
            old_agents = dict(world_simulator._agent_runtime._agents)
            try:
                world_simulator._agent_runtime._agents.clear()
                if hasattr(world_simulator._agent_runtime, '_agent_index'):
                    world_simulator._agent_runtime._agent_index.clear()
                for aid, adata in agents_data.items():
                    try:
                        agent = AgentState.model_validate(adata)
                        world_simulator._agent_runtime._agents[aid] = agent
                        agent_count += 1
                    except Exception as e:
                        logger.warning(f"[Snapshot] Agent {aid} 恢复失败: {e}")
            except Exception:
                # 恢复失败时回滚旧数据
                world_simulator._agent_runtime._agents = old_agents
                raise
        elif agents_data and not world_simulator._agent_runtime:
            logger.warning("[Snapshot] _agent_runtime 未初始化，跳过 Agent 恢复（需先调用 register_agent）")
        logger.info(f"[Snapshot] {agent_count} 个 Agent 已恢复")
    except Exception as e:
        logger.error(f"[Snapshot] Agent 恢复失败: {e}")

    # ── 4.5 恢复 CharacterRuntime 状态 ──
    try:
        cr_data = snapshot_data.get("character_runtime", {})
        if cr_data and hasattr(world_simulator, "_character_runtime") and world_simulator._character_runtime:
            cr = world_simulator._character_runtime
            # 先同步 agent 列表（与 _agent_runtime 保持一致）
            cr._agents = dict(world_simulator._agent_runtime._agents) if world_simulator._agent_runtime else {}
            if cr_data.get("idle_counters"):
                cr._idle_counters = cr_data["idle_counters"]
            if cr_data.get("wake_events"):
                cr._wake_events = cr_data["wake_events"]
            if cr_data.get("last_acted_tick"):
                cr._last_acted_tick = cr_data["last_acted_tick"]
            if cr_data.get("round_robin_order"):
                cr._round_robin_order = cr_data["round_robin_order"]
            logger.info(f"[Snapshot] CharacterRuntime 状态已恢复 (agents={len(cr._agents)})")
    except Exception as e:
        logger.error(f"[Snapshot] CharacterRuntime 恢复失败: {e}")

    # ── 4.6 恢复叙事层（StoryState + PlotManager） ──
    try:
        narrative_data = snapshot_data.get("narrative", {})
        if narrative_data.get("story_state") and hasattr(world_simulator, "_story_state"):
            from backend.modules.narrative.story_state import StoryState
            world_simulator._story_state = StoryState.from_dict(narrative_data["story_state"])
            logger.info(f"[Snapshot] StoryState 已恢复")
            # 更新 PlotManager 和 Validator 的 story_state 引用
            if hasattr(world_simulator, "_plot_manager") and world_simulator._plot_manager:
                world_simulator._plot_manager.state = world_simulator._story_state
            if hasattr(world_simulator, "_validator") and world_simulator._validator:
                world_simulator._validator.state = world_simulator._story_state
        if narrative_data.get("plot_manager") and hasattr(world_simulator, "_plot_manager"):
            pm_data = narrative_data["plot_manager"]
            pm = world_simulator._plot_manager
            pm._last_speakers = pm_data.get("last_speakers", [])
            pm._speak_counts = pm_data.get("speak_counts", {})
            pm._silent_warnings = pm_data.get("silent_warnings", {})
            logger.info(f"[Snapshot] PlotManager 状态已恢复")
    except Exception as e:
        logger.error(f"[Snapshot] 叙事层恢复失败: {e}")

    # ── 4.7 恢复玩家影响力 ──
    try:
        pi_data = snapshot_data.get("player_influence", {})
        if pi_data and hasattr(world_simulator, "_player_influence") and world_simulator._player_influence:
            world_simulator._player_influence._from_dict(pi_data)
            logger.info(f"[Snapshot] PlayerInfluence 已恢复 ({len(pi_data)} agents)")
    except Exception as e:
        logger.error(f"[Snapshot] PlayerInfluence 恢复失败: {e}")

    # ── 4.8 恢复信念系统 ──
    try:
        belief_data = snapshot_data.get("beliefs", {})
        if belief_data and hasattr(world_simulator, "_belief") and world_simulator._belief:
            if hasattr(world_simulator._belief, "_from_dict"):
                world_simulator._belief._from_dict(belief_data)
                logger.info(f"[Snapshot] BeliefSystem 已恢复 ({len(belief_data)} agents)")
    except Exception as e:
        logger.error(f"[Snapshot] BeliefSystem 恢复失败: {e}")

    # ── 5. 裁剪记忆（tick > target 的删除） ──
    try:
        if memory_system:
            deleted = memory_system.rollback_after(target_tick)
            logger.info(f"[Snapshot] 记忆已裁剪: {deleted} 条删除（含短期+向量）")
    except Exception as e:
        logger.error(f"[Snapshot] 记忆裁剪失败: {e}")

    # ── 5.5 裁剪对话历史（旧 DialogueStore + 新 ChapterDialogueStore） ──
    try:
        if hasattr(world_simulator, "_dialogue_store") and world_simulator._dialogue_store:
            d_deleted = world_simulator._dialogue_store.rollback_after(target_tick)
            if d_deleted > 0:
                logger.info(f"[Snapshot] DialogueStore 已裁剪: {d_deleted} 条")
    except Exception as e:
        logger.error(f"[Snapshot] DialogueStore 裁剪失败: {e}")

    # 裁剪统一章节对话存储
    if hasattr(world_simulator, '_dialogue_store') and hasattr(world_simulator._dialogue_store, 'rollback_after'):
        pass  # 上面已处理旧存储
    # 新存储通过 app.state.chapter_dialogue_store 访问，由 handler 层处理

    # ── 6. 重置 tick 和事件 ──
    world_simulator._tick_count = target_tick
    world_simulator._recent_events = list(snapshot_data.get("recent_events", []))
    world_simulator._tick_in_progress = False
    world_simulator._tick_started_at = 0
    if hasattr(director.state, "_last_player_text"):
        director.state._last_player_text = ""
    # 裁剪内存中的对话缓存
    world_simulator._last_tick_dialogues = [
        d for d in world_simulator._last_tick_dialogues
        if d.get("tick", 0) <= target_tick
    ]

    # ── 7. 构建前端事件 ──
    frontend_snapshot = world_simulator.get_frontend_snapshot()

    logger.info(f"[Snapshot] 状态恢复完成 → tick={target_tick}")

    return {
        "success": True,
        "tick": target_tick,
        "agent_count": agent_count,
        "world_state": frontend_snapshot.get("world_state"),
        "agents": frontend_snapshot.get("agents"),
        "message": f"世界状态已恢复到 tick {target_tick}",
    }
