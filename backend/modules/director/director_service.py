
# ============================================================
# director/director_service.py —— 导演服务主类
# ============================================================
# 整合所有导演子模块的统一服务。
# 每个 tick 由 World Simulator 调用 update()，导演执行叙事决策。
#
# 工作流程（每个 tick）：
#   1. RhythmController  → 评估并更新紧张度
#   2. EventScheduler    → 取出到期事件并触发
#   3. EventScheduler    → 判断是否需要生成自发事件
#   4. InfoController    → 判断是否需要曝光秘密
#   5. NarrativeConvergence → 更新收束因子，判断是否需要强制收束
#   6. 生成 SceneGoal    → 返回给 World Simulator
#
# 与框架层的对接：
#   - 导演通过 EventBus 发布事件，框架层通过 WebSocket 推送给前端
#   - 推送类型：directive、narrative_event（见接口文档）
#   - REST API 端点由 api/routes.py 调用 get_status() 等方法
#
# 与角色后端的对接：
#   - SceneGoal 通过 World Simulator 注入 Agent 决策上下文
#   - directive 消息通知角色后端调整行为
#   - TODO：调用 POST /role/apply_directives 下发任务
# ============================================================

import time
import random
import logging
from typing import Dict, List, Optional, Any

from backend.model.narrative import DirectorState, SceneGoal, TensionLevel, NarrativeEvent, Chapter
from backend.modules.director.rhythm_controller import RhythmController
from backend.framework.bus import bus
from backend.modules.director.info_controller import InfoController
from backend.modules.director.event_scheduler import EventScheduler
from backend.modules.director.narrative_convergence import NarrativeConvergence
from backend.engine.ground_truth import GroundTruthManager
from backend.modules.character.belief_system import BeliefSystem
from backend.utils.i18n import cn_phase

logger = logging.getLogger(__name__)


