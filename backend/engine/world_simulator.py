# ============================================================
# simulator/world_simulator.py —— World Simulator（完全修复稳定版）
# ============================================================

from typing import Dict, List, Optional, Any
import asyncio
import logging

from backend.engine.rule_engine import RuleEngine
from backend.engine.intent_resolver import IntentResolver

from backend.engine.ground_truth import GroundTruthManager
from backend.modules.character.belief_system import BeliefSystem
from backend.modules.character.player_influence import PlayerInfluenceSystem

from backend.modules.memory.memory_system import MemorySystem
from backend.engine.agent_runtime import AgentRuntime

from backend.framework.event_bus import global_event_bus
from backend.framework.bus import bus
from backend.model.agent import AgentState
from backend.utils.i18n import cn_emotion, cn_action_type, cn_location
from backend.modules.narrative.story_state import StoryEvent

logger = logging.getLogger(__name__)


# ============================================================
# 🧩 WorldCommand（统一世界修改协议）
# ============================================================

class WorldCommand:
    """
    所有对世界的修改必须通过 Command 进行
    （禁止直接修改 world truth / agent object）
    """
    def __init__(self, type: str, payload: Dict[str, Any]):
        self.type = type
        self.payload = payload


# ============================================================
# 🌍 WorldSimulator 主类
# ============================================================

