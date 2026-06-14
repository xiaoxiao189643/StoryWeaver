# ============================================================
# utils/i18n.py —— 前端数据中英翻译
# ============================================================
# 所有对前端输出的英文字段统一在这里转中文。
# 修改时只需改这里的映射表，不需要到处改 handler。
# ============================================================

EMOTION_CN: dict[str, str] = {
    "neutral": "平静",
    "anxious":  "焦虑",
    "nervous":  "紧张",
    "calm":     "冷静",
    "angry":    "愤怒",
    "sad":      "悲伤",
    "happy":    "开心",
    "fear":     "恐惧",
    "surprised": "惊讶",
    "confused": "困惑",
    "suspicious": "怀疑",
    "determined": "坚定",
    "worried":  "担忧",
    "excited":  "兴奋",
    "tension":  "紧绷",
}

ACTION_TYPE_CN: dict[str, str] = {
    "speak":       "讲话",
    "move":        "移动",
    "investigate": "调查",
    "interact":    "互动",
    "idle":        "待机",
}

PHASE_CN: dict[str, str] = {
    "act_1":      "第一幕·建立",
    "act_2_rise": "第二幕·矛盾升级",
    "act_2_peak": "第二幕·危机高潮",
    "act_3":      "第三幕·真相收束",
}

WEATHER_CN: dict[str, str] = {
    "sunny":   "晴天",
    "stormy":  "暴风雨",
    "rainy":   "雨天",
    "snowy":   "大雪",
    "cloudy":  "阴天",
    "foggy":   "大雾",
    "windy":   "大风",
    "blizzard": "暴风雪",
}

EVENT_TYPE_CN: dict[str, str] = {
    "broadcast":         "广播通知",
    "blackout":          "停电",
    "murder":            "谋杀",
    "alarm":             "警报",
    "weather_change":    "天气变化",
    "new_arrival":       "新人到场",
    "strange_sound":     "异响",
    "confrontation":     "对峙",
    "discovery":         "发现线索",
    "revelation":        "真相揭示",
    "ambient":           "环境氛围",
    "convergence_trigger": "收束触发",
}

LOCATION_CN: dict[str, str] = {
    "hall":    "大厅",
    "study":   "书房",
    "kitchen": "厨房",
    "garden":  "花园",
    "cellar":  "地窖",
}


def cn_emotion(en: str) -> str:
    return EMOTION_CN.get(en, en)

def cn_action_type(en: str) -> str:
    return ACTION_TYPE_CN.get(en, en)

def cn_phase(en: str) -> str:
    return PHASE_CN.get(en, en)

def cn_weather(en: str) -> str:
    return WEATHER_CN.get(en, en)

def cn_event_type(en: str) -> str:
    return EVENT_TYPE_CN.get(en, en)

def cn_location(en: str) -> str:
    return LOCATION_CN.get(en, en)
