# ============================================================
# worldstate/ground_truth.py —— 客观真相管理器
# ============================================================
# 维护系统的"唯一真实世界"（World Truth）。
# 职责：
#   1. 存储所有地点、物品、关系、时间的真实状态
#   2. 提供原子化更新方法（仅 World Simulator 可调用）
#   3. 记录事件日志
#
# 注意：没有任何实体（玩家/Agent/导演）能直接修改 Ground Truth。
# 所有修改必须通过 World Simulator 的 Intent → Resolution 流程。
# ============================================================

from backend.model.world import WorldTruth, Location, Item, Relationship, GameTime
from typing import Dict, List, Optional


class GroundTruthManager:
    """
    客观真相管理器。
    这是系统的"上帝视角"——唯一知道一切真相的模块。
    """

    def __init__(self):
        self._truth = WorldTruth()

    # ── Read 方法（任何人都可读） ──

    def get_truth(self) -> WorldTruth:
        """获取客观真相的只读快照"""
        return self._truth.model_copy(deep=True)

    def get_location(self, location_id: str) -> Optional[Location]:
        return self._truth.locations.get(location_id)

    def get_item(self, item_id: str) -> Optional[Item]:
        return self._truth.items.get(item_id)

    def get_relationship(self, agent_a: str, agent_b: str) -> Optional[Relationship]:
        key = self._rel_key(agent_a, agent_b)
        return self._truth.relationships.get(key)

    def get_all_locations(self) -> Dict[str, Location]:
        return dict(self._truth.locations)

    def get_all_items(self) -> Dict[str, Item]:
        return dict(self._truth.items)

    # ── Write 方法（仅 World Simulator 调用） ──


    def _apply_update(self, update: Dict) -> None:
        """
        ⭐ World Truth 唯一写入口（核心）
        所有 world change 必须走这里
        """

        update_type = update.get("type")

        # ─────────────────────────────
        # 1. 角色位置变化
        # ─────────────────────────────
        if update_type == "location_change":
            agent_id = update.get("agent_id")
            new_location = update.get("new_location")

            # 写入"物理世界状态"（你当前缺的关键）
            if not hasattr(self._truth, "agent_locations"):
                self._truth.agent_locations = {}

            self._truth.agent_locations[agent_id] = new_location

            self.add_event_log(f"{agent_id} moved to {new_location}")

        # ─────────────────────────────
        # 2. 物品变化
        # ─────────────────────────────
        elif update_type == "item_change":
            item_id = update.get("item_id")
            location_id = update.get("location_id")
            holder_id = update.get("holder_id")

            item = self._truth.items.get(item_id)
            if item:
                item.location_id = location_id
                item.held_by = holder_id

            self.add_event_log(f"item {item_id} updated")

        # ─────────────────────────────
        # 3. 对话 / 事件
        # ─────────────────────────────
        elif update_type == "dialogue":
            self.add_event_log(update.get("text", "dialogue"))

        # ─────────────────────────────
        else:
            self.add_event_log(f"unknown update: {update}")


    def move_agent(self, agent_id: str, location_id: str) -> bool:
        """移动 Agent 到指定地点，直接写入内部 _truth"""
        location = self._truth.locations.get(location_id)
        if not location:
            return False
        if location.locked:
            return False
        self._truth.agent_locations[agent_id] = location_id
        self.add_event_log(f"{agent_id} moved to {location_id}")
        return True

    def get_agent_location(self, agent_id: str) -> Optional[str]:
        """获取 Agent 当前位置"""
        return self._truth.agent_locations.get(agent_id)

    def add_location(self, location: Location) -> None:
        self._truth.locations[location.id] = location

    def add_item(self, item: Item) -> None:
        self._truth.items[item.id] = item

    def move_item(self, item_id: str, location_id: Optional[str], holder_id: Optional[str]) -> bool:
        """移动物品到某地或某人手中"""
        # TODO: 验证规则（如物品是否可移动）
        pass

    def update_relationship(self, a: str, b: str, **kwargs) -> None:
        """更新两个角色之间的关系"""
        key = self._rel_key(a, b)
        if key not in self._truth.relationships:
            self._truth.relationships[key] = Relationship(agent_a=a, agent_b=b)
        # TODO: 应用更新

    def advance_time(self) -> GameTime:
        """
        ⭐ 时间系统（必须统一）
        """

        time = self._truth.time

        # tick +1
        time.tick += 1

        # minute +1（简单模型）
        time.minute += 1

        if time.minute >= 60:
            time.minute = 0
            time.hour += 1

        if time.hour >= 24:
            time.hour = 0
            time.day += 1

        # phase 更新
        if 6 <= time.hour < 12:
            time.phase = "morning"
        elif 12 <= time.hour < 18:
            time.phase = "afternoon"
        elif 18 <= time.hour < 22:
            time.phase = "evening"
        else:
            time.phase = "night"

        return time

    def add_event_log(self, entry: str) -> None:
        self._truth.event_log.append(entry)

    @staticmethod
    def _rel_key(a: str, b: str) -> str:
        return f"{min(a, b)}__{max(a, b)}"
    def move_item(self, item_id: str, location_id: Optional[str], holder_id: Optional[str]) -> bool:
        item = self._truth.items.get(item_id)
        if not item:
            return False

        item.location_id = location_id
        item.held_by = holder_id

        self.add_event_log(f"item {item_id} moved")
        return True