class WorldSimulator:
    """
    世界模拟器（核心物理引擎）
    """

    def __init__(
        self,
        ground_truth: GroundTruthManager,
        belief_system: BeliefSystem,
        player_influence: PlayerInfluenceSystem,
        memory_system: MemorySystem,
    ):
        # 世界核心状态系统
        self._ground_truth = ground_truth
        self._belief = belief_system
        self._player_influence = player_influence
        self._memory = memory_system

        # 核心引擎模块
        self.rule_engine = RuleEngine(ground_truth.get_truth())
        self.intent_resolver = IntentResolver(
            self.rule_engine,
            ground_truth,
            belief_system
        )

        # 外部依赖注入
        self._director = None
        self._agent_runtime: Optional[AgentRuntime] = None
        self._character_runtime = None
        self._timeline_store = None  # TimelineStore（时间线模块）
        self._dialogue_store = None          # 旧 DialogueStore（供快照恢复兼容）
        self._chapter_dialogue_store = None  # ChapterDialogueStore（统一章节对话存储）

        # 运行状态
        self._is_running = False
        self._tick_count = 0
        self._recent_events: List[str] = []
        self._last_tick_dialogues: List[Dict[str, Any]] = []

    # ============================================================
    # 🔌 依赖注入
    # ============================================================

    def set_director(self, director: Any) -> None:
        self._director = director
        logger.info("Director 已注入 WorldSimulator")

    def set_character_runtime(self, chr_runtime) -> None:
        self._character_runtime = chr_runtime
        logger.info("CharacterRuntime 已注入 WorldSimulator")

    def set_timeline_store(self, store) -> None:
        self._timeline_store = store
        logger.info("TimelineStore 已注入 WorldSimulator")

    def set_narrative_layer(self, story_state, plot_manager, validator) -> None:
        self._story_state = story_state
        self._plot_manager = plot_manager
        self._validator = validator
        logger.info("叙事逻辑层已注入 WorldSimulator")


    def register_agent(self, agent: AgentState) -> None:
        if self._agent_runtime is None:
            self._agent_runtime = AgentRuntime({})
        self._agent_runtime.add_agent(agent)
        if self._character_runtime is not None:
            self._character_runtime.register_agent(agent)

    # ============================================================
    # ▶️ 世界运行控制
    # ============================================================

    async def start(self):
        self._is_running = True
        # 从统一章节存储恢复最近对话缓存（供 /feed 增量使用）
        if self._chapter_dialogue_store is not None:
            self._last_tick_dialogues = self._chapter_dialogue_store.get_recent(500)
            stats = self._chapter_dialogue_store.get_stats()
            logger.info(
                f"已恢复 {len(self._last_tick_dialogues)} 条最近对话 "
                f"(共 {stats['total_dialogues']} 条, {stats['chapter_count']} 个章节)"
            )
        logger.info("WorldSimulator 启动")

    async def pause(self):
        self._is_running = False

    # ============================================================
    # 🧠 Tick 主循环（核心）
    # ============================================================

    async def tick(self, player_intents: Optional[List[Dict]] = None) -> Dict:
        if not self._is_running:
            return {"status": "paused"}

        import time as _time

        # 防止并发 tick + 超时保护
        if getattr(self, "_tick_in_progress", False):
            tick_started = getattr(self, "_tick_started_at", 0)
            if tick_started > 0 and _time.time() - tick_started > 60:
                logger.error(f"上一次 tick 超时（{_time.time() - tick_started:.0f}s），强制重置锁")
                self._tick_in_progress = False
            elif player_intents:
                # 玩家干预：等待当前 tick 完成后执行（最多等 10 秒）
                for _ in range(100):
                    await asyncio.sleep(0.1)
                    if not getattr(self, "_tick_in_progress", False):
                        break
                if getattr(self, "_tick_in_progress", False):
                    logger.warning("等待 tick 完成超时，跳过玩家干预")
                    return {"status": "skipped", "reason": "tick_in_progress"}
            else:
                return {"status": "skipped", "reason": "tick_in_progress"}
        self._tick_in_progress = True
        self._tick_started_at = _time.time()

        try:
            return await asyncio.wait_for(self._do_tick(player_intents), timeout=45)
        except asyncio.TimeoutError:
            logger.error(f"Tick {self._tick_count + 1} 超时（45秒），跳过")
            return {"status": "timeout", "tick": self._tick_count}
        except Exception as e:
            logger.exception(f"Tick 异常: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._tick_in_progress = False

    async def _do_tick(self, player_intents: Optional[List[Dict]] = None) -> Dict:
        self._tick_count += 1

        # 首 tick 修正：第一章 start_tick 从 0 → 1（tick 0 无实际内容）
        if self._tick_count == 1 and self._director:
            for ch in self._director._chapters:
                if ch.start_tick == 0:
                    ch.start_tick = 1
                    # 同步更新 timeline node
                    if self._timeline_store:
                        self._timeline_store.add_node({
                            "node_id": ch.id, "tick": 1,
                            "title": ch.title, "summary": ch.summary or "",
                            "tension": ch.tension, "key_events": ch.key_events or [],
                        })
                    break

        # 0️⃣ 玩家神谕预处理（先于导演和角色决策）
        player_directive = ""
        player_text = ""
        intervention_effectiveness = 1.0
        intervention_narration = ""
        intervention_target = "all"
        intervention_type = "persuasion"
        intervention_intent_type = "other"
        if player_intents and self._director:
            intervention_target = player_intents[0].get("target") or "all"
            intervention_type = player_intents[0].get("frontend_type") or player_intents[0].get("metadata", {}).get("intervention_type", "persuasion")
            player_text = "；".join(
                i.get("dialogue", "") or i.get("content", "") or i.get("action", "")
                for i in player_intents
            ).strip()
            if player_text:
                try:
                    intervention = await self._director.receive_intervention(player_text)
                    player_directive = intervention.get("player_directive", "")
                    intervention_effectiveness = intervention.get("effectiveness", 1.0)
                    intervention_narration = intervention.get("narration_hint", "") or intervention.get("narrative_response", "")
                    intervention_intent_type = intervention.get("intent_type", "other")
                except Exception:
                    pass

        # 1️⃣ Director 决策（影响叙事方向）
        director_goal = None
        director_narration = None
        if self._director:
            try:
                director_result = await self._director.update(
                    current_tick=self._tick_count,
                    recent_events=self._recent_events[-10:],
                    player_active=bool(player_intents),
                    player_text=player_text,
                )
                if isinstance(director_result, dict):
                    director_goal = director_result.get("scene_goal")
                    director_narration = director_result.get("narration")
                else:
                    director_goal = director_result
            except Exception as e:
                logger.exception(f"Director error: {e}")

        # 2️⃣ 导演事件 → 唤醒 NPC
        if self._character_runtime and self._director:
            triggered = getattr(self._director.state, "triggered_events", [])
            for event in triggered[-3:]:
                for agent_id in self._character_runtime.get_all_agents():
                    self._character_runtime.wake_agent(agent_id, event.description)
            if director_goal:
                goal_desc = getattr(director_goal, "description", "自然推进剧情")
                for agent_id in self._character_runtime.get_all_agents():
                    self._character_runtime.wake_agent(agent_id, f"导演指令：{goal_desc}")
            if player_directive:
                agents = self._character_runtime.get_all_agents()
                if intervention_target in agents:
                    self._character_runtime.wake_agent(intervention_target, f"玩家对你说：「{player_text}」")
                else:
                    for agent_id in agents:
                        self._character_runtime.wake_agent(agent_id, f"玩家向现场发出指令：「{player_text}」")

        # 3️⃣ 叙事层：角色独立决策（替代统一场景生成）
        # 每个角色带着自己的记忆、认知、目标独立调用 LLM 决策
        agent_intents = []
        fix_hints = getattr(self, "_fix_hints", "")
        try:
            dialogue_history = []
            for d in self._last_tick_dialogues[-15:]:
                name = d.get("speakerName", d.get("agent_name", ""))
                content = d.get("content", "")
                if name and content:
                    dialogue_history.append(f"{name}: {content}")

            # 角色目标（博弈模型）
            character_goals = {
                "苏晚晴": "弄清三年前丈夫失踪的真相。试探钟叔是否知情，观察江策掌握了多少",
                "江策": "证明三年前苏先生不是失踪而是谋杀。逼钟叔松口，同时不让苏晚晴察觉自己知道多少",
                "顾言": "拿到画室里藏的一样东西。用艺术话题转移注意力，不让其他人发现自己的真实意图",
                "钟叔": "阻止任何人今晚进入画室。用恭敬回避的方式拖延、撒谎、转移焦点",
            }

            # 信息差——两层知识结构
            surface_knowledge = {
                "苏晚晴": ["画室那幅画的眼睛是空白的", "楼上今晚似乎有动静", "丈夫失踪前曾反常地锁了画室的门"],
                "江策": ["三年前那晚钟叔见过苏先生", "画室窗户当晚没锁，窗台没有积雪痕迹", "这不是意外——有太多巧合"],
                "顾言": ["画室颜料里掺了别的东西，气味不对", "对别墅结构很熟悉，知道一条旧楼梯", "受邀来别墅，但感觉大家都有事瞒着"],
                "钟叔": ["三年前那晚给老爷送过茶，那是最后一次见他", "画室钥匙只有两把——太太一把，老爷一把", "楼上多年不曾打扫，但今晚听到了脚步声"],
            }
            deep_secrets = {
                "苏晚晴": ["不确定丈夫是否真的死了——没有找到尸体", "怀疑在场的某个人就是凶手"],
                "江策": ["有证据指向谋杀——一份匿名信和三张现场照片", "苏先生死前一周曾联系过自己"],
                "顾言": ["自己是苏先生的私生子，今晚是来拿回属于自己的一切", "画室里藏着一份遗嘱——父亲亲手交给自己的"],
                "钟叔": ["画室里有老爷的遗嘱，自己亲手放的", "苏先生不是自己走出那扇窗的——他是被人推下去的", "知道凶手是谁，但出于恐惧和忠诚一直没说出来"],
            }

            # 知识揭示：由导演收敛因子驱动（不再硬编码 tick 阈值）
            convergence = getattr(self._director.state, "convergence_factor", 0.0) if self._director else 0.0
            if convergence < 0.2:
                reveal_count = 0
            elif convergence < 0.5:
                reveal_count = 1
            elif convergence < 0.8:
                reveal_count = 2
            else:
                reveal_count = 99

            character_knowledge = {}
            for name in surface_knowledge:
                character_knowledge[name] = list(surface_knowledge[name])
                if reveal_count > 0:
                    deep = deep_secrets.get(name, [])
                    character_knowledge[name].extend(deep[:reveal_count])

            # 阶段系统：由 Director 根据收敛因子驱动（替代原来基于 tick 数的硬编码6幕）
            phase = {}
            if self._director and hasattr(self._director, "_get_narrative_phase"):
                phase = self._director._get_narrative_phase(self._tick_count)

            # 首 tick 事件
            incident = ""
            if self._tick_count <= 1:
                incident = "晚餐刚结束。灯闪灭，三楼传来沉闷巨响。"

            # 停滞检测
            stagnation = False
            if len(dialogue_history) >= 6:
                recent = " ".join(dialogue_history[-3:])
                older = " ".join(dialogue_history[-6:-3])
                recent_words = set(recent)
                older_words = set(older)
                if len(recent_words & older_words) / max(len(recent_words), 1) > 0.5:
                    stagnation = True
                    logger.warning(f"[Tick {self._tick_count}] 检测到叙事停滞")

            # ── 首 tick：先生成开场旁白，角色对话承接旁白氛围 ──
            opening_narration = None
            if self._tick_count <= 1:
                if director_narration:
                    # 导演已在 update() 中生成了开场旁白，直接用作角色上下文
                    opening_narration = director_narration
                else:
                    # 回退：自行调用 LLM 生成开场旁白
                    try:
                        nar_result = await bus.send(to="llm", type="llm_director_narration", payload={
                            "tension": "平静",
                            "convergence": 0.0,
                            "is_opening": True,
                            "characters": "苏晚晴（女主人，三十五岁，优雅而不可捉摸）、江策（侦探，四十二岁，沉静寡言，观察力极强）、顾言（画家，二十八岁，言辞犀利，对别墅异常熟悉）、钟叔（管家，六十岁，表面恭顺，心思深沉）",
                        })
                        if nar_result and nar_result.get("narration"):
                            opening_narration = nar_result.get("narration")
                            director_narration = opening_narration
                    except Exception as e:
                        logger.exception(f"Opening narration error: {e}")

            # ── 注入上下文到 CharacterRuntime，让每个角色独立决策 ──
            if self._character_runtime:
                # 节奏控制：早期 tick 限制发言人数，逐步放开
                if self._tick_count <= 2:
                    max_speakers = 2
                elif self._tick_count <= 5:
                    max_speakers = 3
                else:
                    max_speakers = 4

                # ── 为 NPC 决策准备玩家信任快照 ──
                player_trust_context = {}
                if self._player_influence:
                    for a_id in self._character_runtime.get_all_agents():
                        inf = self._player_influence.get_influence(a_id)
                        player_trust_context[a_id] = {
                            "trust": round(inf.trust, 3),
                            "liking": round(inf.liking, 3),
                        }

                self._character_runtime.set_tick_context(
                    tick=self._tick_count,
                    phase=phase,
                    incident=incident,
                    stagnation=stagnation,
                    fix_hints=fix_hints,
                    character_goals=character_goals,
                    character_knowledge=character_knowledge,
                    dialogue_history=dialogue_history,
                    max_speakers=max_speakers,
                    opening_narration=opening_narration,
                    player_directive=player_directive,
                    player_trust=player_trust_context,
                    player_intervention={
                        "target": intervention_target,
                        "type": intervention_type,
                        "intent_type": intervention_intent_type,
                        "effectiveness": intervention_effectiveness,
                        "text": player_text,
                    } if player_directive else {},
                )
                agent_intents = await self._character_runtime.tick(
                    current_tick=self._tick_count,
                    world_id="default",
                )

                # ── 汇报 Agent 动作给导演（用于章节命名等叙事上下文） ──
                for intent in agent_intents:
                    if intent.get("type") == "speak" or intent.get("dialogue"):
                        agent = self._character_runtime.get_agent(intent.get("actor", ""))
                        agent_name = agent.name if agent else intent.get("actor", "")
                        self._director.report_agent_action(
                            agent_id=intent.get("actor", ""),
                            agent_name=agent_name,
                            action_type=intent.get("type", "speak"),
                            action=intent.get("action", intent.get("dialogue", "")[:30]),
                            target=intent.get("target", ""),
                            dialogue=intent.get("dialogue", ""),
                            thought=intent.get("thought", ""),
                            emotion=intent.get("emotion", "平静"),
                        )

                # ── NPC 间信任变化：根据对话内容分析 ──
                name_to_id: dict = {}
                for a_id, a in self._character_runtime._agents.items():
                    name_to_id[a.name] = a_id
                    name_to_id[a_id] = a_id

                for intent in agent_intents:
                    if intent.get("type") != "speak" or not intent.get("dialogue"):
                        continue
                    target_name = intent.get("target", "")
                    target_id = name_to_id.get(target_name)
                    speaker_id = intent.get("actor", "")
                    if not target_id or target_id == speaker_id:
                        continue
                    trust_delta = self._analyze_trust_impact(intent["dialogue"])
                    if abs(trust_delta) < 0.5:
                        continue
                    try:
                        await bus.send(to="memory", type="memory_relationship_update", payload={
                            "agent_id": speaker_id,
                            "target_id": target_id,
                            "delta": trust_delta,
                            "reason": f"tick_{self._tick_count}: {intent['dialogue'][:50]}",
                        })
                    except Exception as e:
                        logger.warning(f"[Trust] NPC 间信任更新失败: {e}")

                # ── 写回 Agent 状态：情绪和当前行为 ──
                for intent in agent_intents:
                    agent = self._character_runtime.get_agent(intent.get("actor", ""))
                    if agent is None:
                        continue
                    # 更新情绪
                    llm_emotion = intent.get("emotion")
                    if llm_emotion and hasattr(agent, "emotion") and agent.emotion:
                        agent.emotion.current_mood = llm_emotion
                        agent.emotion.intensity = intent.get("emotion_intensity", 0.5)
                    # 更新行为类型
                    agent.current_action = intent.get("action", agent.current_action)
                    agent.current_action_type = intent.get("type", agent.current_action_type)

                # ── Validator 校验（提取对话文本后校验） ──
                if hasattr(self, '_validator') and self._validator:
                    dialogues_for_check = []
                    for intent in agent_intents:
                        if intent.get("type") == "speak" and intent.get("dialogue"):
                            agent = self._character_runtime.get_agent(intent.get("actor", ""))
                            spk_name = agent.name if agent else intent.get("actor", "")
                            dialogues_for_check.append({"speaker": spk_name, "content": intent.get("dialogue", "")})
                    if dialogues_for_check:
                        char_names = {}
                        for aid, agent in self._character_runtime._agents.items():
                            char_names[aid] = agent.name
                        validation = self._validator.validate_scene(
                            "", dialogues_for_check, dialogue_history, char_names
                        )
                        if not validation.passed:
                            self._fix_hints = self._validator.generate_fix_hint(validation.issues)
                            logger.warning(f"[Tick {self._tick_count}] 校验问题: {validation.issues}")
                        else:
                            self._fix_hints = ""

                # ── StoryState 事件记录 + 事实追踪 ──
                if hasattr(self, '_story_state') and self._story_state:
                    for intent in agent_intents:
                        if intent.get("type") == "speak" and intent.get("dialogue"):
                            agent = self._character_runtime.get_agent(intent.get("actor", ""))
                            spk_name = agent.name if agent else intent.get("actor", "")
                            content = intent.get("dialogue", "")
                            self._story_state.record_event(StoryEvent(
                                tick=self._tick_count,
                                event_type="dialogue",
                                description=f"{spk_name}: {content[:80]}",
                                participants=[intent.get("actor", "")]
                            ))
                            # 记录发言者的事实
                            self._story_state.record_fact(spk_name, content, self._tick_count)
                            # PlotManager
                            if hasattr(self, '_plot_manager') and self._plot_manager:
                                self._plot_manager.record_speaker(spk_name)

                    # ── 更新角色认知：听到别人说话的角色获得新信息 ──
                    self._update_character_knowledge(agent_intents, character_knowledge)

                    contradiction_hint = self._story_state.get_contradiction_hint()
                    if contradiction_hint and not fix_hints:
                        self._fix_hints = contradiction_hint

            # ── 响应式旁白：根据本 tick 角色对话生成场景描写 ──
            if self._tick_count > 1 and agent_intents:
                try:
                    dialogue_texts = []
                    for intent in agent_intents:
                        if intent.get("type") == "speak" and intent.get("dialogue"):
                            agent = self._character_runtime.get_agent(intent.get("actor", "")) if self._character_runtime else None
                            name = agent.name if agent else intent.get("actor", "")
                            dialogue_texts.append(f"{name}：「{intent['dialogue']}」")
                    if dialogue_texts and self._director and hasattr(self._director, 'generate_narration_for_dialogues'):
                        responsive = await self._director.generate_narration_for_dialogues(
                            current_tick=self._tick_count,
                            dialogues=dialogue_texts,
                        )
                        if responsive:
                            director_narration = responsive
                except Exception as e:
                    logger.exception(f"Responsive narration error: {e}")

            logger.info(f"[Tick {self._tick_count}] 角色决策: {len(agent_intents)} 个意图")
        except Exception as e:
            logger.exception(f"Agent decision error: {e}")

        # 4️⃣ 合并 Player Intent（玩家意图在前，确保对话顺序正确）
        all_intents = (player_intents or []) + agent_intents

        # 4️⃣ Intent → Command → Resolve
        commands: List[WorldCommand] = []
        results = []

        for intent in all_intents:
            success, raw_update = self.intent_resolver.resolve(intent)
            if not success:
                results.append({
                    "intent": intent,
                    "success": False,
                    "reason": "resolve_failed"
                })
                continue

            # 🛠️ 经过修复的转换层：融合 intent 和 resolver 的反馈
            command = self._to_command(raw_update if raw_update else {}, intent)
            commands.append(command)

            results.append({
                "intent": intent,
                "success": True,
                "command": command.type
            })

        # 5️⃣ 应用 Command（唯一写入世界入口）
        for cmd in commands:
            self._apply_command(cmd)

        # 6️⃣ 时间推进（唯一时间源：GroundTruth）
        current_time = self._ground_truth.advance_time()
        time_dict = current_time.model_dump()

        # 7️⃣ 事件发布
        await global_event_bus.publish(
            "world:time_changed",
            tick=self._tick_count,
            time=time_dict,
        )

        if director_goal:
            await global_event_bus.publish(
                "director:goal_updated",
                tick=self._tick_count,
                goal=director_goal.model_dump() if hasattr(director_goal, "model_dump") else director_goal,
            )

        # 8️⃣ 维护 recent events 队列长度
        if len(self._recent_events) > 30:
            self._recent_events = self._recent_events[-30:]

        # 8️⃣ 玩家影响力追踪（基于本 tick 的 NPC 回应情况）
        if player_intents and self._character_runtime and self._player_influence:
            target_agent = intervention_target  # 可能是 "all" 或具体 agent_id
            all_agents = self._character_runtime.get_all_agents()
            for agent_id in all_agents:
                # 非全体干预时，只影响目标角色
                is_target = (target_agent == "all" or target_agent == agent_id)
                if not is_target:
                    continue
                # 按说服力修饰符 × 干预有效性 计算信任变化
                persuasion_mod = self._player_influence.get_persuasion_modifier(agent_id)
                trust_delta = persuasion_mod * intervention_effectiveness
                # 全体干预时效果减半
                if target_agent == "all":
                    trust_delta *= 0.5
                trust_delta = max(-0.15, min(0.15, trust_delta))  # 单次信任变化上限 ±0.15
                is_success = trust_delta > 0.01
                self._player_influence.record_interaction(agent_id, self._tick_count, success=is_success)
                self._player_influence.modify_trust(agent_id, trust_delta)

        # 9️⃣ 构造 tick 结果
        tick_result = {
            "tick": self._tick_count,
            "time": time_dict,
            "director_goal": director_goal.model_dump() if hasattr(director_goal, "model_dump") else director_goal,
            "director_narration": director_narration,
            "command_count": len(commands),
            "intent_results": results,
            "intervention_effectiveness": intervention_effectiveness,
            "intervention_narration": intervention_narration,
        }

        # 🔟 提取前端事件（extract_frontend_events 内部已追加到 _last_tick_dialogues）
        tick_result["frontend_events"] = self.extract_frontend_events(tick_result)

        # ⓫ 定期维护（每 5 tick）：信任衰减 + 记忆整合
        if self._tick_count % 5 == 0 and self._character_runtime:
            # 玩家信任自然衰减
            if self._player_influence:
                self._player_influence.decay_all(rate=0.005)
            # NPC 间信任自然衰减
            try:
                await bus.send(to="memory", type="memory_relationship_decay_all",
                               payload={"rate": 0.003})
            except Exception:
                pass
            # 长期记忆整合
            for agent_id in self._character_runtime.get_all_agents():
                await self._memory.consolidate(agent_id)

        # ⓬ 自动保存世界快照（每 5 tick + 章节边界）
        await self._auto_save_snapshot()

        return tick_result

    # ============================================================
    # 🔄 Intent → Command 转换层（核心修复点 1）
    # ============================================================

    def _to_command(self, update: Dict, intent: Dict) -> WorldCommand:
        """
        将 intent + resolver update 转换为具有明确语义的 WorldCommand。
        优先根据意图类型(intent.type)进行强映射，防止由于规则引擎返回值缺失导致指令失效。
        """
        intent_type = intent.get("type", "")
        update_type = update.get("type", "") if update else ""

        # 构建标准的意图至命令类型的映射表
        type_map = {
            "move":        "location_change",
            "speak":       "dialogue",
            "interact":    "interaction",
            "investigate": "investigation",
            "idle":        "idle",
            "generic":     "idle",      # fallback for _resolve_generic
        }

        # 优先使用显式映射，其次保留底层的特征，最后兜底 idle
        cmd_type = type_map.get(intent_type) or update_type or "idle"

        return WorldCommand(
            type=cmd_type,
            payload={
                "update": update,
                "intent": intent
            }
        )
    
    # ============================================================
    # 🧱 Command 执行（核心修复点 2：唯一写入入口）
    # ============================================================

    def _apply_command(self, cmd: WorldCommand):
        intent = cmd.payload.get("intent", {})
        update = cmd.payload.get("update", {}) or {}
        actor  = intent.get("actor", "") or update.get("agent_id", "")
        target = intent.get("target", "") or update.get("target", "")
        action = intent.get("action", "")
        agent_name = self._get_agent_name(actor)

        if self._character_runtime:
            agent = self._character_runtime.get_agent(actor)
            if agent:
                agent.current_action = action or cmd.type

        if cmd.type == "location_change":
            agent_id = update.get("agent_id") or actor
            new_location = update.get("new_location") or target
            if agent_id and new_location:
                self._ground_truth.move_agent(agent_id, new_location)
                msg = f"{agent_name} 移动到了 {new_location}"
                self._recent_events.append(msg)
                self._ground_truth.add_event_log(msg)

        elif cmd.type == "dialogue":
            dialogue = intent.get("dialogue") or intent.get("metadata", {}).get("dialogue") or action
            if dialogue:
                msg = f"{agent_name} 说: \"{dialogue}\""
                self._recent_events.append(msg)
                self._ground_truth.add_event_log(msg)

        elif cmd.type == "interaction":
            msg = f"{agent_name} 与 {target} 进行了互动：{action or '执行动作'}"
            self._recent_events.append(msg)
            self._ground_truth.add_event_log(msg)

        elif cmd.type == "investigation":
            msg = f"{agent_name} 调查了 {target}：{action or '细致观察'}"
            self._recent_events.append(msg)
            self._ground_truth.add_event_log(msg)

        elif cmd.type == "idle":
            pass

    def _update_character_knowledge(self, agent_intents: List[Dict], current_knowledge: Dict[str, List[str]]) -> None:
        """对话后更新角色认知：听到别人说话的角色获得新信息。"""
        if not hasattr(self, '_story_state') or not self._story_state:
            return

        # 构建 id→name 映射
        id_to_name = {}
        if self._character_runtime:
            for aid, agent in self._character_runtime._agents.items():
                id_to_name[aid] = agent.name

        # 收集本 tick 所有发言
        speeches = []
        for intent in agent_intents:
            if intent.get("type") == "speak" and intent.get("dialogue"):
                actor_id = intent.get("actor", "")
                actor_name = id_to_name.get(actor_id, actor_id)
                speeches.append((actor_id, actor_name, intent.get("dialogue", "")))

        # 每个发言的内容被同地点的人"听到"
        for speaker_id, speaker_name, content in speeches:
            for listener_id, listener_name in id_to_name.items():
                if listener_id == speaker_id:
                    continue
                # 简单规则：同地点的角色都能听到（后续可加入位置判断）
                summary = f"听到{speaker_name}说：「{content[:60]}」"
                if listener_id in self._story_state.character_knowledge:
                    self._story_state.character_knowledge[listener_id].known_facts.add(summary)

    def _get_agent_name(self, agent_id: str) -> str:
        """根据 agent_id 安全获取可读名字的辅助方法"""
        if agent_id == "player_01":
            return "玩家"
        if self._agent_runtime:
            agent = self._agent_runtime.get_agent(agent_id)
            if agent:
                return agent.name
        return agent_id

    # ============================================================
    # 📊 状态查询（核心修复点 3：统一多模型数据源）
    # ============================================================

    def get_state_summary(self) -> Dict:
        """
        统一世界状态摘要。
        摒弃原先简单粗暴的计数器逻辑，改为直接读取运行时及真值系统，
        使 /world/state、/world/map 以及交互层共享绝对同源的数据。
        """
        truth = self._ground_truth.get_truth()
        all_agents = self._agent_runtime.get_all_agents() if self._agent_runtime else {}

        # 1. 组装实时的 Agents 动态详情 (优先从 Runtime 内存读，确保同步)
        agents_detail = [
            {
                "id":       a.id,
                "name":     a.name,
                "location": a.location_id,
                "mood":     cn_emotion(a.emotion.current_mood) if hasattr(a, 'emotion') and hasattr(a.emotion, 'current_mood') else "平静",
                "action":   a.current_action if hasattr(a, 'current_action') else "idle",
            }
            for a in all_agents.values()
        ]

        # 2. 组装真值世界 Locations 详情
        locations_detail = [
            {
                "id":          loc.id,
                "name":        loc.name,
                "locked":      getattr(loc, 'locked', False),
                "connections": getattr(loc, 'connected_to', []),
            }
            for loc in truth.locations.values()
        ]

        # 3. 组装真值世界 Items 详情
        items_detail = [
            {
                "id":       item.id,
                "name":     item.name,
                "location": item.location_id,
            }
            for item in truth.items.values()
        ]

        return {
            "tick":          self._tick_count,
            "time":          truth.time.model_dump() if hasattr(truth.time, 'model_dump') else truth.time,
            "is_running":    self._is_running,
            "agents":        agents_detail,
            "locations":     locations_detail,
            "items":         items_detail,
            "recent_events": self._recent_events[-10:], # 返回最新10条环境事件流
        }

    def _frontend_tension(self) -> int:
        if not self._director:
            return 0
        status = self._director.get_status()
        return int(status.get("tension", 0)) * 25

    def get_frontend_world_state(self) -> Dict[str, Any]:
        truth = self._ground_truth.get_truth()
        return {
            "tick": self._tick_count,
            "time": truth.time.model_dump() if hasattr(truth.time, "model_dump") else truth.time,
            "tension": self._frontend_tension(),
        }

    def get_frontend_agents(self) -> List[Dict[str, Any]]:
        all_agents = self._agent_runtime.get_all_agents() if self._agent_runtime else {}
        return [
            {
                "id": agent.id,
                "agentId": agent.id,
                "name": agent.name,
                "state": agent.current_action or "待机",
                "actionType": cn_action_type(getattr(agent, "current_action_type", "idle")),
                "emotion": cn_emotion(agent.emotion.current_mood) if agent.emotion else "平静",
                "trustPlayer": int((self._player_influence.get_influence(agent.id).trust + 1.0) * 50) if self._player_influence else 50,
                "location": agent.location_id,
                "locationName": cn_location(agent.location_id) if hasattr(agent, "location_id") and agent.location_id else "未知",
            }
            for agent in all_agents.values()
        ]

    def set_chapter_dialogue_store(self, store) -> None:
        """注入统一章节对话存储（ChapterDialogueStore）。"""
        self._chapter_dialogue_store = store
        logger.info("ChapterDialogueStore 已注入 WorldSimulator")

    async def flush_feed_cache(self):
        """对外暴露的刷新接口（供 lifespan shutdown 调用）。"""
        if self._chapter_dialogue_store is not None:
            try:
                self._chapter_dialogue_store.flush()
            except Exception as e:
                logger.warning(f"[WorldSimulator] 对话存储刷新失败: {e}")

    async def _auto_save_snapshot(self):
        """自动保存世界快照（供 tick 循环调用）。"""
        if not self._timeline_store:
            return
        try:
            import time as _time
            from backend.timeline.snapshot import build_snapshot

            snapshot = build_snapshot(self, self._director, self._tick_count)
            self._timeline_store.save_snapshot(self._tick_count, snapshot)
        except Exception as e:
            logger.warning(f"[WorldSimulator] 自动快照保存失败 tick={self._tick_count}: {e}")

    def get_frontend_snapshot(self) -> Dict[str, Any]:
        truth = self._ground_truth.get_truth()
        agents = self.get_frontend_agents()
        rooms = []
        for loc in truth.locations.values():
            room_agents = [a["id"] for a in agents if a.get("location") == loc.id]
            rooms.append({
                "id": loc.id,
                "name": loc.name,
                "description": loc.description,
                "width": 800,
                "height": 600,
                "connectedTo": getattr(loc, "connected_to", []),
                "npcs": room_agents,
            })
        return {
            "world_state": self.get_frontend_world_state(),
            "agents": agents,
            "rooms": rooms,
            "background": "雪山别墅中的秘密、停电与互相猜疑正在缓慢发酵。",
            "summary": "女主人苏晚晴、侦探江策、画家顾言与管家钟叔被困在别墅中，每个人都带着自己的目标寻找真相。",
            "initial_quest": "推动角色调查线索，并在关键事件发生前保持叙事张力。",
        }

    def extract_frontend_events(self, tick_result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        dialogues = []
        narrative_events = []
        for result in tick_result.get("intent_results", []):
            if not result.get("success"):
                continue
            intent = result.get("intent", {}) or {}
            intent_type = intent.get("type")
            actor = intent.get("actor", "")
            agent_name = self._get_agent_name(actor)
            if intent_type == "speak":
                content = intent.get("dialogue") or intent.get("action") or ""
                if content:
                    dialogues.append({
                        "id": f"dlg_{tick_result.get('tick', self._tick_count)}_{actor}_{len(dialogues)}",
                        "speakerId": actor,
                        "speakerName": agent_name,
                        "actionType": "speak",
                        "thought": intent.get("thought", ""),
                        "content": f"\"{content}\"",
                        "emotion": self._get_agent_emotion(actor),
                    })
            # 不再为非 speak 动作生成独立旁白条目，统一由导演旁白代替
        # ── 玩家干预反馈（插入到玩家发言之后、NPC 回应之前） ──
        intervention_narration = tick_result.get("intervention_narration", "")
        intervention_eff = tick_result.get("intervention_effectiveness", 0)
        if intervention_narration and intervention_eff > 0:
            insert_pos = 0
            for i, d in enumerate(dialogues):
                if d.get("speakerId") == "player_01":
                    insert_pos = i + 1
            if insert_pos > 0:
                eff_pct = int(intervention_eff * 100)
                dialogues.insert(insert_pos, {
                    "id": f"feedback_{tick_result.get('tick', 0)}",
                    "speakerId": "system",
                    "speakerName": "系统",
                    "actionType": "feedback",
                    "tick": tick_result.get("tick", self._tick_count),
                    "thought": "",
                    "content": f"💫 {intervention_narration}（干预强度 {eff_pct}%）",
                    "emotion": "平静",
                })
        # ── 导演旁白（首 tick 插入头部作为开场，后续 tick 追加到对话之后） ──
        narration = tick_result.get("director_narration")
        if narration:
            tick_num = tick_result.get("tick", 1)
            entry = {
                "id": f"narration_{tick_result.get('tick', self._tick_count)}_{len(dialogues)}",
                "speakerId": "director",
                "speakerName": "旁白",
                "actionType": "narration",
                "tick": tick_result.get("tick", self._tick_count),
                "thought": "",
                "content": narration,
                "emotion": "平静",
            }
            if tick_num <= 1:
                dialogues.insert(0, entry)
            else:
                dialogues.append(entry)

        # ── 缓存最近对话供 /feed 轮询 + 持久化到章节存储 ──
        for d in dialogues:
            d.setdefault("tick", tick_result.get("tick", self._tick_count))
        self._last_tick_dialogues = (self._last_tick_dialogues + dialogues)[-500:]

        # 实时写入统一章节存储（替代旧 feed_cache.json）
        if self._chapter_dialogue_store is not None and dialogues:
            try:
                self._chapter_dialogue_store.append_batch(dialogues)
            except Exception as e:
                logger.error(f"[WorldSimulator] 对话写入章节存储失败: {e}")

        return {
            "world_state": [self.get_frontend_world_state()],
            "agent_state": self.get_frontend_agents(),
            "dialogue": dialogues,
            "narrative_event": narrative_events,
        }

    def _get_agent_emotion(self, agent_id: str) -> str:
        if self._agent_runtime:
            agent = self._agent_runtime.get_agent(agent_id)
            if agent and agent.emotion:
                return cn_emotion(agent.emotion.current_mood)
        return "平静"

    @staticmethod
    def _analyze_trust_impact(dialogue: str) -> float:
        """规则匹配：分析一条对话对说话者→听话者信任的影响。
        返回 -100~100 范围内的 delta 值（RelationStore trust_value 量纲）。"""
        d = dialogue
        delta = 0.0

        # ── 负面：直接指控/揭发 ──
        if any(kw in d for kw in ["你杀了", "是你干的", "凶手是你", "你撒谎", "你说谎",
                                    "你编的", "你陷害", "栽赃"]):
            delta -= 5.0
        # 中度负面：挑战/逼迫
        elif any(kw in d for kw in ["你在隐瞒", "你骗", "别装了", "你不敢说",
                                      "你心里清楚", "闭嘴", "够了", "你有什么目的"]):
            delta -= 3.0
        # 轻度负面：质疑/否定/反驳
        elif any(kw in d for kw in ["不可能", "不对", "你说什么", "怎么可能",
                                      "我不信", "我怀疑", "你说错了"]):
            delta -= 1.5

        # ── 正面：信任/支持 ──
        if any(kw in d for kw in ["我相信你", "我信你", "你没错", "我站在你这边",
                                    "你不是那种人", "我理解你", "我懂你"]):
            delta += 5.0
        # 中度正面：赞同/辩护
        elif any(kw in d for kw in ["他说得对", "有道理", "我觉得你是对的",
                                      "你不像在说谎", "我同意"]):
            delta += 3.0
        # 轻度正面：关心/共情
        elif any(kw in d for kw in ["不容易", "别担心", "我帮你", "你还好吗",
                                      "没事的"]):
            delta += 1.5

        return delta
