

# ============================================================
# director/info_controller.py —— 信息控制器
# ============================================================
# 负责控制信息的释放节奏（"悬疑感"的来源）。
#
# 核心理念：
#   秘密不能一次性全部曝光，要有节奏地释放。
#   好的悬疑叙事 = 玩家总是"知道一些、但不知道全部"。
#
# 工作流程：
#   1. 初始化时，所有秘密放入 state.hidden_secrets
#   2. 每个 tick，decide_revelation() 判断是否该曝光一个秘密
#   3. 曝光后，秘密从 hidden_secrets 移到 revealed_secrets
#   4. Agent 的信息隔离通过 should_hide_from_agent() 判断
#
# TODO（后续迭代方向）：
#   - 接入 LLM：让导演根据剧情进展动态决定曝光哪个秘密
#   - 支持"部分曝光"：给不同的 Agent 曝光不同程度的信息
#   - 支持玩家干预触发曝光（玩家问对了问题就得到线索）
# ============================================================

from backend.model.narrative import DirectorState, TensionLevel
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


# 两次秘密曝光之间的最短间隔（tick 数）
# 避免信息过快涌现导致玩家来不及消化
MIN_REVELATION_INTERVAL = 80

# 每个紧张度阶段对应的最大曝光数量限制
# 确保关键秘密在正确的叙事阶段才出现
MAX_REVELATIONS_BY_TENSION: Dict[TensionLevel, int] = {
    TensionLevel.CALM:       1,   # 平静阶段：只能曝光 1 个秘密（初步线索）
    TensionLevel.TENSE:      3,   # 紧张阶段：可以曝光 3 个（矛盾激化）
    TensionLevel.CRISIS:     6,   # 危机阶段：大量信息涌现
    TensionLevel.RESOLUTION: 999, # 收束阶段：所有秘密都可以曝光
}


