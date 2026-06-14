# ============================================================
# simulator/intent_resolver.py —— Intent 解析器
# ============================================================
# 负责将 Intent（意图）解析为具体的状态更新。
#
# Intent 来源：
#   - 玩家：如"Bob 在撒谎"
#   - 角色 Agent：如"尝试进入实验室"
#   - 导演 Agent：如"增加冲突"
#
# 解析流程：
#   1. 接收 Intent
#   2. Rule Engine 验证
#   3. 冲突处理（多个 Intent 同时发生）
#   4. 概率计算（非确定性行为）
#   5. 生成 State Update
# ============================================================
from typing import Dict, Tuple, Any
import random

from backend.engine.rule_engine import RuleEngine
from backend.engine.ground_truth import GroundTruthManager
from backend.modules.character.belief_system import BeliefSystem


# ============================================================
# 🧩 标准化解析结果（核心升级）
# ============================================================

class IntentResult:
    """
    Intent解析结果（统一结构）
    """

    def __init__(
        self,
        success: bool,
        command_type: str = "",
        payload: Dict = None,
        probability: float = 1.0,
        priority: int = 1,
        reason: str = ""
    ):
        self.success = success
        self.command_type = command_type
        self.payload = payload or {}
        self.probability = probability
        self.priority = priority
        self.reason = reason


# ============================================================
# 🧠 IntentResolver（升级版）
# ============================================================

class IntentResolver:

    def __init__(
        self,
        rule_engine: RuleEngine,
        ground_truth: GroundTruthManager,
        belief_system: BeliefSystem
    ):
        self._rule_engine = rule_engine
        self._ground_truth = ground_truth
        self._belief_system = belief_system

    # ========================================================
    # 🎯 主入口
    # ========================================================

    def resolve(self, intent: Dict) -> Tuple[bool, Dict]:

        # 1️⃣ 规则校验
        check = self._rule_engine.validate_intent(intent)
        if not check.passed:
            return False, {"reason": check.reason}

        intent_type = intent.get("type")

        # 2️⃣ 分发
        result = None

        if intent_type == "move":
            result = self._resolve_move(intent)

        elif intent_type == "interact":
            result = self._resolve_interact(intent)

        elif intent_type == "speak":
            result = self._resolve_speak(intent)

        elif intent_type == "use_item":
            result = self._resolve_use_item(intent)

        elif intent_type == "investigate":
            result = self._resolve_investigate(intent)

        else:
            result = self._resolve_generic(intent)

        # 3️⃣ 概率执行（关键升级）
        if result.probability < 1.0:
            if random.random() > result.probability:
                return False, {
                    "reason": "probability_failed",
                    "probability": result.probability
                }

        # 4️⃣ 输出统一 command
        return True, {
            "type": result.command_type,
            **result.payload
        }

    # ========================================================
    # 🚶 MOVE（升级版）
    # ========================================================

    def _resolve_move(self, intent: Dict) -> IntentResult:

        agent_id = intent.get("actor")
        target = intent.get("target")

        access = self._rule_engine.can_access_location(agent_id, target)

        if not access.passed:
            return IntentResult(
                success=False,
                reason=access.reason
            )

        return IntentResult(
            success=True,
            command_type="location_change",
            payload={
                "agent_id": agent_id,
                "new_location": target
            },
            probability=1.0,
            priority=2
        )

    # ========================================================
    # 💬 SPEAK（升级版）
    # ========================================================

    def _resolve_speak(self, intent: Dict) -> IntentResult:

        actor = intent.get("actor")
        text = intent.get("action", "")

        # 可以接 belief system 做信息过滤（未来升级点）
        visibility = 1.0

        return IntentResult(
            success=True,
            command_type="dialogue",
            payload={
                "speaker": actor,
                "text": text
            },
            probability=visibility,
            priority=1
        )

    # ========================================================
    # 🤝 INTERACT
    # ========================================================

    def _resolve_interact(self, intent: Dict) -> IntentResult:

        return IntentResult(
            success=True,
            command_type="interaction",
            payload={
                "actor": intent.get("actor"),
                "target": intent.get("target")
            },
            probability=0.9,   # 👈 有失败概率（模拟真实世界）
            priority=2
        )

    # ========================================================
    # 📦 ITEM
    # ========================================================

    def _resolve_use_item(self, intent: Dict) -> IntentResult:

        return IntentResult(
            success=True,
            command_type="item_use",
            payload=intent,
            probability=1.0,
            priority=1
        )

    # ========================================================
    # 🔍 INVESTIGATE
    # ========================================================

    def _resolve_investigate(self, intent: Dict) -> IntentResult:

        return IntentResult(
            success=True,
            command_type="investigation",
            payload=intent,
            probability=0.8,
            priority=3
        )
    
    # ========================================================
    # 🧠 ACTION MAPPING（LLM Intent → WorldCommand）
    # ========================================================
    # 将 LLM 输出的抽象 intent 转换为世界可执行 command
    # 这是系统的"语义翻译层"，决定世界是否能正确响应 Agent 行为
    # 实际解析逻辑由上面的 resolve() 统一入口完成（含规则验证+概率执行）
    # ========================================================

    # ========================================================
    # 🧱 DEFAULT RESOLVER（兜底逻辑）
    # ========================================================

    def _resolve_generic(self, intent: Dict) -> IntentResult:

        return IntentResult(
            success=True,
            command_type="generic",
            payload=intent,
            probability=1.0,
            priority=1
        )
    
    