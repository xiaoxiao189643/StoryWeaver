# ============================================================
# modules/narrative/story_state.py —— 故事状态追踪器
# ============================================================
# 追踪：秘密揭露状态、角色认知、线索发现、时间线、故事阶段
# ============================================================

from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class StoryPhase(Enum):
    OPENING = "opening"
    INVESTIGATION = "investigation"
    CONFLICT = "conflict"
    CLIMAX = "climax"
    RESOLUTION = "resolution"


@dataclass
class Clue:
    id: str
    description: str
    location: str
    discovered_by: str = ""
    discovered_tick: int = 0
    related_secret: str = ""


@dataclass
class StoryEvent:
    tick: int
    event_type: str
    description: str
    participants: List[str] = field(default_factory=list)


@dataclass
class Fact:
    """一条可追踪的世界事实"""
    id: str
    content: str              # 事实内容
    stated_by: str            # 哪个角色说的
    stated_tick: int          # 在哪个 tick 说的
    subject: str = ""         # 主语/主题（如 "钥匙", "书房窗户", "地窖门"）
    assertion: str = ""       # 断言类型（"存在", "不存在", "可访问", "不可访问", "已知", "未知"）
    is_character_belief: bool = True  # 是角色主观认知还是客观事实


@dataclass
class Contradiction:
    """两个事实之间的矛盾"""
    fact_a: Fact
    fact_b: Fact
    description: str
    severity: str  # "critical" / "warning"


@dataclass
class CharacterKnowledge:
    """单个角色的独立认知"""
    known_facts: Set[str] = field(default_factory=set)
    known_clues: List[str] = field(default_factory=list)
    suspicions: Dict[str, str] = field(default_factory=dict)
    revealed_secrets: Set[str] = field(default_factory=set)
    # 角色独立记忆：每个角色有自己版本的世界事实
    personal_facts: List[Fact] = field(default_factory=list)


