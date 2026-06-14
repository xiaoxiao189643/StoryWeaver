from pydantic import BaseModel, Field
from backend.framework.json_store import JsonStore
from typing import Dict


class AgentInfluence(BaseModel):
    trust: float = 0.0
    fear: float = 0.0
    liking: float = 0.0
    interaction_count: int = 0
    last_interaction_tick: int = 0
    successful_persuasions: int = 0
    failed_persuasions: int = 0


class PlayerInfluenceSystem(JsonStore):
    """玩家影响系统（JSON 文件持久化）"""

    def __init__(self, storage_dir: str = "./data"):
        self._influences: Dict[str, AgentInfluence] = {}
        super().__init__(storage_dir, "player_influence.json")

    def get_influence(self, agent_id: str) -> AgentInfluence:
        if agent_id not in self._influences:
            self._influences[agent_id] = AgentInfluence()
        return self._influences[agent_id]

    def modify_trust(self, agent_id: str, delta: float) -> None:
        inf = self.get_influence(agent_id)
        inf.trust = max(-1.0, min(1.0, inf.trust + delta))
        self.save()

    def record_interaction(self, agent_id: str, tick: int, success: bool) -> None:
        inf = self.get_influence(agent_id)
        inf.interaction_count += 1
        inf.last_interaction_tick = tick
        if success:
            inf.successful_persuasions += 1
        else:
            inf.failed_persuasions += 1
        self.save()

    def get_persuasion_modifier(self, agent_id: str) -> float:
        inf = self.get_influence(agent_id)
        total = inf.successful_persuasions + inf.failed_persuasions
        history_mod = (inf.successful_persuasions / total - 0.5) * 0.2 if total > 0 else 0.0
        return inf.trust * 0.3 + inf.liking * 0.2 + history_mod

    def decay_all(self, rate: float = 0.005) -> int:
        """自然衰减：所有 agent 的 trust/fear/liking 向 0 趋近。返回变更数。"""
        changed = 0
        for agent_id in list(self._influences.keys()):
            inf = self._influences[agent_id]
            for attr in ("trust", "fear", "liking"):
                v = getattr(inf, attr)
                if abs(v) < 0.001:
                    continue
                new_v = v * (1.0 - rate)
                if abs(new_v) < 0.001:
                    new_v = 0.0
                setattr(inf, attr, max(-1.0, min(1.0, new_v)))
                changed += 1
        if changed:
            self.save()
        return changed

    def _default_data(self): return {}
    def _to_dict(self): return {aid: inf.model_dump() for aid, inf in self._influences.items()}
    def _from_dict(self, d):
        self._influences = {aid: AgentInfluence(**inf) for aid, inf in d.items()}
