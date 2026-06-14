# ============================================================
# simulator/rule_engine.py —— 规则引擎
# ============================================================
# 负责所有世界规则的验证。
# 任何 Intent 在被接受前，必须通过规则引擎的验证。
#
# 规则示例：
#   - 角色不在场时无法互动
#   - 门锁着无法进入
#   - 不知道的信息不能说
#   - 夜晚角色会睡觉
#   - 物品只能在所在位置被拾取
# ============================================================

from backend.model.world import WorldTruth
from backend.model.agent import AgentState
from typing import Dict, Optional

# 规则检查结果
class RuleCheckResult:
    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason

    def __bool__(self):
        return self.passed


class RuleEngine:
    """
    规则引擎 —— 世界规则的唯一裁判。
    所有 Intent 必须通过规则验证才能被解析。
    """

    def __init__(self, world_truth: WorldTruth):
        self._truth = world_truth

    def can_agent_perform(self, agent: AgentState, action: str, target_id: str = None) -> RuleCheckResult:
        """
        验证某个 Agent 是否能执行某个动作。
        例如：agent 是否在场？门是否锁住？是否昏迷？
        """
        # TODO: 实现完整的规则验证逻辑
        # - 检查位置
        # - 检查状态（是否昏迷/睡觉等）
        # - 检查时间约束
        # - 检查物品约束
        return RuleCheckResult(True)

    def can_access_location(self, agent_id: str, location_id: str) -> RuleCheckResult:
        """验证 Agent 是否能进入某个地点"""
        location = self._truth.locations.get(location_id)
        if location is None:
            return RuleCheckResult(False, "地点不存在")
        if location.locked:
            # TODO: 检查是否有钥匙
            return RuleCheckResult(False, f"{location.name} 已锁")
        return RuleCheckResult(True)

    def can_interact_with(self, agent_a: str, agent_b: str) -> RuleCheckResult:
        """验证两个 Agent 是否能交互（必须在同一地点）"""
        # TODO: 检查是否在同一地点
        return RuleCheckResult(True)

    def can_know_information(self, agent_id: str, info_key: str) -> RuleCheckResult:
        """
        验证 Agent 是否知道某个信息。
        用于信息隔离 —— 不知道的信息不能说。
        """
        # TODO: 检查 Agent 的认知空间
        return RuleCheckResult(True)

    def validate_intent(self, intent: Dict) -> RuleCheckResult:
        """
        通用 Intent 验证入口。
        intent 结构：{"type": str, "actor": str, "target": str, "action": str, ...}
        """
        intent_type = intent.get("type", "")
        actor = intent.get("actor", "")
        target = intent.get("target", "")
        action = intent.get("action", "")

        # TODO: 根据 intent_type 分派到具体验证方法
        return RuleCheckResult(True)