class DirectorService:
    """
    导演服务 —— 叙事结构的控制中心。
    
    导演的职责边界：
      ✅ 控制叙事节奏（紧张度）
      ✅ 调度叙事事件（停电、广播、谋杀...）
      ✅ 管理信息释放（哪个秘密何时曝光）
      ✅ 推进叙事收束（防止剧情无限拖延）
      ❌ 不直接控制 Agent 的对话内容
      ❌ 不直接修改世界状态（通过 EventBus 间接执行）
    """

    def __init__(
        self,
        ground_truth: GroundTruthManager,
        belief_system: BeliefSystem,
        event_bus=None,     # EventBus 实例，用于推送消息给框架层
    ):
        self._ground_truth = ground_truth
        self._belief = belief_system

        # EventBus：导演通过它发布事件，框架层通过 WebSocket 推送给前端
        # 如果 event_bus 为 None（测试环境），使用 Mock
        self._event_bus = event_bus or _MockEventBus()

        # ── 子模块初始化 ──────────────────────────────────
        self.rhythm = RhythmController()
        self.info = InfoController()
        self.event_scheduler = EventScheduler()
        self.convergence = NarrativeConvergence()

        # ── 导演状态 ──────────────────────────────────────
        # DirectorState 是所有子模块共享的状态对象
        # 所有子模块读写同一个 state，保证一致性
        self.state = DirectorState()
        self._last_narration_tick = -self._NARRATION_COOLDOWN
        self._last_narration_tension = None
        self._last_narration_text = ""
        self._chapters: list = []
        self._current_chapter_start_tick = 0
        self._chapter_event_log: list = []
        self._chapter_dialogue_snippets: list = []  # 对话片段，供LLM章节命名用
        self._timeline_store = None  # TimelineStore 引用
        self._dialogue_store = None  # ChapterDialogueStore 引用（统一章节对话存储）

        logger.info("[DirectorService] 导演服务初始化完成")

    # ============================================================
    # 初始化方法
    # ============================================================

    def initialize(
        self,
        start_tick: int,
        secret_keys: List[str],
        scheduled_events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        初始化导演状态（游戏开始时调用一次）。
        
        这个方法应该在 WorldSimulator 启动时被调用，
        传入本局游戏的剧情配置（秘密列表、预定事件等）。
        
        Args:
            start_tick: 游戏起始 tick
            secret_keys: 本局游戏的秘密列表（按曝光优先级排序）
                         例如 ["victim_past", "murderer_identity", "secret_room"]
            scheduled_events: 预定事件列表，格式：
                         [{"type": "murder", "tick": 100, "description": "...", ...}]
        """
        # 记录起始 tick
        self.state.tick_started = start_tick
        self.state.last_core_event_tick = start_tick

        # 初始化秘密列表
        self.info.initialize_secrets(self.state, secret_keys)

        # 安排预定事件
        if scheduled_events:
            for ev in scheduled_events:
                self.event_scheduler.schedule_event(
                    state=self.state,
                    event_type=ev["type"],
                    tick=ev["tick"],
                    affected_locations=ev.get("affected_locations", []),
                    affected_agents=ev.get("affected_agents", []),
                    description=ev.get("description", ""),
                    priority=ev.get("priority", 0),
                    metadata=ev.get("metadata", {}),
                )

        # ── 创建第一章 ──
        self._chapters = []
        chapter1 = Chapter(
            id="chapter_1", number=1,
            title="第一章：故事开始",  # 占位符，创建第二章时回溯重命名
            start_tick=start_tick,
            tension="CALM",
        )
        self._chapters.append(chapter1)
        self._current_chapter_start_tick = start_tick
        self._chapter_event_log = []
        self._chapter_dialogue_snippets = []

        # 同步第一章到时间线节点
        if self._timeline_store:
            try:
                self._timeline_store.add_node({
                    "node_id": chapter1.id,
                    "tick": chapter1.start_tick,
                    "title": chapter1.title,
                    "summary": chapter1.summary or "",
                    "tension": TensionLevel[chapter1.tension].label() if chapter1.tension in TensionLevel.__members__ else "平静",
                    "key_events": chapter1.key_events or [],
                })
            except Exception as e:
                logger.warning(f"[DirectorService] 第一章时间线同步失败: {e}")

        logger.info(
            f"[DirectorService] 初始化完成: start_tick={start_tick}, "
            f"secrets={secret_keys}, scheduled={len(scheduled_events or [])} 个事件"
        )

    def set_timeline_store(self, store) -> None:
        """注入 TimelineStore，用于章节→时间线节点同步。"""
        self._timeline_store = store

    def set_dialogue_store(self, store) -> None:
        """注入 ChapterDialogueStore，用于章节对话文件管理。"""
        self._dialogue_store = store

    def create_cast(
        self,
        templates: list,
        locations: list,
        items: list,
        secrets: list,
    ) -> list:
        """
        导演根据固定角色模板生成最终阵容。
        为每个角色分配与故事背景、秘密和物品相关的目标。
        """
        cast = []
        location_ids = {loc.id for loc in locations}
        item_names = [item.name for item in items]

        for i, t in enumerate(templates):
            loc_id = t.get("location_id", "hall")
            if loc_id not in location_ids:
                loc_id = list(location_ids)[0]

            goals = [
                {"id": f"{t['id']}_g1", "description": t.get("goal", "探索真相"),
                 "priority": 9, "is_active": True},
            ]

            # 导演根据角色身份追加秘密相关目标
            if "侦探" in t.get("role", ""):
                goals.append({"id": f"{t['id']}_g2", "description": "观察其他人的行为，寻找可疑之处", "priority": 7, "is_active": True})
            elif "管家" in t.get("role", ""):
                goals.append({"id": f"{t['id']}_g2", "description": "维持别墅的正常运转，不让外人起疑", "priority": 5, "is_active": True})
            elif "女主人" in t.get("role", ""):
                goals.append({"id": f"{t['id']}_g2", "description": "不让任何人提前知道你的计划", "priority": 8, "is_active": True})
            elif "访客" in t.get("role", ""):
                goals.append({"id": f"{t['id']}_g2", "description": f"在{random.choice(item_names) if item_names else '别墅'}附近寻找线索", "priority": 8, "is_active": True})

            cast.append({
                "id": t["id"],
                "name": t["name"],
                "location_id": loc_id,
                "current_action": "idle",
                "personality": {
                    "core_description": t.get("core_description", ""),
                    "traits": t.get("traits", {}),
                },
                "emotion": {
                    "current_mood": t.get("emotion", "平静"),
                    "intensity": 0.4 + 0.1 * i,
                },
                "goals": goals,
            })

        logger.info(f"[DirectorService] 导演生成了 {len(cast)} 个角色: {[c['name'] for c in cast]}")
        return cast

    # ============================================================
    # 核心更新循环
    # ============================================================

    async def update(
        self,
        current_tick: int,
        recent_events: List[str],
        player_active: bool,
        player_text: str = "",
    ) -> SceneGoal:
        """
        执行一个 tick 的导演更新，返回当前场景目标。

        Args:
            current_tick: 当前游戏 tick
            recent_events: 最近发生的事件描述列表
            player_active: 本 tick 玩家是否有操作
            player_text: 玩家指令原文（用于调整场景目标和叙事方向）
        """
        self.state.last_update_tick = current_tick
        self.state._last_player_text = player_text or ""

        if player_text and self.state.scene_goal is not None:
            self.state.scene_goal_elapsed_ticks = getattr(self.state.scene_goal, "duration_ticks", 0)

        # ── 步骤 1：更新紧张度 ────────────────────────────
        # RhythmController 根据故事进展、玩家活跃度等计算新紧张度
        new_tension = self.rhythm.evaluate_tension(
            self.state, current_tick, player_active
        )
        # 如果紧张度发生了变化，推送 directive 消息通知前端和角色后端
        if new_tension != self.state.current_tension:
            await self._publish_directive(current_tick)
        self.state.current_tension = new_tension

        # ── 步骤 2：处理到期事件 ──────────────────────────
        # 取出所有在当前 tick 到期的预定事件
        due_events = self.event_scheduler.get_due_events(
            self.state, current_tick
        )
        for event in due_events:
            await self._trigger_event(event, current_tick)

        # ── 步骤 3：判断是否需要自发事件 ──────────────────
        # 如果本 tick 没有预定事件触发，让调度器判断是否需要自发生成一个
        if not due_events:
            spontaneous = self.event_scheduler.generate_spontaneous_event(
                self.state, current_tick
            )
            if spontaneous:
                await self._trigger_event(spontaneous, current_tick)

        # ── 步骤 4：信息释放判断 ──────────────────────────
        # InfoController 判断是否到了曝光某个秘密的时机
        secret_to_reveal = self.info.decide_revelation(
            self.state, current_tick
        )
        if secret_to_reveal:
            self.info.mark_as_revealed(self.state, secret_to_reveal)
            # 更新曝光时间戳（用于冷却时间计算）
            self.state.last_revelation_tick = current_tick
            # 秘密曝光也是叙事进展，推进收束因子
            self.convergence.advance_convergence(
                self.state, delta=0.05, reason=f"secret_revealed:{secret_to_reveal}"
            )
            logger.info(f"[DirectorService] 秘密曝光: {secret_to_reveal}")

        # ── 步骤 5：叙事收束评估 ──────────────────────────
        # 更新 convergence_factor，并判断是否需要强制收束
        new_factor = self.convergence.evaluate_convergence(
            self.state, current_tick, recent_events
        )
        self.state.convergence_factor = new_factor

        # 判断是否需要强制收束（叙事发散太久）
        if self.convergence.needs_convergence(
            self.state, current_tick, self.state.last_core_event_tick
        ):
            conv_event = self.convergence.generate_convergence_event(
                self.state, current_tick
            )
            await self._trigger_event(conv_event, current_tick)

        # ── 步骤 6：生成场景目标（同时尝试获导演旁白） ──
        scene_goal, llm_narration = await self._generate_scene_goal(current_tick, recent_events)
        self.state.scene_goal = scene_goal
        self.state.scene_goal_elapsed_ticks += 1

        # ── 步骤 7：章节管理 ──────────────────────────────
        # 先收集本tick事件日志，再创建章节（让key_events包含当前事件）
        for ev in due_events:
            loc_names = self._resolve_location_names(ev.affected_locations or [])
            agent_names = self._resolve_agent_names(ev.affected_agents or [])
            ctx = ""
            if agent_names:
                ctx = f"（涉及：{'、'.join(agent_names[:3])}）"
            elif loc_names:
                ctx = f"（地点：{'、'.join(loc_names[:2])}）"
            self._chapter_event_log.append(f"{self._event_type_label(ev.type)}：{ev.description}{ctx}")
        if secret_to_reveal:
            self._chapter_event_log.append(f"秘密曝光：{self._secret_label(secret_to_reveal)}")

        chapter_trigger = (
            len(due_events) > 0
            or secret_to_reveal is not None
            or new_tension != self._last_narration_tension
        )
        if chapter_trigger and (current_tick - self._current_chapter_start_tick) > 5:
            await self._maybe_create_chapter(current_tick, due_events, secret_to_reveal)

        # ── 步骤 8：导演旁白（第一 tick 强制生成序幕） ──
        if current_tick <= 1:
            narration = await self._generate_narration(current_tick, force=True)
        else:
            narration = llm_narration or await self._generate_narration(current_tick, force=True)
        if narration:
            self._last_narration_tick = current_tick

        # ── 旁白写入全局记忆（所有 NPC 都能感知到氛围变化） ──
        if narration:
            try:
                await bus.send(to="memory", type="add_memory", payload={
                    "world_id": "default_world",
                    "content": f"【导演旁白】{narration}",
                    "tick": current_tick,
                    "importance": 0.7,
                    "emotion_tag": "平静",
                    "scope": "global",
                })
            except Exception:
                pass

        logger.debug(
            f"[DirectorService] tick={current_tick} 更新完成: "
            f"tension={self.state.current_tension.label()}, "
            f"convergence={self.state.convergence_factor:.2f}, "
            f"goal={scene_goal.description[:30]}..."
        )

        return {"scene_goal": scene_goal, "narration": narration}

    # ============================================================
    # 玩家干预
    # ============================================================

    async def receive_intervention(self, player_text: str) -> Dict:
        """处理玩家干预，评估意图并生成指令。"""
        directive = f"【神谕】高维存在降下指引：「{player_text}」。角色们应当对此有所感应。"

        effectiveness = 1.0
        narration_hint = ""
        # 调用 LLM 评估玩家意图
        try:
            eval_result = await bus.send(to="llm", type="llm_evaluate_intervention", payload={
                "player_text": player_text,
                "tension": self.state.current_tension.label(),
            })
            if eval_result and eval_result.get("success"):
                intent_type = eval_result.get("intent_type", "other")
                effectiveness = eval_result.get("effectiveness", 1.0)
                narration_hint = eval_result.get("narration_hint", "") or eval_result.get("narrative_response", "")
                # 根据意图类型调整紧张度
                if intent_type == "accuse" or intent_type == "threaten":
                    if self.state.current_tension.value < 2:
                        self.state.current_tension = type(self.state.current_tension)(self.state.current_tension.value + 1)
                self.state._last_intent_type = intent_type
        except Exception:
            pass

        return {
            "player_directive": directive,
            "effectiveness": effectiveness,
            "intent_type": getattr(self.state, "_last_intent_type", "other"),
            "narration_hint": narration_hint,
        }

    # ============================================================
    # 接收角色模块汇报
    # ============================================================

    def report_agent_action(
        self,
        agent_id: str,
        agent_name: str,
        action_type: str,
        action: str,
        target: str = "",
        dialogue: str = "",
        thought: str = "",
        emotion: str = "平静",
    ) -> Dict[str, Any]:
        """
        接收角色模块汇报：NPC 做了什么，导演据此更新叙事状态。
        """
        result = {"acknowledged": True, "effects": []}

        detail = f"{agent_name} [{action_type}] {action}"
        if dialogue:
            detail += f" 说：「{dialogue}」"
        if thought:
            detail += f" （内心: {thought}）"

        # ── 收集对话片段供章节命名使用 ──
        if dialogue and len(dialogue) > 3:
            snippet = dialogue if len(dialogue) <= 80 else dialogue[:80] + "…"
            self._chapter_dialogue_snippets.append(f"{agent_name}：{snippet}")

        if action_type == "investigate":
            self.convergence.advance_convergence(self.state, delta=0.01, reason=f"investigate:{agent_id}")
            result["effects"].append("convergence+0.01")
            clue = self.info.get_available_clues(self.state, target)
            if clue:
                result["effects"].append(f"clues_found:{len(clue)}")

        elif action_type == "speak" and dialogue:
            for secret in self.state.hidden_secrets:
                if secret.lower().replace("_", "") in dialogue.lower().replace(" ", ""):
                    self.info.mark_as_revealed(self.state, secret)
                    self.state.last_revelation_tick = getattr(self.state, "last_update_tick", 0)
                    result["effects"].append(f"secret_revealed:{secret}")

        elif action_type == "move":
            result["effects"].append("location_changed")

        tick = getattr(self.state, "last_update_tick", 0)
        self.state.log_decision(tick, "agent_report", {
            "agent_id": agent_id,
            "action_type": action_type,
            "action": action,
            "dialogue": dialogue[:50] if dialogue else "",
        })

        return result

    # ============================================================
    # 导演旁白生成
    # ============================================================

    # 旁白冷却 tick 数，避免刷屏
    _NARRATION_COOLDOWN = 3

    async def _generate_narration(self, current_tick: int, force: bool = False) -> Optional[str]:
        """
        生成导演旁白。在关键时刻输出场景描述。
        返回 None 表示本 tick 不需要旁白。
        """
        # 冷却检查（除非强制）
        if not force and (current_tick - self._last_narration_tick) < self._NARRATION_COOLDOWN:
            return None

        # 紧张度变化时强制旁白
        tension_changed = self._last_narration_tension != self.state.current_tension
        if not force and not tension_changed:
            # 随机概率：每 N 个 tick 有 30% 概率出旁白
            if random.random() > 0.3:
                return None

        self._last_narration_tick = current_tick
        self._last_narration_tension = self.state.current_tension

        # ── 去重池：避免旁白重复 ──
        if not hasattr(self, "_narration_history"):
            self._narration_history: list = []

        # 尝试用导演 LLM 生成旁白
        llm_narration = await self._llm_narration(current_tick)
        if llm_narration:
            # 去重检查：和最近 3 条旁白做近似比较
            for prev in self._narration_history[-3:]:
                overlap = len(set(llm_narration) & set(prev)) / max(len(set(prev)), 1)
                if overlap > 0.6:
                    logger.info("[DirectorService] 旁白与近期重复，跳过")
                    return None
            self._narration_history.append(llm_narration)
            if len(self._narration_history) > 10:
                self._narration_history = self._narration_history[-10:]
            return llm_narration

        # 回退：模板旁白
        tension = self.state.current_tension
        convergence = self.state.convergence_factor
        secrets_hidden = len(self.state.hidden_secrets)
        secrets_revealed = len(self.state.revealed_secrets)

        if tension == TensionLevel.CALM:
            narrations = [
                "暴风雪在窗外呼啸，别墅内灯火通明，一切看似宁静。",
                "古老的落地钟发出沉稳的滴答声，时间在不知不觉中流逝。",
                "大厅里弥漫着木材燃烧的暖意，却也藏着说不清的寒意。",
                "每个人都在等待——等待某个信号，某个人，或者某件事。",
                "壁炉的火光在墙壁上投下摇曳的影子。",
                "窗外积雪压弯了松枝，远处偶尔传来猫头鹰的低鸣。",
                "热茶在杯中冒着白雾，没有人先开口打破沉默。",
                "走廊深处的脚步声在大厅里回荡，然后归于寂静。",
            ]
        elif tension == TensionLevel.TENSE:
            narrations = [
                "空气中弥漫着难以言说的不安，每个人都在偷偷观察彼此。",
                "墙上摇曳的烛光让影子扭曲变形，仿佛暗处藏着什么。",
                f"已经有{secrets_revealed}个秘密浮出水面，但还有{secrets_hidden}个隐藏在暗处。",
                "对话变得小心翼翼，每一个字都像在试探对方的底线。",
                "一阵寒风从门缝钻进，烛火剧烈摇晃了几下。",
                "有人避开了对视，有人假装整理衣襟。",
                "楼梯上传来木板被踩压的吱嘎声，但没有人下楼。",
                "沉默在蔓延，每一秒都被拉得很长。",
            ]
        elif tension == TensionLevel.CRISIS:
            narrations = [
                "危机降临——所有人都意识到，今晚注定无法平静地度过。",
                "紧张的气氛如同绷紧的琴弦，只差最后一根稻草就会断裂。",
                "没有人可以继续保持中立，是时候做出选择了。",
                f"真相正在逼近，收束的时钟指向了{convergence:.0%}。",
                "暴风雪愈发猛烈，窗户被吹得咯咯作响。",
                "某处传来玻璃碎裂的声音，所有人都僵住了。",
                "心跳声在大厅里格外清晰。",
                "一道闪电划破夜空，照亮了所有人脸上的表情。",
            ]
        else:
            narrations = [
                "一切迹象都在指向同一个答案——真相即将揭晓。",
                "漫漫长夜即将过去，但黎明前的这一刻最为关键。",
                "所有的谎言、隐瞒和秘密，终究要面对最后的审判。",
                f"故事走到了尾声，{secrets_revealed}个被揭露的秘密串联成了完整的拼图。",
                "每个人都知道——接下来的几分钟将改变一切。",
                "没有人再试图逃避，真相的气味弥漫在空气中。",
                "暴风雪渐渐平息，仿佛在为最后的告白让路。",
                "落地钟敲响了整点，每一声都像在倒数着什么。",
            ]

        # 避免连续重复：检查最近 3 条旁白
        recent_set = set("".join(self._narration_history[-3:])) if self._narration_history else set()
        available = [n for n in narrations if n != self._last_narration_text and n not in self._narration_history[-2:]]
        if not available:
            available = narrations
        chosen = random.choice(available)
        self._last_narration_text = chosen
        self._narration_history.append(chosen)
        if len(self._narration_history) > 10:
            self._narration_history = self._narration_history[-10:]
        return chosen

    async def generate_narration_for_dialogues(self, current_tick: int, dialogues: List[str]) -> Optional[str]:
        """根据角色实际对话内容生成匹配的场景旁白。"""
        if not dialogues:
            return None
        dialogue_text = "\n".join(dialogues[:4])
        try:
            result = await bus.send(to="llm", type="llm_director_narration", payload={
                "tension": self.state.current_tension.label(),
                "convergence": self.state.convergence_factor,
                "event_desc": f"角色们在暴风雪中的雪山别墅里对话：\n{dialogue_text}",
                "recent_actions": "",
                "is_responsive": True,
                "recent_narrations": self._narration_history[-5:] if hasattr(self, "_narration_history") and self._narration_history else [],
            })
            if result and result.get("narration"):
                narration = result["narration"]
                # 去重检查
                if not hasattr(self, "_narration_history"):
                    self._narration_history = []
                for prev in self._narration_history[-3:]:
                    overlap = len(set(narration) & set(prev)) / max(len(set(prev)), 1)
                    if overlap > 0.6:
                        return None
                self._narration_history.append(narration)
                if len(self._narration_history) > 10:
                    self._narration_history = self._narration_history[-10:]
                return narration
        except Exception:
            pass
        return None

    async def _llm_narration(self, current_tick: int = 0) -> Optional[str]:
        """通过导演 LLM 生成旁白，失败时返回 None。"""
        try:
            payload = {
                "tension": self.state.current_tension.label(),
                "convergence": self.state.convergence_factor,
                "secrets_hidden": self.state.hidden_secrets,
                "secrets_revealed": self.state.revealed_secrets,
            }
            # 第一个 tick 生成序幕
            if current_tick <= 1:
                payload["is_opening"] = True
                payload["characters"] = (
                    "苏晚晴——别墅女主人，三十五岁，优雅从容，心思缜密。丈夫三年前失踪。\n"
                    "江策——前刑警，四十二岁，现在是私家侦探。沉默寡言，观察力极强。\n"
                    "顾言——二十八岁油画家，苏晚晴亡夫的表弟。性格张扬，言辞犀利。\n"
                    "钟叔——六十岁老管家，在苏家服务四十年，忠诚而深沉。"
                )
            # 传入近期旁白历史用于去重
            payload["recent_narrations"] = self._narration_history[-5:] if hasattr(self, "_narration_history") and self._narration_history else []
            result = await bus.send(to="llm", type="llm_director_narration", payload=payload)
            if result and result.get("narration"):
                return result["narration"]
        except Exception:
            pass
        return None

    # ============================================================
    # 场景目标生成
    # ============================================================

    async def _generate_scene_goal(self, current_tick: int, recent_events: List[str] = None):
        """生成场景目标和旁白。优先用导演 LLM，回退模板。返回 (SceneGoal, narration_or_None)。"""
        if (
            self.state.scene_goal is not None
            and self.state.scene_goal_elapsed_ticks < self.state.scene_goal.duration_ticks
        ):
            return self.state.scene_goal, None

        self.state.scene_goal_elapsed_ticks = 0

        # 尝试 LLM — 同时获取 scene_goal 和 narration
        try:
            player_note = getattr(self.state, "_last_player_text", "")
            result = await bus.send(to="llm", type="llm_director_decide", payload={
                "tension": self.state.current_tension.label(),
                "convergence": self.state.convergence_factor,
                "secrets_hidden": self.state.hidden_secrets,
                "secrets_revealed": self.state.revealed_secrets,
                "pending_events": self.get_upcoming_events(),
                "recent_events": recent_events or [],
                "narration_history": [self._last_narration_text] if self._last_narration_text else [],
                "player_text": player_note,
            })
            if result and result.get("scene_goal"):
                goal = SceneGoal(
                    description=result["scene_goal"],
                    duration_ticks=5,
                    priority=1,
                )
                narration = result.get("narration") or None
                self.state.log_decision(current_tick, "scene_goal_update_llm", {
                    "goal": goal.description[:50],
                })
                return goal, narration
        except Exception:
            pass

        # 回退模板
        secrets_remaining = len(self.state.hidden_secrets)
        secrets_revealed = len(self.state.revealed_secrets)
        pending_events = len(self.state.scheduled_events)
        convergence = self.state.convergence_factor

        tension = self.state.current_tension
        if tension == TensionLevel.CALM:
            desc = "维持当前平静氛围。让角色自然地互动、探索环境、建立关系。鼓励信息交流，但不要引发直接冲突。"
            if secrets_revealed == 0 and secrets_remaining > 0:
                desc += f"（当前有 {secrets_remaining} 个未曝光的秘密等待发现）"
            goal = SceneGoal(description=desc, duration_ticks=5, priority=0)
        elif tension == TensionLevel.TENSE:
            desc = "增加角色之间的猜疑和暗流涌动。可以引发小摩擦和信息的战略性隐瞒。让每个角色都感到不安全感。"
            if pending_events > 0:
                desc += f"（{pending_events} 个事件即将发生，推动角色靠近冲突中心）"
            goal = SceneGoal(description=desc, duration_ticks=5, priority=1)
        elif tension == TensionLevel.CRISIS:
            desc = "危机已经爆发。迫使角色做出关键选择和表态。没有人可以继续中立。矛盾需要直面，不能回避。"
            if secrets_remaining > 0:
                desc += f"（尚有 {secrets_remaining} 个秘密可被揭露，加快信息释放）"
            goal = SceneGoal(description=desc, duration_ticks=5, priority=2)
        elif tension == TensionLevel.RESOLUTION:
            desc = "引导故事走向真相的揭示和最终收束。关键证据应该浮出水面，角色的动机应该变得清晰。准备迎接结局。"
            if secrets_revealed > 0:
                desc += f"（已揭露 {secrets_revealed} 个秘密，收束度 {convergence:.0%}）"
            goal = SceneGoal(description=desc, duration_ticks=5, priority=3)
        else:
            goal = SceneGoal(description="自然推进故事发展。", duration_ticks=5)

        self.state.log_decision(current_tick, "scene_goal_update", {
            "tension": self.state.current_tension.label(),
            "goal": goal.description[:50],
        })

        return goal, None

    # ============================================================
    # 事件触发
    # ============================================================

    async def _trigger_event(
        self, event: NarrativeEvent, current_tick: int
    ) -> None:
        """
        触发一个叙事事件并执行对应的世界状态变更。
        """
        logger.info(
            f"[DirectorService] 触发事件: type={event.type}, "
            f"id={event.id[:8]}, desc={event.description}"
        )

        # 记录到触发历史
        self.state.record_triggered_event(event)

        # 判断是否是"核心事件"
        core_event_types = {
            "murder", "revelation", "confrontation",
            "new_arrival", "convergence_trigger"
        }
        is_core_event = event.type in core_event_types
        if is_core_event:
            self.state.last_core_event_tick = current_tick
            self.convergence.advance_convergence(
                self.state, delta=0.1, reason=f"core_event:{event.type}",
            )

        # ── 执行世界状态变更 ──────────────────────────────
        self._apply_event_to_world(event)

        # ── 推送 narrative_event 给前端 ────────────────────
        await self._event_bus.publish("narrative_event", {
            "tick": current_tick,
            "description": event.description,
            "timestamp": int(time.time()),
            "event_type": event.type,
        })

        # ── 写入全局记忆（让 NPC 感知到事件发生） ──────────
        try:
            await bus.send(to="memory", type="add_memory", payload={
                "world_id": "default_world",
                "content": f"【全局事件】{event.description}",
                "tick": current_tick,
                "importance": 0.9,
                "emotion_tag": "平静",
                "scope": "global",
            })
        except Exception:
            pass

        # ── 推送 directive 给角色后端 ──────────────────────
        await self._publish_directive(current_tick, triggered_event=event)

    def _apply_event_to_world(self, event: NarrativeEvent) -> None:
        """根据事件类型执行对应的世界状态变更。"""
        gt = self._ground_truth
        affected = event.affected_locations or []
        if not affected:
            # 全局事件影响所有地点
            affected = list(gt.get_all_locations().keys())

        if event.type == "blackout":
            for loc_id in affected:
                loc = gt.get_location(loc_id)
                if loc:
                    gt.add_event_log(f"[{loc.name}] 停电，陷入一片黑暗")
        elif event.type == "murder":
            location = event.metadata.get("location", "study")
            victim = event.metadata.get("victim", "unknown")
            gt.add_event_log(f"[{location}] 谋杀发生！受害者: {victim}")
            # 标记地窖钥匙等相关物品
            for item_id, item in gt.get_all_items().items():
                if getattr(item, "is_key_item", False):
                    item.is_hidden = False
        elif event.type == "broadcast":
            msg = event.metadata.get("message", event.description)
            gt.add_event_log(f"[广播] {msg}")
        elif event.type == "alarm":
            gt.add_event_log(f"[警报] {event.description}")
        elif event.type == "weather_change":
            weather = event.metadata.get("weather", "stormy")
            gt.add_event_log(f"[天气] 天气变为: {weather}")
        elif event.type == "revelation":
            clue = event.metadata.get("clue", event.description)
            gt.add_event_log(f"[揭示] {clue}")
        elif event.type == "new_arrival":
            gt.add_event_log(f"[新角色] {event.description}")
        elif event.type == "discovery":
            evidence = event.metadata.get("evidence_type", "clue")
            loc = event.metadata.get("location", "unknown")
            gt.add_event_log(f"[发现] 在{loc}发现了{evidence}")
        else:
            gt.add_event_log(f"[事件] {event.description}")

    # ============================================================
    # EventBus 推送封装
    # ============================================================

    async def _publish_directive(
        self,
        current_tick: int,
        triggered_event: Optional[NarrativeEvent] = None,
    ) -> None:
        """
        推送 directive 消息给角色后端和前端。
        
        directive 消息格式（来自接口文档）：
        {
            "type": "directive",
            "rhythm": { "tension": int, "target": str },
            "scheduledEvent": { "type": str, "triggerTime": int } | null
        }
        
        前端接收后：更新导演状态面板（紧张度指示器等）
        角色后端接收后：调整 Agent 的行为倾向
        
        Args:
            current_tick: 当前 tick
            triggered_event: 刚触发的事件（如果有的话）
        """
        # 构造 scheduledEvent 字段
        # 如果有刚触发的事件，带上事件信息；否则取队列里下一个待触发的事件
        scheduled_event_payload = None
        if triggered_event:
            scheduled_event_payload = {
                "type": triggered_event.type,
                "triggerTime": triggered_event.scheduled_tick,
                "description": triggered_event.description,
            }
        elif self.state.scheduled_events:
            next_event = self.state.scheduled_events[0]
            scheduled_event_payload = {
                "type": next_event.type,
                "triggerTime": next_event.scheduled_tick,
                "description": next_event.description,
            }

        payload = {
            "type": "directive",
            "rhythm": {
                "tension": int(self.state.current_tension),
                "target": self.state.current_tension.label(),
            },
            "scheduledEvent": scheduled_event_payload,
        }

        await self._event_bus.publish("directive", payload)

    # ============================================================
    # REST API 对外接口
    # ============================================================

    def get_status(self) -> Dict[str, Any]:
        """
        获取当前导演状态，供 REST API 返回给前端。
        
        对应接口文档：
          GET /director/status
          返回：{ tension, target, phase, narrativeStage, intensity }
          
        Returns:
            dict: 导演状态摘要
        """
        return {
            "tension": int(self.state.current_tension),
            "target": self.state.current_tension.label(),
            "phase": cn_phase(self._get_narrative_phase(0).get("name", "")),
            "narrativeStage": self._get_narrative_stage(),
            "intensity": float(self.state.convergence_factor),
            "hiddenSecrets": len(self.state.hidden_secrets),
            "revealedSecrets": len(self.state.revealed_secrets),
            "pendingEvents": len(self.state.scheduled_events),
        }

    def get_state(self) -> DirectorState:
        """
        获取导演完整状态对象（供内部模块使用）。
        
        Returns:
            DirectorState: 当前完整状态
        """
        return self.state

    # ============================================================
    # 章节管理
    # ============================================================

    async def _maybe_create_chapter(
        self, current_tick: int,
        due_events: list = None,
        revealed_secret: str = None,
    ) -> None:
        """在关键时刻自动划分新章节。优先使用LLM生成有故事衔接感的标题。"""
        due_events = due_events or []

        # ── 结束上一章 ──
        if self._chapters:
            prev = self._chapters[-1]
            prev.end_tick = current_tick
            prev.summary = await self._summarize_chapter(prev)

        # ── 回溯重命名第一章（当创建第二章时，用已积累的对话为第一章生成标题）──
        if len(self._chapters) == 1:
            ch1 = self._chapters[0]
            ch1_dialogues = list(self._chapter_dialogue_snippets)
            ch1_events = list(self._chapter_event_log)
            ch1_llm_title = await self._llm_chapter_title(
                chapter_num=1,
                events=ch1_events[-8:],
                dialogues=ch1_dialogues[-16:],
                prev_title="",
                character_names=self._get_character_names(),
            )
            if ch1_llm_title:
                ch1.title = f"第一章：{ch1_llm_title}"
            else:
                ch1.title = self._fallback_chapter_title(
                    1,
                    dialogue_snippets=ch1_dialogues,
                    due_events=None,
                    revealed_secret=None,
                )
            # 同步更新时间线节点（add_node 按 node_id 去重，天然支持更新）
            if self._timeline_store:
                try:
                    self._timeline_store.add_node({
                        "node_id": ch1.id,
                        "tick": ch1.start_tick,
                        "title": ch1.title,
                        "summary": ch1.summary or "",
                        "tension": TensionLevel[ch1.tension].label() if ch1.tension in TensionLevel.__members__ else ch1.tension,
                        "key_events": ch1.key_events or [],
                    })
                except Exception as e:
                    logger.warning(f"[DirectorService] 第一章标题时间线同步失败: {e}")
            logger.info(f"[DirectorService] 第一章回溯重命名: {ch1.title}")

        chapter_num = len(self._chapters) + 1

        # ── 收集LLM上下文 ──
        context_events = list(self._chapter_event_log[-8:])
        context_dialogues = list(self._chapter_dialogue_snippets[-16:])
        prev_title = self._chapters[-1].title if self._chapters else ""

        # 收集角色名
        character_names = self._get_character_names()

        # ── 尝试LLM生成标题 ──
        llm_title = await self._llm_chapter_title(
            chapter_num=chapter_num,
            events=context_events,
            dialogues=context_dialogues,
            prev_title=prev_title,
            character_names=character_names,
        )

        if llm_title:
            title = f"第{chapter_num}章：{llm_title}"
        else:
            # 回退：优先从对话片段提取，次选事件/秘密/紧张度
            title = self._fallback_chapter_title(
                chapter_num,
                dialogue_snippets=context_dialogues,
                due_events=due_events,
                revealed_secret=revealed_secret,
            )

        chapter = Chapter(
            id=f"chapter_{chapter_num}",
            number=chapter_num,
            title=title,
            start_tick=current_tick,
            key_events=list(self._chapter_event_log[-5:]),
            tension=self.state.current_tension.name,
        )
        self._chapters.append(chapter)
        self._current_chapter_start_tick = current_tick
        self._chapter_event_log = []
        self._chapter_dialogue_snippets = []

        # ── 同步到时间线节点 ──
        if self._timeline_store:
            try:
                import uuid
                self._timeline_store.add_node({
                    "node_id": chapter.id,
                    "tick": chapter.start_tick,
                    "title": chapter.title,
                    "summary": chapter.summary or "",
                    "tension": TensionLevel[chapter.tension].label() if chapter.tension in TensionLevel.__members__ else chapter.tension,
                    "key_events": chapter.key_events or [],
                })
            except Exception as e:
                logger.warning(f"[DirectorService] 时间线节点写入失败: {e}")

        # ── 同步到统一章节对话存储 ──
        if self._dialogue_store:
            try:
                self._dialogue_store.start_chapter(chapter.id, chapter.start_tick)
            except Exception as e:
                logger.warning(f"[DirectorService] 对话存储章节同步失败: {e}")

        logger.info(f"[DirectorService] 新章节: {title} (tick={current_tick})")

    async def _llm_chapter_title(
        self,
        chapter_num: int,
        events: list,
        dialogues: list,
        prev_title: str,
        character_names: list,
    ) -> Optional[str]:
        """调用LLM生成有故事衔接感的章节标题。失败时重试一次，两次都失败返回None。"""
        import asyncio

        for attempt in range(2):
            try:
                result = await bus.send(to="llm", type="llm_director_chapter", payload={
                    "chapter_num": chapter_num,
                    "events": events,
                    "recent_dialogues": dialogues,
                    "tension": self.state.current_tension.label(),
                    "secrets_revealed": self.state.revealed_secrets[-3:] if self.state.revealed_secrets else [],
                    "character_names": character_names,
                    "prev_chapter_title": prev_title,
                })
                if result and result.get("title"):
                    t = result["title"].strip()
                    # 清理可能残留的"第X章："前缀
                    for prefix in [f"第{chapter_num}章：", f"第{chapter_num}章:", f"第{chapter_num}章 "]:
                        if t.startswith(prefix):
                            t = t[len(prefix):]
                    # 检测是否为中文标题（中文占比低于50%视为英文，拒绝）
                    chinese_chars = sum(1 for c in t if '一' <= c <= '鿿')
                    if chinese_chars / max(len(t), 1) < 0.5:
                        logger.info(f"[DirectorService] LLM返回非中文标题'{t}'，回退到中文模板")
                        break  # 不重试，直接用回退
                    if 3 <= len(t) <= 25:
                        return t
                    # 标题长度不合格，重试
                    if attempt == 0:
                        logger.info(
                            f"[DirectorService] LLM章节标题长度异常(len={len(t)})，重试中..."
                        )
                        await asyncio.sleep(0.5)
                        continue
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[DirectorService] LLM章节命名失败(第1次): {e}，重试中...")
                    await asyncio.sleep(0.5)
                else:
                    logger.warning(f"[DirectorService] LLM章节命名失败(第2次): {e}")
        return None

    def _fallback_chapter_title(
        self, chapter_num: int,
        dialogue_snippets: list = None,
        due_events: list = None,
        revealed_secret = None,
    ) -> str:
        """LLM不可用时的回退标题生成，优先使用对话内容提取关键短语。"""
        dialogue_snippets = dialogue_snippets or []
        due_events = due_events or []

        # 1. 优先从对话片段中提取有意义的短语
        if dialogue_snippets:
            last_dialogues = dialogue_snippets[-6:]
            for snippet in reversed(last_dialogues):
                parts = snippet.split("：", 1)
                if len(parts) == 2:
                    name, text = parts
                    # 清理省略号，取前10个有意义字符
                    short = text.replace("……", "").replace("...", "").replace("…", "").strip()[:10]
                    if len(short) >= 3 and "事件" not in short:
                        return f"第{chapter_num}章：{name}的{short}"

        # 2. 回退到事件描述
        if due_events:
            ev = due_events[0]
            desc = ev.description[:20] if ev.description else self._event_type_label(ev.type)
            return f"第{chapter_num}章：{desc}"
        if revealed_secret:
            label = self._secret_label(revealed_secret)
            return f"第{chapter_num}章：{label}浮出水面"

        # 3. 最终回退：紧张度模板
        tension = self.state.current_tension
        if tension == TensionLevel.TENSE:
            return f"第{chapter_num}章：暗流涌动"
        elif tension == TensionLevel.CRISIS:
            return f"第{chapter_num}章：危机降临"
        elif tension == TensionLevel.RESOLUTION:
            return f"第{chapter_num}章：真相浮现"
        return f"第{chapter_num}章：疑云渐起"

    async def _summarize_chapter(self, chapter) -> str:
        """生成章节摘要：优先LLM，回退模板。"""
        events = chapter.key_events or []
        if not events:
            return "故事在平静中推进。"

        character_names = self._get_character_names()
        # 快照对话片段，避免竞态
        snippets = list(self._chapter_dialogue_snippets[-8:])
        if not snippets and events:
            logger.debug("[DirectorService] 章节摘要LLM无对话上下文，依赖纯事件。")

        # 尝试LLM
        try:
            result = await bus.send(to="llm", type="llm_director_chapter_summary", payload={
                "events": events,
                "recent_dialogues": snippets,
                "chapter_title": chapter.title,
                "tension": TensionLevel[chapter.tension].label() if chapter.tension in TensionLevel.__members__ else chapter.tension,
                "character_names": character_names,
            })
            if result and result.get("summary") and len(result["summary"].strip()) >= 5:
                return result["summary"].strip()
        except Exception:
            pass

        # 回退
        first = events[0][:40] if events else ""
        last = events[-1][:40] if len(events) > 1 else ""
        if first and last and first != last:
            return f"从「{first}」到「{last}」，故事逐渐推进。"
        return f"「{first}」——这一章的关键转折。"

    def get_chapters(self) -> list:
        """返回所有已完成章节 + 当前进行中章节。"""
        result = []
        for ch in self._chapters:
            d = ch.model_dump()
            d["tension"] = TensionLevel[ch.tension].label() if ch.tension in TensionLevel.__members__ else ch.tension
            result.append(d)
        if self._chapters:
            result[-1]["end_tick"] = None
            result[-1]["summary"] = "进行中..."
        return result

    # ── 章节辅助方法 ──

    def _get_character_names(self) -> list:
        """获取当前所有角色名。回退到已知角色列表。"""
        # 尝试从belief_system获取agent_id列表
        try:
            if self._belief and hasattr(self._belief, '_beliefs'):
                # _beliefs 的 key 格式可能包含名字信息
                pass
        except Exception:
            pass
        # 回退：已知的演示角色
        return ["苏晚晴", "江策", "顾言", "钟叔"]

    def _event_type_label(self, event_type: str) -> str:
        labels = {
            "blackout": "停电", "broadcast": "广播通知", "alarm": "警报",
            "murder": "谋杀发生", "weather_change": "天气变化",
            "new_arrival": "新角色登场", "convergence_trigger": "叙事收束",
            "confrontation": "正面冲突", "revelation": "真相揭露", "discovery": "关键发现",
        }
        return labels.get(event_type, "未知事件")

    def _resolve_location_names(self, location_ids: list) -> list:
        try:
            locs = self._ground_truth.get_all_locations() if hasattr(self._ground_truth, 'get_all_locations') else {}
            return [locs[lid].name for lid in location_ids if lid in locs and hasattr(locs[lid], 'name')]
        except Exception:
            return []

    def _resolve_agent_names(self, agent_ids: list) -> list:
        """将agent_id解析为可读名称。"""
        known_names = {
            "suwanqing": "苏晚晴", "jiangce": "江策",
            "guyan": "顾言", "zhongshu": "钟叔",
            "player": "玩家",
        }
        return [known_names.get(aid, aid) for aid in agent_ids]

    def _secret_label(self, secret_key: str) -> str:
        labels = {
            "victim_past": "受害者的过往", "murderer_identity": "凶手身份",
            "secret_room": "密室之谜", "hidden_motive": "隐藏动机",
            "betrayal": "背叛真相", "poison": "毒药线索",
            "affair": "隐秘关系", "inheritance": "遗产纠葛",
            "forged_letter": "伪造信件", "missing_will": "失踪遗嘱",
        }
        return labels.get(secret_key, "未解之谜")

    def get_upcoming_events(self) -> List[Dict[str, Any]]:
        """
        获取即将触发的事件列表，供 REST API 返回给前端。
        
        对应接口文档：
          GET /director/upcoming_events
          返回：[{ type, description, triggerTime, probability }]
          
        Returns:
            List[dict]: 事件摘要列表
        """
        return self.event_scheduler.get_upcoming_events_summary(self.state)

    # ============================================================
    # 私有辅助方法
    # ============================================================

    def _get_narrative_phase(self, tick: int = 0) -> dict:
        """
        根据收束因子 + 秘密揭露进度返回叙事阶段（替代硬编码6幕）。
        返回与 world_simulator 兼容的 phase dict：{name, goal, deadline, reveal}

        Args:
            tick: 当前 tick（用于上下文判断）

        Returns:
            dict: 阶段描述字典
        """
        factor = self.state.convergence_factor
        revealed = len(self.state.revealed_secrets) if hasattr(self.state, "revealed_secrets") else 0
        total = len(getattr(self.state, "all_secrets", {}))
        # 从 StoryState 获取补充信息（如果有引用）
        tension = self.state.current_tension.label() if hasattr(self.state, "current_tension") else "normal"

        # ── 收敛因子驱动的阶段映射 ──
        # 早期：建立悬念 → 中期：揭露线索/推进冲突 → 后期：真相浮现/收束
        if factor < 0.2:
            return {
                "name": "第一幕：建立悬念",
                "goal": "角色对异常事件做出反应，抛出问题，建立人物关系和氛围。",
                "deadline": "不要急于揭露核心秘密。",
                "reveal": "",
            }
        elif factor < 0.4:
            return {
                "name": "第二幕：线索浮现",
                "goal": "揭露第一条线索，有人发现了具体的东西——实物证据、矛盾的说辞、可疑的痕迹。",
                "deadline": "线索应来自角色而非旁白。",
                "reveal": f"已揭露 {revealed}/{total} 个秘密" if total > 0 else "",
            }
        elif factor < 0.6:
            return {
                "name": "第三幕：冲突升级",
                "goal": "角色间的猜疑加深，矛盾浮现。揭露次要秘密，推动角色站队和对立。",
                "deadline": "至少一个角色应在压力下露出破绽。",
                "reveal": f"紧张度: {tension}" if tension != "normal" else "",
            }
        elif factor < 0.8:
            return {
                "name": "第四幕：证据公开",
                "goal": "关键证据指向真相。持有信息的角色公开他们掌握的线索。",
                "deadline": "至少一条关键证据应在本阶段公开。",
                "reveal": f"已揭露 {revealed}/{total} 个秘密" if total > 0 else "",
            }
        else:
            return {
                "name": "第五幕：真相浮现",
                "goal": "所有碎片拼在一起，核心真相浮出水面。角色做出最终选择。",
                "deadline": "",
                "reveal": "核心真相即将揭露" if revealed >= total else "",
            }

    def _get_narrative_stage(self) -> str:
        """
        返回叙事阶段的中文描述（给前端展示用）。
        
        Returns:
            str: 阶段描述
        """
        phase_dict = self._get_narrative_phase(0)
        return phase_dict.get("name", "进行中") if isinstance(phase_dict, dict) else str(phase_dict)


# ============================================================
# Mock EventBus（仅用于测试和开发环境）
# ============================================================

class _MockEventBus:
    """
    Mock EventBus，在没有真实 EventBus 时使用。
    仅打印日志，不做真实推送。
    
    真实的 EventBus 在 backend/core/event_system/event_bus.py 中实现。
    生产环境通过依赖注入传入真实实例：
    
      director = DirectorService(
          ground_truth=gt,
          belief_system=bs,
          event_bus=real_event_bus,   # ← 传入真实 EventBus
      )
    """

    async def publish(self, event_type: str, data: dict) -> None:
        """模拟发布事件（只打日志）"""
        logger.debug(f"[MockEventBus] 发布事件: type={event_type}, data={data}")