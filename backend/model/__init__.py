# ============================================================
# model/ —— Pydantic 数据模型
# ============================================================
# 本包定义系统中所有结构化数据模型。
# 遵循 readme.txt 中的三层状态划分：
#   1. World Truth（客观真相）
#   2. Agent Belief（角色认知）
#   3. Player Influence（玩家影响）
#
# 以及 Intent（意图）、Event（事件）等运行时模型。
# ============================================================

from backend.model.relationship import Relationship
from backend.model.dialogue import DialogueRecord

__all__ = ["Relationship", "DialogueRecord"]
