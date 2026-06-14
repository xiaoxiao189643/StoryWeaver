from backend.model.relationship import Relationship
from backend.framework.json_store import JsonStore
from typing import Dict, List, Optional


class RelationshipStore(JsonStore):
    """NPC 关系存储（JSON 文件持久化）"""

    def __init__(self, storage_dir: str = "./data"):
        self._dict: Dict[str, Dict] = {}
        super().__init__(storage_dir, "relationships.json")

    def _key(self, agent_id: str, target_id: str, world_id: Optional[str] = None) -> str:
        if world_id and world_id != "default_world":
            return f"{world_id}::{agent_id}::{target_id}"
        return f"{agent_id}::{target_id}"

    def get_relationships(self, agent_id: str, world_id: Optional[str] = None) -> List[Relationship]:
        result = []
        for value in self._dict.values():
            relationship = Relationship(**value)
            if relationship.agent_id != agent_id:
                continue
            if world_id is None or relationship.world_id == world_id:
                result.append(relationship)
        return result

    def get_relationship(self, agent_id: str, target_id: str, world_id: Optional[str] = None) -> Optional[Relationship]:
        v = self._dict.get(self._key(agent_id, target_id, world_id))
        relationship = Relationship(**v) if v else None
        if relationship and world_id and relationship.world_id != world_id:
            return None
        return relationship

    def update(self, agent_id: str, target_id: str, delta: float, reason: str) -> Relationship:
        key = self._key(agent_id, target_id)
        if key not in self._dict:
            self._dict[key] = {"agent_id": agent_id, "target_id": target_id, "trust_value": 0.0, "attitude": "neutral", "history": []}
        d = self._dict[key]
        d["trust_value"] = max(-100.0, min(100.0, d["trust_value"] + delta))
        d["history"].append(reason)
        v = d["trust_value"]
        d["attitude"] = "friendly" if v >= 60 else ("neutral" if v >= -20 else "hostile")
        self.save()
        return Relationship(**d)

    def decay_all(self, rate: float = 0.003) -> int:
        """自然衰减：所有 NPC 间 trust_value 向 0 趋近。返回变更数。"""
        changed = 0
        for key, d in list(self._dict.items()):
            v = d.get("trust_value", 0.0)
            if abs(v) < 0.5:
                continue
            if v > 0:
                d["trust_value"] = max(0.0, v - rate * 100)
            else:
                d["trust_value"] = min(0.0, v + rate * 100)
            if abs(d["trust_value"]) < 0.5:
                d["trust_value"] = 0.0
            d["attitude"] = "friendly" if d["trust_value"] >= 60 else ("neutral" if d["trust_value"] >= -20 else "hostile")
            changed += 1
        if changed:
            self.save()
        return changed

    def set_relationship(
        self,
        agent_id: str,
        target_id: str,
        trust_value: float,
        attitude: str,
        history: Optional[List[str]] = None,
        **fields,
    ) -> Relationship:
        key = self._key(agent_id, target_id, fields.get("world_id"))
        self._dict[key] = {
            "agent_id": agent_id,
            "target_id": target_id,
            "trust_value": trust_value,
            "attitude": attitude,
            "history": history or [],
            **fields,
        }
        self.save()
        return Relationship(**self._dict[key])

    def _default_data(self): return {}
    def _to_dict(self): return self._dict
    def _from_dict(self, d): self._dict = d
