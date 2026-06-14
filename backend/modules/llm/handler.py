# ============================================================
# modules/llm/handler.py —— LLM 模块消息处理器
# ============================================================

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv

from backend.framework.bus import bus

# 从项目根目录加载 .env
import os as _os
_dotenv_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))), ".env")
load_dotenv(_dotenv_path)
logger = logging.getLogger(__name__)

from backend.config import settings

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _get_api_key() -> str:
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _get_director_api_key() -> str:
    return os.environ.get("DIRECTOR_API_KEY", "") or _get_api_key()


def _director_model() -> str:
    return os.environ.get("DIRECTOR_MODEL", "") or "deepseek-chat"


def _director_temperature() -> float:
    return float(os.environ.get("DIRECTOR_TEMPERATURE", "0.9"))


class LLMHandler:
    """LLM 模块消息处理器。"""

    async def handle_generate_scene(self, payload: Dict) -> Dict:
        """一次 LLM 调用写场景：每个角色带目标说话，不是聊天是博弈。"""
        tick = payload.get("tick", 0)
        history = payload.get("dialogue_history", [])
        incident = payload.get("incident", "")
        goals = payload.get("character_goals", {})
        knowledge = payload.get("character_knowledge", {})
        fix_hints = payload.get("fix_hints", "")

        history_text = "\n".join(history[-15:]) if history else "（故事刚开始）"

        goals_text = "\n".join(f"  {n}：{g}" for n, g in goals.items()) if goals else ""
        know_text = "\n".join(f"  {n} 知道：【{'；'.join(knowledge.get(n, ['仅了解自己身份'])[:4])}】" for n in goals) if goals else ""

        incident_block = f"\n【本轮触发事件——所有角色必须各自做出反应】\n{incident}\n" if incident else ""
        fix_block = f"\n【上轮逻辑矛盾——本轮角色必须质疑或解释】\n{fix_hints}\n" if fix_hints else ""

        # 阶段信息
        phase = payload.get("phase", {})
        phase_name = phase.get("name", "开场")
        phase_goal = phase.get("goal", "建立悬念")
        phase_deadline = phase.get("deadline", "")
        reveal_hint = phase.get("reveal", "")
        stagnation = payload.get("stagnation", False)

        phase_block = f"""【当前阶段：{phase_name}——本阶段必须完成的任务】
{phase_goal}
{phase_deadline}
{reveal_hint}
"""

        force_block = ""
        if stagnation:
            force_block = "【强制推进——对话已经停滞！必须引入新事件。楼上传来声响/窗外有动静/某个角色做出了出人意料的行动。不要继续在同样的质疑上打转。】\n"

        system_prompt = f"""你是悬疑小说《雪隐》的作者。续写一段场景。

【故事】暴风雪夜，雪山别墅「雪隐」。晚餐刚结束，灯闪灭，三楼传来巨响。

{phase_block}
{force_block}
【角色目标】
{goals_text}

【信息差——知道的各不相同】
{know_text}
{incident_block}
【已发生的对话——不可重复写同样的质疑和回答】
{history_text}
{fix_block}

【输出规则——根据当前阶段严格执行】
- 如果阶段目标是"建立悬念"：抛出问题，营造不安，让读者想知道答案
- 如果阶段目标是"揭露线索"：必须有实质性的新信息，不能再用"老奴什么都不知道"敷衍
- 如果阶段目标是"推进冲突"：某人在压力下露出破绽，矛盾必须比上一轮更尖锐
- 如果阶段目标是"揭示真相"：不能再回避问题，关键信息必须浮出水面

【输出 JSON】
{{"narration":"描写","dialogues":[{{"speaker":"角色名","content":"台词"}}]}}"""

        import json as _json
        api_key = _get_api_key()
        if not api_key:
            return {"narration": "", "dialogues": []}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    DEEPSEEK_URL,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                    json={"model": "deepseek-chat", "max_tokens": 500, "temperature": 0.85,
                          "messages": [{"role": "system", "content": system_prompt}]},
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                return _json.loads(cleaned)
        except Exception as e:
            logger.error(f"Scene generation failed: {e}")
            return {"narration": "", "dialogues": []}

    async def handle_decide_action(self, payload: Dict) -> Dict:
        """NPC 决策（信息隔离 + 阶段驱动 + 记忆强化版）"""
        agent_name = payload.get("agent_name", "角色")
        personality_desc = payload.get("personality_desc", "普通的角色")
        emotion = payload.get("emotion", "neutral")
        emotion_intensity = payload.get("emotion_intensity", 0.5)
        # ── 提取玩家信任值，用于构建信任感知 prompt ──
        player_trust_value = float(payload.get("player_trust", 0.0) or 0.0)
        if player_trust_value > 0.2:
            trust_label = "信任——你比较相信这位高维存在，倾向于认真考虑其指引"
        elif player_trust_value > -0.2:
            trust_label = "中性——你对这位高维存在没有特别的倾向"
        else:
            trust_label = "不信任——你怀疑这位高维存在，对其指引持抗拒态度"
        goals_text = payload.get("goals", "暂无明确目标")
        events_text = "\n".join(f"  - {e}" for e in payload.get("events", [])) or "无"
        all_mems = payload.get("recent_memories", [])
        recent_dialogues = [m for m in all_mems if m.startswith('"') or '"' in m]
        mem_lines = []
        for i, m in enumerate(all_mems[-12:]):
            prefix = ">>> 你刚说过 <<<" if m in recent_dialogues[-3:] and m == all_mems[-1] else ""
            mem_lines.append(f"  {prefix} {m}" if prefix else f"  - {m}")
        mem_text = "\n".join(mem_lines) or "（暂无记忆）"
        other_dialogues = payload.get("other_dialogues", [])
        other_text = "\n".join(f"  - {d}" for d in other_dialogues[-6:]) if other_dialogues else "（暂无）"
        rel_text = "\n".join(f"  - 对 {tid} 信任值: {val}" for tid, val in payload.get("relationships", {}).items()) or "（暂无关系数据）"
        instruction = payload.get("instruction", "自然推进剧情")

        # 信息隔离
        my_knowledge = payload.get("my_knowledge", [])
        others_knowledge = payload.get("others_knowledge", {})
        know_text = "\n".join(f"  - {k}" for k in my_knowledge[:6]) if my_knowledge else "（仅了解自己的身份和来意）"
        secrets_others_know = []
        for name, knows in others_knowledge.items():
            for k in knows[:2]:
                if k not in my_knowledge:
                    secrets_others_know.append(f"  - {name}可能知道一些你不知道的事：{k}")
        blindspot_text = "\n".join(secrets_others_know[:4]) if secrets_others_know else ""

        # 阶段信息
        phase = payload.get("phase", {})
        phase_name = phase.get("name", "开场")
        phase_goal = phase.get("goal", "建立悬念")
        phase_deadline = phase.get("deadline", "")
        reveal_hint = phase.get("reveal", "")
        stagnation = payload.get("stagnation", False)
        fix_hints = payload.get("fix_hints", "")

        phase_block = f"【当前阶段：{phase_name}——节奏控制】{phase_goal}"
        if phase_deadline:
            phase_block += f"\n截止要求：{phase_deadline}"
        if reveal_hint:
            phase_block += f"\n本阶段可开始揭露的线索：{reveal_hint}"
        # 明确告诉 LLM 当前阶段允许透露的程度
        if "第一幕" in phase_name or "建立" in phase_goal:
            phase_block += "\n【节奏指令】你在第一幕。不要揭露核心秘密。你的任务是营造不安、抛出问题、建立人物关系。说话要有保留、有试探、有言外之意。像个活人在社交场合小心翼翼地试探——而不是朗读你的角色档案。"
        elif "第二幕" in phase_name or "揭露" in phase_goal:
            phase_block += "\n【节奏指令】你在第二幕。可以在被追问时透露部分信息，但不要一次性全说出来。让真相像剥洋葱一样一层一层地展开。"
        elif "第三幕" in phase_name or "破绽" in phase_goal or "冲突" in phase_goal:
            phase_block += "\n【节奏指令】冲突升级阶段。你可以在压力下说漏嘴，你的回答可以出现矛盾。不要再完美地回避问题。"

        force_block = ""
        if stagnation:
            force_block = "\n【警告：对话已停滞！你必须做出与之前不同的行动。如果别人在回避问题，就逼问。如果没人行动，你就主动调查。】"
        if fix_hints:
            force_block += f"\n【逻辑矛盾需处理】{fix_hints}"

        system_prompt = f"""你是「{agent_name}」。场上只有四个角色：苏晚晴（女主人）、江策（侦探）、顾言（画家）、钟叔（管家）。除此之外没有任何其他人。

【你的人格】
{personality_desc}

【当前情绪】{emotion}（强度 {emotion_intensity}）
【你的目标】{goals_text}

【对玩家的态度】{trust_label}（信任值 {player_trust_value:.2f}，范围 -1~1）——你对这位"高维存在"的信任程度，影响你接受其指引的意愿：信任越高，越倾向于顺着玩家的指引思考和行动；信任越低，越会质疑、抗拒或无视玩家的建议。

【信息隔离——最重要的规则】
你只能根据「你知道的信息」行动。你不知道的事，不能说、不能暗示、不能突然"猜到"。
- 如果一件事没列在"你知道的信息"里，你就真的不知道
- 你可以怀疑、试探、观察——但不能直接知道别人的秘密
- 不要突然说出你没听到过的信息

【规则】
1. 对话驱动剧情，优先 speak
2. 刚说完话 → idle 或做别的事；换场景 → move；检查物件 → investigate
3. 别人对你说的话 → 必须 speak 回应，不能沉默
4. speak 时 target 只能是：苏晚晴、江策、顾言、钟叔，或 null
5. 严禁重复自己刚说过的话
6. 严禁虚构角色名
7. 你的发言要像真人——有犹豫、有试探、有言外之意

【叙事节奏——你的秘密是逐步释放的，不是一开始就摊牌】
- 如果当前是"第一幕"或"建立悬念"阶段：你只能观察、提问、暗示。不要主动揭露你的核心秘密或身份。你可以看起来可疑，但不能直接把底牌亮出来。
- 如果当前是"第二幕"或"揭露线索"阶段：你可以在被逼问时松口，透露部分信息——但只透露和你"知道的信息"相匹配的内容，不要编造。
- 如果当前是"推合冲突"或"揭示真相"阶段：是时候摊牌了。你可以说出你一直隐瞒的关键信息，与其他角色正面冲突。

【输出 JSON，无额外文字】
{{"type": "speak|move|investigate|interact|idle", "action": "简述（15字内）", "target": "苏晚晴/江策/顾言/钟叔/null", "dialogue": "发言（speak时填，否则null）", "emotion": "平静/冷静/焦虑/怀疑/紧张/愤怒/恐惧/惊讶/悲伤/困惑/坚定/担忧", "emotion_intensity": 0.0, "reason": "理由（10字内）"}}"""

        # 开场旁白——角色正处于这段描述的场景中
        opening_block = ""
        opening_narration = payload.get("opening_narration")
        if opening_narration:
            opening_block = f"""【此刻——你正置身于这段场景中。旁白刚刚落下，巨响的余韵还在空气中震颤。你是这段场景里活生生的人——不是读剧本的演员。你的第一句话必须从这段氛围中自然生长出来。】

「{opening_narration}」

【接续指引】
- 你刚刚经历了旁白中描述的一切：灯光闪烁、三楼巨响。这刚刚发生。
- 你的第一句话要像一个真实的人在这种情境下会说的第一句话——而不是一段"角色介绍"或"剧情说明"。
- 你可以沉默片刻后再开口，你的话可以很短，可以带着犹豫，可以只是一个问题或一声低语。
- 不要直接说出你的秘密或你的全部想法。你是一个在暴风雪夜、刚听到三楼传来巨响的人。仅此而已。
"""

        player_directive = payload.get("player_directive", "")
        player_intervention = payload.get("player_intervention", {}) or {}
        player_target = player_intervention.get("target", "all")
        player_text = player_intervention.get("text") or (player_directive.split("「")[1].split("」")[0] if "「" in player_directive else player_directive)
        is_direct_target = player_target in ("all", "", None, payload.get("agent_id"), payload.get("agent_name"))
        response_hint = "你是这次指令的直接对象，要给出符合自身目标和认知的回应。" if is_direct_target else "你不是这次指令的直接对象，只在符合场景时表现出旁观、怀疑或短暂反应。"

        # ── 干预有效性 → NPC 可感知的提示 ──
        effectiveness = player_intervention.get("effectiveness", 1.0)
        if effectiveness > 0.7:
            eff_note = "这次干预触动了你的内心——你倾向于认真思考玩家所指出的方向，并可能顺着它行动。"
        elif effectiveness > 0.3:
            eff_note = "这次干预有一定道理——你可以半信半疑地考虑，也可以选择性地接受一部分。"
        else:
            eff_note = "这次干预说服力较弱——你很可能忽略它，或者只是表面上应付一下。"

        player_block = f"""

【玩家干预——自然纳入剧情】
玩家刚刚影响了场景：「{player_text}」
{eff_note}
{response_hint}
不要逐字复述玩家的话；不要把它当作必须服从的命令。你可以质疑、误解、抗拒、顺势利用或沉默观察，但回应必须符合你的秘密、目标和当前信息。""" if player_directive else ""

        user_prompt = f"""【导演指令】{instruction}
{player_block}
{phase_block}
{force_block}
{opening_block}【当前场景事件】
{events_text}

【你知道的信息——只能据此行动】
{know_text}

【你记得的事（>>> = 你刚说过的，严禁重复）】
{mem_text}

【其他人刚说了什么——你应该回应】
{other_text}

【关系】{rel_text}
{"【提示：以下是你不知道的事，你不能直接知晓】" + chr(10) + blindspot_text if blindspot_text else ""}

你现在说什么或做什么来推进剧情？输出 JSON："""

        return await self._call_deepseek(system_prompt, user_prompt)

    async def handle_generate_dialogue(self, payload: Dict) -> Dict:
        # TODO: 独立对话生成
        return {"dialogue": "", "emotion": "平静"}

    async def handle_generate_thought(self, payload: Dict) -> Dict:
        # TODO: 内心独白
        return {"thought": ""}

    async def handle_evaluate_intervention(self, payload: Dict) -> Dict:
        """评估玩家干预意图和效果。"""
        player_text = payload.get("player_text", "")
        tension = payload.get("tension", "平静")
        if not player_text:
            return {"success": False, "effectiveness": 0.0, "narrative_response": ""}

        system_prompt = """你是 StoryWeaver 的干预评估器。分析玩家指令，返回意图分类和效果评估。

意图类型：investigate(调查)、accuse(指控)、reassure(安抚)、threaten(威胁)、guide(引导)、other(其他)

输出 JSON：
{"intent_type": "investigate", "effectiveness": 0.7, "narration_hint": "玩家试图引导角色调查新线索"}"""

        user_prompt = f"当前紧张度：{tension}\n玩家指令：「{player_text}」\n分析这个指令的意图和可能的效果。输出 JSON。"

        try:
            result = await self._call_director(system_prompt, user_prompt, max_tokens=100, parser="text")
            import json
            data = json.loads(result.get("text", "{}"))
            return {
                "success": True,
                "effectiveness": data.get("effectiveness", 0.5),
                "intent_type": data.get("intent_type", "other"),
                "narrative_response": data.get("narration_hint", ""),
            }
        except Exception:
            return {"success": True, "effectiveness": 0.5, "intent_type": "other", "narrative_response": ""}

    async def handle_generate_characters(self, payload: Dict) -> Dict:
        logger.info(f"[角色生成] 开始, API Key: {'有' if _get_api_key() else '无'}")
        background = payload.get("background", "")
        locations = payload.get("locations", [])
        items = payload.get("items", [])
        secrets = payload.get("secrets", [])
        scheduled_events = payload.get("scheduled_events", [])
        count = payload.get("count", 4)
        loc_text = "\n".join(f"  - {loc['id']}: {loc.get('name','')}（{loc.get('description','')}）" for loc in locations) or "（无）"
        item_text = "\n".join(f"  - {item['id']}: {item.get('name','')}（{item.get('description','')}）" for item in items) or "（无）"
        secret_text = "\n".join(f"  - {s}" for s in secrets) or "（无）"
        event_text = "\n".join(f"  - tick {e.get('tick',0)}: [{e.get('type','')}] {e.get('description','')}" for e in scheduled_events) or "（无）"
        system_prompt = f"""你是一个互动叙事游戏的游戏大师。根据故事背景、场景、物品、秘密和预定事件，创建 {count} 个角色。

每个角色必须包含：
- id: 英文标识符（如 detective_lin）
- name: 中文名（2-3字）
- personality:
  - core_description: 角色介绍（100-150字，第三人称，描述角色的身份、性格、背景、说话风格）
  - traits: 大五人格（0.0-1.0），根据角色身份必须各有高低，不能全一样：
    · openness（开放性）：高=好奇爱探索，低=务实保守
    · conscientiousness（尽责性）：高=严谨自律，低=随性散漫
    · extraversion（外向性）：高=健谈社交，低=内敛独处
    · agreeableness（宜人性）：高=温和合作，低=多疑好斗
    · neuroticism（神经质）：高=焦虑敏感，低=沉稳冷静
    【重要】4个角色的trait必须差异化，例如侦探应高尽责低宜人，艺术家应高开放低尽责。
- emotion: current_mood（平静/冷静/焦虑/怀疑/紧张/愤怒/恐惧/惊讶/悲伤/困惑）和 intensity（0.3-0.8）
- goals: 2-3个目标（id/description/priority/is_active），与秘密和事件关联
- location_id: 从给定地点中选择
- current_action: "idle"

角色之间要有关系张力，目标冲突或互补。
严格输出JSON：{{"agents": [{{...}}]}}"""
        user_prompt = f"""【故事背景】{background}
【地点】{loc_text}
【物品】{item_text}
【秘密】{secret_text}
【事件】{event_text}
【要求】生成{count}个角色。输出JSON。"""
        return await self._call_deepseek(system_prompt, user_prompt, max_tokens=2000, parser="character_list")

    async def _call_deepseek(self, system_prompt: str, user_prompt: str, max_tokens: int = 300, parser: str = "action") -> Dict:
        api_key = _get_api_key()
        if not api_key:
            return {"agents": []} if parser == "character_list" else {"type": "idle", "action": "发呆", "target": None, "dialogue": None, "reason": "无 API Key"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    DEEPSEEK_URL,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                    json={"model": "deepseek-chat", "max_tokens": max_tokens, "temperature": 1.0,
                          "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]},
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                return self._parse_character_list(raw) if parser == "character_list" else self._parse(raw)
        except Exception as e:
            logger.error(f"DeepSeek 调用失败: {type(e).__name__}: {e}")
            return {"agents": []} if parser == "character_list" else {"type": "idle", "action": "发呆", "target": None, "dialogue": None, "reason": f"API 错误: {e}"}

    def _parse(self, raw: str) -> Dict:
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(cleaned)
            # 防止 JSON null 值透传；情绪写回用于导演节奏控制和前端展示
            return {
                "type": data.get("type") or "idle",
                "action": data.get("action") or "",
                "target": data.get("target") or None,
                "dialogue": data.get("dialogue") or None,
                "emotion": data.get("emotion") or "平静",
                "emotion_intensity": data.get("emotion_intensity", 0.5),
                "reason": data.get("reason") or "",
            }
        except (json.JSONDecodeError, KeyError):
            return {"type": "idle", "action": "发呆", "target": None, "dialogue": None, "reason": "解析失败"}

    def _parse_character_list(self, raw: str) -> Dict:
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(cleaned)
            return data if "agents" in data else ({"agents": data} if isinstance(data, list) else {"agents": []})
        except (json.JSONDecodeError, KeyError):
            return {"agents": []}


    # ═══════════════════════════════════════════════════════════
    # 导演专用 LLM 接口
    # ═══════════════════════════════════════════════════════════

    async def handle_director_decide(self, payload: Dict) -> Dict:
        """导演叙事决策：根据当前状态判断下一步该做什么。"""
        tension = payload.get("tension", "平静")
        convergence = payload.get("convergence", 0)
        secrets_hidden = payload.get("secrets_hidden", [])
        secrets_revealed = payload.get("secrets_revealed", [])
        pending_events = payload.get("pending_events", [])
        recent_events = payload.get("recent_events", [])
        narration_history = payload.get("narration_history", [])

        secret_text = "\n".join(f"  - {s}" for s in secrets_hidden[:5]) or "无"
        revealed_text = "\n".join(f"  - {s}" for s in secrets_revealed[-3:]) or "无"
        event_text = "\n".join(f"  - tick {e.get('triggerTime','?')}: {e.get('type','?')} {e.get('description','')}" for e in pending_events[:5]) or "无"
        recent_text = "\n".join(f"  - {e}" for e in recent_events[-5:]) or "无"
        narration_text = "\n".join(f"  - {n}" for n in narration_history[-3:]) or "无"

        player_text = payload.get("player_text", "")
        player_block = f"""
【高维玩家指令——必须优先响应】
玩家刚刚给出了指令：「{player_text}」
你的 SceneGoal 必须引导角色响应这个指令——让他们讨论、质疑、或执行玩家建议的方向。
""" if player_text else ""

        system_prompt = f"""你是 StoryWeaver 的导演，负责控制互动悬疑叙事的节奏和方向。

当前故事状态：
- 紧张度：{tension}（平静→紧张→危机→收束）
- 收束度：{convergence:.0%}（0% = 刚开始，100% = 结局）
- 隐藏的秘密：{len(secrets_hidden)} 个
- 已揭露的秘密：{len(secrets_revealed)} 个

【你的职责】
根据最近发生的事，给 NPC 一个具体的场景目标。目标必须具体——
比如"让侦探去调查厨房窗户的可疑痕迹"或"引发女主人和画家之间的对峙"，
不要泛泛地说"推进剧情"。

【输出格式——严格 JSON】
{{
  "scene_goal": "具体场景目标（30字内，必须包含人物名或地点名）",
  "narration": "导演旁白（20字内，空字符串跳过）",
  "reasoning": "决策理由（15字内）"
}}"""

        user_prompt = f"""【隐藏的秘密】{secret_text}
【已揭露的秘密】{revealed_text}
【待触发事件】{event_text}
【最近发生的事】{recent_text}
【最近旁白】{narration_text}
{player_block}
根据最近发生的事，给 NPC 一个具体的方向。输出 JSON。"""

        return await self._call_director(system_prompt, user_prompt, max_tokens=500, parser="director")

    async def handle_director_narration(self, payload: Dict) -> Dict:
        """导演生成一段小说式旁白。"""
        tension = payload.get("tension", "平静")
        convergence = payload.get("convergence", 0)
        event_desc = payload.get("event_desc", "")
        secret_revealed = payload.get("secret_revealed", "")
        recent_actions = payload.get("recent_actions", "")
        is_opening = payload.get("is_opening", False)
        characters = payload.get("characters", "")

        if is_opening:
            system_prompt = f"""你是悬疑小说的作者。请为故事写一段开场序幕。

故事背景：暴风雪夜，雪山别墅「雪隐」。晚餐刚结束，四个人还坐在餐桌旁，没有人说话。

登场角色：
{characters}

要求：
- 写一段小说的序幕，8-12句话
- 先描写环境：暴风雪拍打窗户、别墅大厅、壁炉火光
- 再逐一勾勒登场角色：他们的身份、神态、此刻细微的动作
- 然后写到事件发生：灯闪了一下、灭了、又亮起来。紧接着三楼传来一声沉闷的巨响——像什么重物砸在地板上。
- 以巨响后的寂静收尾——角色们还没来得及反应，呼吸凝滞在空气中
- 用文学化的语言，营造悬疑氛围。像阿加莎·克里斯蒂的小说的开头。
- 纯文本，不要JSON"""

            result = await self._call_director(system_prompt, "", max_tokens=500, parser="text")
            return {"narration": result.get("text", "")}

        extra = ""
        if event_desc:
            extra = f"\n刚发生的事件：{event_desc}"
        if secret_revealed:
            extra += f"\n刚揭露的秘密：{secret_revealed}"
        if recent_actions:
            extra += f"\n角色们的行动：{recent_actions}"

        is_responsive = payload.get("is_responsive", False)

        if is_responsive:
            recent_narrations = payload.get("recent_narrations", [])
            narration_block = ""
            if recent_narrations:
                narration_block = "\n【近期旁白——避免重复】\n" + "\n".join(f"  - {n}" for n in recent_narrations[-3:]) + "\n请写一段与以上不重复的场景描写。"
            system_prompt = f"""你是悬疑小说的叙述者。根据角色们的对话，写一段场景描写。

【场景】暴风雪中的雪山别墅。当前紧张度：{tension}，故事进度：{convergence:.0%}。{extra}{narration_block}

要求：
- 2-3句话，不超过80字
- 根据角色对话内容，描写此刻的场景氛围、角色神态或环境细节
- 可以写暴风雪、壁炉、老宅声响、角色的细微动作或表情
- 严禁：雨、邻居、街道、城市、汽车、手机
- 严禁与【近期旁白】中的任何描述重复或高度相似
- 纯文本，不要JSON"""
            result = await self._call_director(system_prompt, "", max_tokens=120, parser="text")
        else:
            recent_narrations = payload.get("recent_narrations", [])
            narration_block = ""
            if recent_narrations:
                narration_block = "\n【近期旁白——避免重复】\n" + "\n".join(f"  - {n}" for n in recent_narrations[-3:]) + "\n请写一段与以上不重复的环境描写。"
            system_prompt = f"""你是悬疑小说的叙述者。写一段简短的环境描写来烘托当前场景的氛围。

【场景】暴风雪中的雪山别墅。外面只有风雪呼啸，没有雨、没有邻居、没有城市街道。
当前紧张度：{tension}，故事进度：{convergence:.0%}。{extra}{narration_block}

要求：
- 1-2句话，不超过40字
- 只描写暴风雪、壁炉、窗外的雪、老宅声响
- 严禁：雨、邻居、街道、城市、汽车、手机
- 呼应角色对话中的情绪
- 严禁与【近期旁白】中的任何描述重复或高度相似
- 纯文本，不要JSON"""
            result = await self._call_director(system_prompt, "", max_tokens=80, parser="text")

        return {"narration": result.get("text", "")}

    async def handle_director_chapter(self, payload: Dict) -> Dict:
        """导演章节命名：根据故事上下文生成有叙事衔接感的章节标题。"""
        chapter_num = payload.get("chapter_num", 1)
        events = payload.get("events", [])
        dialogues = payload.get("recent_dialogues", [])
        tension = payload.get("tension", "平静")
        secrets_revealed = payload.get("secrets_revealed", [])
        character_names = payload.get("character_names", [])
        prev_chapter_title = payload.get("prev_chapter_title", "")

        events_text = "\n".join(f"  - {e}" for e in events[-8:]) or "（无关键事件）"
        dialogue_text = "\n".join(f"  - {d}" for d in dialogues[-12:]) or "（暂无对话）"
        secrets_text = ", ".join(secrets_revealed[-3:]) or "无"
        chars_text = "、".join(character_names) if character_names else "众角色"
        name_a = character_names[0] if len(character_names) > 0 else "某人"
        name_b = character_names[1] if len(character_names) > 1 else "另一人"

        system_prompt = f"""你是悬疑小说《雪隐》的编辑。你正在为小说的新章节命名。

故事背景：暴风雪夜，雪山别墅「雪隐」。{chars_text}被困在别墅中，每个人都有自己的秘密。

【命名要求】
- 必须使用中文输出，禁止英文
- 章节标题必须和本章实际发生的事件紧密衔接
- 标题应优先体现对话中的关键转折、质问或揭示，而非仅依赖事件标签
- 如果对话中出现了实质性信息交换、对立或情感爆发，标题应反映这一点
- 标题风格：悬疑小说的章回体，8-15字
- 要体现本章的核心事件或转折，不能是泛泛的"风云突变"之类的空话
- 可以提及关键人物的行动、关键发现、或氛围转折
- 参考风格：「灯灭之后，三楼的闷响」「{name_a}的沉默与未说出口的话」「{name_b}发现了暗处的线索」

【输出格式——严格JSON】
{{"title": "章节标题（不含"第X章："前缀，纯中文8-15字）"}}"""

        user_prompt = f"""当前是第{chapter_num}章。上一章标题是「{prev_chapter_title or "故事开始"}」。
紧张度：{tension}。本章揭露的秘密：{secrets_text}。

本章关键事件：
{events_text}

最近的对话片段：
{dialogue_text}

请为这一章起一个能衔接故事内容的标题。输出JSON。"""

        result = await self._call_director(system_prompt, user_prompt, max_tokens=100, parser="text")
        title = result.get("text", "").strip()
        try:
            import json as _json
            cleaned = title.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = _json.loads(cleaned)
            title = data.get("title", title)
        except Exception:
            pass
        return {"title": title if title else f"第{chapter_num}章"}

    async def handle_director_chapter_summary(self, payload: Dict) -> Dict:
        """导演章节总结：根据本章事件生成有叙事感的章节摘要。"""
        events = payload.get("events", [])
        dialogues = payload.get("recent_dialogues", [])
        chapter_title = payload.get("chapter_title", "")
        tension = payload.get("tension", "平静")
        character_names = payload.get("character_names", [])

        events_text = "\n".join(f"  - {e}" for e in events) or "（无关键事件）"
        dialogue_text = "\n".join(f"  - {d}" for d in dialogues[-8:]) or "（暂无对话）"
        chars_text = "、".join(character_names) if character_names else "众角色"

        system_prompt = f"""你是悬疑小说的编辑。请用一句话（30字以内）概括这一章的故事推进。

【场景】暴风雪中的雪山别墅。角色：{chars_text}。

要求：
- 必须体现本章故事相对于上一章的具体推进
- 用叙事化的语言，不要模板化
- 不要超过30字

【输出格式——严格JSON】
{{"summary": "一句概括（30字内）"}}"""

        user_prompt = f"""章节标题：「{chapter_title}」。紧张度：{tension}。

关键事件：
{events_text}

对话片段：
{dialogue_text}

用一句话概括本章的故事推进。输出JSON。"""

        result = await self._call_director(system_prompt, user_prompt, max_tokens=80, parser="text")
        summary = result.get("text", "").strip()
        try:
            import json as _json
            cleaned = summary.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = _json.loads(cleaned)
            summary = data.get("summary", summary)
        except Exception:
            pass
        return {"summary": summary if summary else "故事在紧张的氛围中继续推进。"}

    async def _call_director(self, system_prompt: str, user_prompt: str, max_tokens: int = 300, parser: str = "action") -> Dict:
        """调用导演专用 LLM。"""
        api_key = _get_director_api_key()
        if not api_key:
            return {"text": ""} if parser == "text" else \
                   {"tension_change": None, "reveal_secret": None, "generate_event": False,
                    "event_idea": None, "scene_goal": "自然推进剧情", "narration": "", "reasoning": "无 API Key"}

        model = _director_model()
        temperature = _director_temperature()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    DEEPSEEK_URL,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                    json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                          "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]},
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                if parser == "text":
                    return {"text": raw.strip()}
                return self._parse_director(raw) if parser == "director" else self._parse(raw)
        except Exception as e:
            logger.error(f"导演 LLM 调用失败: {e}")
            return {"text": ""} if parser == "text" else \
                   {"tension_change": None, "reveal_secret": None, "generate_event": False,
                    "event_idea": None, "scene_goal": "自然推进剧情", "narration": "", "reasoning": f"API 错误: {e}"}

    def _parse_director(self, raw: str) -> Dict:
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(cleaned)
            return {
                "tension_change": data.get("tension_change"),
                "reveal_secret": data.get("reveal_secret"),
                "generate_event": data.get("generate_event", False),
                "event_idea": data.get("event_idea"),
                "scene_goal": data.get("scene_goal", "自然推进剧情"),
                "narration": data.get("narration", ""),
                "reasoning": data.get("reasoning", ""),
            }
        except (json.JSONDecodeError, KeyError):
            return {"tension_change": None, "reveal_secret": None, "generate_event": False,
                    "event_idea": None, "scene_goal": raw[:50] if raw else "自然推进剧情",
                    "narration": "", "reasoning": "解析失败"}


def register_llm_handler():
    h = LLMHandler()
    bus.register("llm", {
        "llm_generate_scene":          h.handle_generate_scene,
        "llm_decide_action":           h.handle_decide_action,
        "llm_generate_dialogue":       h.handle_generate_dialogue,
        "llm_generate_thought":        h.handle_generate_thought,
        "llm_evaluate_intervention":   h.handle_evaluate_intervention,
        "llm_generate_characters":     h.handle_generate_characters,
        "llm_director_decide":         h.handle_director_decide,
        "llm_director_narration":      h.handle_director_narration,
        "llm_director_chapter":        h.handle_director_chapter,
        "llm_director_chapter_summary": h.handle_director_chapter_summary,
    })
    return h