class StoryState:
    """贯穿始终的故事状态追踪器"""

    def __init__(self):
        # 秘密状态
        self.all_secrets: Dict[str, str] = {}        # id -> 描述
        self.revealed_secrets: Set[str] = set()       # 全局已揭露的秘密
        self.who_knows_secret: Dict[str, Set[str]] = {}  # secret_id -> {agent_ids}

        # 线索
        self.clues: Dict[str, Clue] = {}
        self.discovered_clues: List[str] = []

        # 角色认知
        self.character_knowledge: Dict[str, CharacterKnowledge] = {}

        # 时间线
        self.timeline: List[StoryEvent] = []

        # 故事阶段
        self.phase: StoryPhase = StoryPhase.OPENING
        self.phase_ticks: int = 0  # 当前阶段持续的 tick 数

        # 一致性约束
        self.established_facts: Set[str] = set()
        self.pending_questions: List[str] = []

        # ── 跨轮次事实追踪 ──
        self.facts: Dict[str, Fact] = {}          # fact_id -> Fact
        self.contradictions: List[Contradiction] = []  # 检测到的矛盾
        self._subject_index: Dict[str, List[str]] = {} # subject -> [fact_ids]  快速查找同主题事实

    def init_characters(self, agent_ids: List[str]):
        for aid in agent_ids:
            self.character_knowledge[aid] = CharacterKnowledge()

    def register_secret(self, secret_id: str, description: str):
        self.all_secrets[secret_id] = description

    def register_clue(self, clue: Clue):
        self.clues[clue.id] = clue

    def discover_clue(self, clue_id: str, agent_id: str, tick: int):
        if clue_id in self.clues and clue_id not in self.discovered_clues:
            self.discovered_clues.append(clue_id)
            self.clues[clue_id].discovered_by = agent_id
            self.clues[clue_id].discovered_tick = tick
            if agent_id in self.character_knowledge:
                self.character_knowledge[agent_id].known_clues.append(clue_id)
                self.character_knowledge[agent_id].known_facts.add(
                    f"发现了线索: {self.clues[clue_id].description}")

    def reveal_secret(self, secret_id: str, by_agent: str = "", tick: int = 0):
        if secret_id in self.all_secrets and secret_id not in self.revealed_secrets:
            self.revealed_secrets.add(secret_id)
            if by_agent:
                self.who_knows_secret.setdefault(secret_id, set()).add(by_agent)
                if by_agent in self.character_knowledge:
                    self.character_knowledge[by_agent].revealed_secrets.add(secret_id)

    def record_event(self, event: StoryEvent):
        self.timeline.append(event)

    def agent_knows_fact(self, agent_id: str, fact: str) -> bool:
        if agent_id not in self.character_knowledge:
            return False
        return fact in self.character_knowledge[agent_id].known_facts

    def agent_knows_secret(self, agent_id: str, secret_id: str) -> bool:
        if agent_id not in self.character_knowledge:
            return False
        return secret_id in self.character_knowledge[agent_id].revealed_secrets

    def is_established_fact(self, fact: str) -> bool:
        return fact in self.established_facts

    def establish_fact(self, fact: str):
        self.established_facts.add(fact)

    # ═══════════════════════════════════════════════════════════
    # 跨轮次事实追踪
    # ═══════════════════════════════════════════════════════════

    def record_fact(self, speaker: str, content: str, tick: int) -> Optional[Fact]:
        """从对话中提取并记录事实，返回 Fact 或 None"""
        # 简单规则：检测特定模式
        patterns = [
            ("钥匙", ["丢了", "不见了", "丢失", "找不到", "没有"]),
            ("窗户", ["开着", "半开", "没锁", "打开"]),
            ("窗户", ["锁了", "关着", "锁好", "扣好"]),
            ("门", ["锁着", "打不开", "锁上"]),
            ("门", ["开着", "没关", "半开"]),
            ("灯", ["亮着", "有光", "开着"]),
            ("房间", ["进不去", "锁了", "打不开"]),
            ("房间", ["有人", "进去过", "有光"]),
            ("书房", ["锁了", "打不开"]),
            ("书房", ["开着", "有人", "进去"]),
            ("地窖", ["锁了", "打不开"]),
            ("地窖", ["开着", "有人", "进去过"]),
        ]

        for subject, keywords in patterns:
            if subject in content:
                for kw in keywords:
                    if kw in content:
                        # 生成断言
                        if any(neg in kw for neg in ["丢了", "不见", "丢失", "找不到", "没有"]):
                            assertion = "不可访问"
                        elif any(pos in kw for pos in ["开着", "半开", "没锁", "有人", "有光", "亮着", "进去"]):
                            assertion = "可访问"
                        elif any(pos in kw for pos in ["锁了", "锁着", "关着", "锁好", "扣好", "打不开", "进不去"]):
                            assertion = "不可访问"
                        else:
                            assertion = "状态变更"

                        fact = Fact(
                            id=f"fact_{tick}_{speaker}_{subject}_{len(self.facts)}",
                            content=content[:100],
                            stated_by=speaker,
                            stated_tick=tick,
                            subject=subject,
                            assertion=assertion,
                        )
                        self.facts[fact.id] = fact
                        self._subject_index.setdefault(subject, []).append(fact.id)

                        # 记录到角色的独立认知
                        for aid, ck in self.character_knowledge.items():
                            if aid.endswith(speaker) or (hasattr(self, '_name_map') and self._name_map.get(aid) == speaker):
                                ck.personal_facts.append(fact)

                        # 检测矛盾
                        self._detect_contradiction(fact)

                        return fact
        return None

    def _detect_contradiction(self, new_fact: Fact):
        """检查新事实是否与已有事实矛盾"""
        related_ids = self._subject_index.get(new_fact.subject, [])
        for fid in related_ids:
            if fid == new_fact.id:
                continue
            existing = self.facts.get(fid)
            if not existing:
                continue

            # 同一主题，断言相反 = 矛盾
            if existing.assertion != new_fact.assertion:
                # 但如果是不同角色说的，可能是故意设计的矛盾（某人撒谎）
                same_speaker = existing.stated_by == new_fact.stated_by
                severity = "critical" if same_speaker else "warning"

                # 只有同主题且断言互斥才算矛盾
                mutually_exclusive = (
                    (existing.assertion == "不可访问" and new_fact.assertion == "可访问") or
                    (existing.assertion == "可访问" and new_fact.assertion == "不可访问")
                )
                if mutually_exclusive:
                    contradiction = Contradiction(
                        fact_a=existing,
                        fact_b=new_fact,
                        description=(
                            f"Tick{existing.stated_tick} {existing.stated_by}说'{existing.content[:40]}' "
                            f"但 Tick{new_fact.stated_tick} {new_fact.stated_by}说'{new_fact.content[:40]}'"
                            f"——{'同一人说辞矛盾' if same_speaker else '不同角色说法冲突，可能是故意设计'}"
                        ),
                        severity=severity,
                    )
                    self.contradictions.append(contradiction)
                    logger.warning(f"[StoryState] 检测到矛盾: {contradiction.description}")

    def get_recent_contradictions(self, since_tick: int = 0) -> List[Contradiction]:
        """获取最近的矛盾"""
        return [c for c in self.contradictions if c.fact_b.stated_tick >= since_tick]

    def get_contradiction_hint(self) -> str:
        """生成矛盾提示，供下一轮 LLM 参考"""
        recent = self.get_recent_contradictions(self.timeline[-1].tick - 3 if self.timeline else 0)
        if not recent:
            return ""
        hints = ["【逻辑矛盾——请在下轮对话中处理】"]
        for c in recent[-2:]:
            hints.append(f"- {c.description} ({c.severity})")
        return "\n".join(hints)

    def clear_resolved_contradictions(self, subject: str):
        """标记某个主题的矛盾已解决"""
        self.contradictions = [
            c for c in self.contradictions
            if c.fact_a.subject != subject and c.fact_b.subject != subject
        ]

    def get_phase_context(self) -> str:
        """返回当前阶段对应的叙事指引"""
        contexts = {
            StoryPhase.OPENING: "晚宴开场。角色互相介绍、寒暄、熟悉环境。不要急于揭露秘密，先建立人物关系和氛围。",
            StoryPhase.INVESTIGATION: "调查阶段。角色开始注意到异常，提出问题，探索别墅。线索可以逐步浮现，但关键秘密要保持悬念。",
            StoryPhase.CONFLICT: "冲突升级。角色之间的猜疑加深，矛盾浮现。可以揭露次要秘密，推动角色站队和对立。",
            StoryPhase.CLIMAX: "高潮阶段。核心秘密面临揭露，角色关系濒临破裂。关键线索指向真相，每个人都有动机。",
            StoryPhase.RESOLUTION: "收束结局。真相大白，秘密浮出水面。角色做出最终选择，故事走向结局。",
        }
        return contexts.get(self.phase, "自然推进剧情")

    def advance_phase(self, tick: int) -> Optional[StoryPhase]:
        """根据当前状态判断是否应该推进故事阶段"""
        revealed_count = len(self.revealed_secrets)
        clue_count = len(self.discovered_clues)
        total_secrets = len(self.all_secrets)
        total_ticks = self.phase_ticks

        if self.phase == StoryPhase.OPENING and total_ticks >= 3 and clue_count >= 1:
            self.phase = StoryPhase.INVESTIGATION
            self.phase_ticks = 0
            return self.phase

        if self.phase == StoryPhase.INVESTIGATION and revealed_count >= 1 and total_ticks >= 5:
            self.phase = StoryPhase.CONFLICT
            self.phase_ticks = 0
            return self.phase

        if self.phase == StoryPhase.CONFLICT and revealed_count >= total_secrets * 0.5:
            self.phase = StoryPhase.CLIMAX
            self.phase_ticks = 0
            return self.phase

        if self.phase == StoryPhase.CLIMAX and revealed_count >= total_secrets:
            self.phase = StoryPhase.RESOLUTION
            self.phase_ticks = 0
            return self.phase

        self.phase_ticks += 1
        return None

    # ═══════════════════════════════════════════════════════════
    # 快照序列化
    # ═══════════════════════════════════════════════════════════

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 兼容字典，供时间线快照使用。"""
        from dataclasses import asdict
        return {
            "all_secrets": dict(self.all_secrets),
            "revealed_secrets": list(self.revealed_secrets),
            "who_knows_secret": {k: list(v) for k, v in self.who_knows_secret.items()},
            "clues": {k: asdict(v) for k, v in self.clues.items()},
            "discovered_clues": list(self.discovered_clues),
            "character_knowledge": {
                aid: {
                    "known_facts": list(ck.known_facts),
                    "known_clues": list(ck.known_clues),
                    "suspicions": dict(ck.suspicions),
                    "revealed_secrets": list(ck.revealed_secrets),
                    "personal_facts": [asdict(f) for f in ck.personal_facts],
                }
                for aid, ck in self.character_knowledge.items()
            },
            "timeline": [asdict(e) for e in self.timeline],
            "phase": self.phase.value,
            "phase_ticks": self.phase_ticks,
            "established_facts": list(self.established_facts),
            "pending_questions": list(self.pending_questions),
            "facts": {k: asdict(v) for k, v in self.facts.items()},
            "contradictions": [
                {"fact_a": asdict(c.fact_a), "fact_b": asdict(c.fact_b),
                 "description": c.description, "severity": c.severity}
                for c in self.contradictions
            ],
            "subject_index": {k: list(v) for k, v in self._subject_index.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryState":
        """从快照字典恢复 StoryState。"""
        ss = cls()
        ss.all_secrets = data.get("all_secrets", {})
        ss.revealed_secrets = set(data.get("revealed_secrets", []))
        ss.who_knows_secret = {k: set(v) for k, v in data.get("who_knows_secret", {}).items()}
        # Clues
        for cid, cdata in data.get("clues", {}).items():
            ss.clues[cid] = Clue(**cdata)
        ss.discovered_clues = data.get("discovered_clues", [])
        # CharacterKnowledge
        for aid, ck_data in data.get("character_knowledge", {}).items():
            ck = CharacterKnowledge()
            ck.known_facts = set(ck_data.get("known_facts", []))
            ck.known_clues = ck_data.get("known_clues", [])
            ck.suspicions = ck_data.get("suspicions", {})
            ck.revealed_secrets = set(ck_data.get("revealed_secrets", []))
            ck.personal_facts = [Fact(**f) for f in ck_data.get("personal_facts", [])]
            ss.character_knowledge[aid] = ck
        # Timeline
        ss.timeline = [StoryEvent(**e) for e in data.get("timeline", [])]
        # Phase
        try:
            ss.phase = StoryPhase(data.get("phase", "opening"))
        except (ValueError, KeyError):
            ss.phase = StoryPhase.OPENING
        ss.phase_ticks = data.get("phase_ticks", 0)
        ss.established_facts = set(data.get("established_facts", []))
        ss.pending_questions = data.get("pending_questions", [])
        # Facts
        for fid, fdata in data.get("facts", {}).items():
            ss.facts[fid] = Fact(**fdata)
        # Contradictions
        ss.contradictions = []
        for cdata in data.get("contradictions", []):
            try:
                ss.contradictions.append(Contradiction(
                    fact_a=Fact(**cdata["fact_a"]),
                    fact_b=Fact(**cdata["fact_b"]),
                    description=cdata.get("description", ""),
                    severity=cdata.get("severity", "warning"),
                ))
            except Exception:
                pass
        # Subject index
        ss._subject_index = {k: list(v) for k, v in data.get("subject_index", {}).items()}
        return ss

    def get_summary_for_llm(self) -> str:
        """生成给 LLM 的当前状态摘要"""
        lines = [f"【故事阶段】{self.phase.value}"]

        if self.revealed_secrets:
            lines.append(f"【已揭露秘密】{', '.join(self.revealed_secrets)}")
        lines.append(f"【未揭露秘密】{', '.join(set(self.all_secrets.keys()) - self.revealed_secrets)}")

        if self.pending_questions:
            lines.append(f"【待解答悬念】{'; '.join(self.pending_questions[-3:])}")

        if self.discovered_clues:
            clues_text = ", ".join(
                f"{cid}({self.clues[cid].description})"
                for cid in self.discovered_clues[-5:]
            )
            lines.append(f"【已发现线索】{clues_text}")

        lines.append(f"【确立事实】{'; '.join(list(self.established_facts)[-5:])}")

        return "\n".join(lines)
