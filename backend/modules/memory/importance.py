# ============================================================
# modules/memory/importance.py —— 记忆重要性自动评估
# ============================================================
# 根据记忆内容自动打分，决定是否值得进入长期记忆。
# ============================================================

from backend.model.agent import MemoryEntry

# ── 情绪权重：强情绪记忆更重要 ──
EMOTION_WEIGHT = {
    "neutral": 0.3, "calm": 0.3, "anxious": 0.6, "nervous": 0.6,
    "suspicious": 0.7, "fear": 0.8, "angry": 0.7, "surprised": 0.8,
    "tension": 0.7, "confused": 0.5, "determined": 0.6, "worried": 0.6,
    "excited": 0.7, "sad": 0.6, "happy": 0.5,
}

# ── 内容关键词权重 ──
KEYWORD_WEIGHT = [
    (["秘密", "真相", "谋杀", "杀手", "凶手", "死去", "死亡", "尸体"], 0.9),
    (["信", "钥匙", "刀", "血迹", "证据", "线索", "发现"], 0.8),
    (["我怀疑", "我觉得", "我认为", "也许", "可能", "一定"], 0.6),
    (["他说", "她说", "透露", "告诉我", "听说"], 0.7),
    (["对不起", "原谅", "后悔", "当年", "曾经", "过去"], 0.7),
    (["爱", "恨", "害怕", "担心", "恐惧", "愤怒"], 0.6),
    (["计划", "打算", "准备", "决定", "必须", "一定"], 0.5),
]

# ── 事件/动作权重 ──
EVENT_BONUS = {
    "speak": 0.1,        # 对话有信息量
    "investigate": 0.2,  # 调查行为产生发现
    "interact": 0.15,    # 互动有剧情推进
    "move": 0.0,         # 纯移动信息量低
    "idle": -0.1,        # 发呆不重要
}


def score_importance(entry: MemoryEntry, action_type: str = "") -> float:
    """
    自动评估一条记忆的重要性 (0.0 ~ 1.0)。

    计算因素：
      1. 情绪权重（基础分）
      2. 内容关键词匹配
      3. 行为类型加成
      4. 记忆内容长度（太短的可能信息量不足）
    """
    score = 0.3  # 基础分

    # 1. 情绪权重
    emotion = entry.emotion_tag.lower()
    score += EMOTION_WEIGHT.get(emotion, 0.3)

    # 2. 关键词匹配
    content = entry.content.lower()
    keyword_bonus = 0.0
    for keywords, weight in KEYWORD_WEIGHT:
        for kw in keywords:
            if kw.lower() in content:
                keyword_bonus = max(keyword_bonus, weight)
                break
    score += keyword_bonus * 0.3

    # 3. 行为类型
    if action_type:
        score += EVENT_BONUS.get(action_type, 0.0)

    # 4. 长度惩罚（少于5字的信息量太低）
    if len(entry.content) < 5:
        score -= 0.1

    return max(0.0, min(1.0, score))


def should_consolidate(entry: MemoryEntry, action_type: str = "") -> bool:
    """判断一条记忆是否应该归档到长期记忆。"""
    return score_importance(entry, action_type) >= 0.5