class InfoController:
    """
    信息释放控制器。
    决定哪些秘密应该在什么时候以什么方式曝光。
    """

    # ============================================================
    # 核心决策方法
    # ============================================================

    def decide_revelation(self, state: DirectorState, tick: int) -> Optional[str]:
        """
        决定是否在当前 tick 曝光一个秘密，返回应该曝光的秘密 key。
        
        决策流程：
          1. 检查冷却时间（两次曝光之间需要间隔）
          2. 检查当前紧张度对应的曝光数量上限
          3. 从 hidden_secrets 中选取优先级最高的秘密
          4. 返回该秘密 key，由调用方执行曝光操作
        
        Args:
            state: 当前导演状态
            tick: 当前 tick
            
        Returns:
            Optional[str]: 要曝光的秘密 key，或 None（不曝光）
            
        TODO：
          用 LLM 替换规则决策：
          ```python
          context = build_revelation_context(state, tick)
          response = await llm.generate(context)
          return parse_secret_key(response)
          ```
        """
        # ── 步骤 1：冷却时间检查 ────────────────────────────
        # 刚曝光过秘密，还没到下一次的时间
        if (tick - state.last_revelation_tick) < MIN_REVELATION_INTERVAL:
            return None

        # ── 步骤 2：没有可曝光的秘密 ────────────────────────
        if not state.hidden_secrets:
            return None

        # ── 步骤 3：紧张度阶段曝光数量限制 ──────────────────
        # 已曝光数量 >= 当前阶段上限，不再曝光
        already_revealed = len(state.revealed_secrets)
        max_allowed = MAX_REVELATIONS_BY_TENSION.get(
            state.current_tension, 1
        )
        if already_revealed >= max_allowed:
            logger.debug(
                f"[InfoController] 已曝光 {already_revealed} 个秘密，"
                f"当前阶段上限 {max_allowed}，暂不曝光"
            )
            return None

        # ── 步骤 4：选取要曝光的秘密 ────────────────────────
        # 目前简单选第一个（FIFO 顺序）
        # TODO：后续改为按"重要性权重"或 LLM 决策选取
        secret_to_reveal = state.hidden_secrets[0]

        logger.info(
            f"[InfoController] tick={tick} 决定曝光秘密: {secret_to_reveal} "
            f"(已曝光 {already_revealed}/{max_allowed})"
        )

        return secret_to_reveal

    def mark_as_revealed(self, state: DirectorState, secret_key: str) -> None:
        """
        将一个秘密标记为已曝光。
        
        操作：
          1. 从 hidden_secrets 移除
          2. 加入 revealed_secrets
          3. 更新 last_revelation_tick
          
        注意：这个方法由 DirectorService 在执行曝光后调用，
        不应该直接调用（应先调用 decide_revelation 判断是否应该曝光）。
        
        Args:
            state: 导演状态（会被修改）
            secret_key: 要标记为已曝光的秘密 key
        """
        if secret_key in state.hidden_secrets:
            state.hidden_secrets.remove(secret_key)
            state.revealed_secrets.append(secret_key)
            # 注意：last_revelation_tick 需要调用方传入当前 tick 来更新
            # 这里只做数据迁移，tick 更新在 DirectorService 里做
            logger.info(f"[InfoController] 秘密已曝光: {secret_key}")
        else:
            logger.warning(
                f"[InfoController] 尝试曝光不存在的秘密: {secret_key}"
            )

    # ============================================================
    # 信息隔离方法
    # ============================================================

    def should_hide_from_agent(
        self, secret_key: str, agent_id: str, state: DirectorState
    ) -> bool:
        """
        判断某个秘密是否应该对特定 Agent 隐藏。
        
        这是"信息隔离"的核心：不同 Agent 知道不同的信息，
        这才是悬疑游戏的乐趣所在。
        
        当前实现：
          - 在 hidden_secrets 中的秘密，对所有 Agent 隐藏
          - 已曝光的秘密，对所有 Agent 可见
          
        TODO（后续迭代）：
          实现"差异化信息"：
          - Agent A 知道 secret_1，但不知道 secret_2
          - Agent B 知道 secret_2，但不知道 secret_1
          需要在 state 中维护 per-agent 的知识图谱
          
        Args:
            secret_key: 秘密 key
            agent_id: Agent ID
            state: 导演状态
            
        Returns:
            bool: True 表示应该对该 Agent 隐藏
        """
        # 当前简单实现：隐藏秘密对所有人隐藏
        return secret_key in state.hidden_secrets

    def get_available_clues(
        self, state: DirectorState, location_id: str
    ) -> List[str]:
        """
        获取某个地点当前可供玩家或 Agent 发现的线索列表。

        根据当前紧张度阶段和已揭露的秘密，决定该地点可发现的线索。
        线索来自两部分：已曝光但未被发现的秘密、地点固有线索。
        """
        clues = []

        # ── 地点固有线索（按紧张度阶段释放） ──
        location_clues: Dict[str, List[str]] = {
            "hall":    ["落地钟在午夜停摆", "地毯下有暗红色痕迹"],
            "study":   ["书架后有隐藏隔层", "桌上的信件署名被涂改"],
            "kitchen": ["厨刀有可疑污渍", "垃圾桶里有撕碎的照片"],
            "garden":  ["花坛泥土被新翻过", "围墙边有脚印"],
            "cellar":  ["角落里堆着生锈的工具", "墙壁上有抓痕"],
        }

        if location_id in location_clues:
            all_loc_clues = location_clues[location_id]
            # 每上升一个紧张度阶段，多释放一个线索
            reveal_count = min(int(state.current_tension) + 1, len(all_loc_clues))
            clues.extend(all_loc_clues[:reveal_count])

        # ── 已曝光但未被角色"发现"的秘密（高紧张度时出现） ──
        if state.current_tension >= TensionLevel.TENSE:
            for secret_key in state.revealed_secrets:
                secret_name = secret_key.replace("_", " ")
                clues.append(f"与「{secret_name}」相关的线索")

        return clues

    def initialize_secrets(
        self, state: DirectorState, secret_keys: List[str]
    ) -> None:
        """
        初始化秘密列表（在游戏开始时调用一次）。
        
        将所有秘密加入 hidden_secrets，按重要性排序（
        列表靠前的优先曝光，所以应该把初级线索放前面）。
        
        Args:
            state: 导演状态
            secret_keys: 秘密 key 列表，顺序决定曝光优先级
        """
        state.hidden_secrets = list(secret_keys)
        state.revealed_secrets = []
        logger.info(f"[InfoController] 初始化秘密: {secret_keys}")