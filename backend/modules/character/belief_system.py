from backend.model.agent import Belief
from backend.framework.json_store import JsonStore
from typing import Dict, Optional


class BeliefSystem(JsonStore):
    """角色认知系统（JSON 文件持久化）"""

    def __init__(self, storage_dir: str = "./data"):
        self._beliefs: Dict[str, Belief] = {}
        super().__init__(storage_dir, "beliefs.json")

    def get_belief(self, agent_id: str) -> Optional[Belief]:
        return self._beliefs.get(agent_id)

    def ensure_belief(self, agent_id: str) -> Belief:
        if agent_id not in self._beliefs:
            self._beliefs[agent_id] = Belief()
        return self._beliefs[agent_id]

    def set_fact(self, agent_id: str, key: str, value: str, certainty: float = 1.0) -> None:
        belief = self.ensure_belief(agent_id)
        belief.facts[key] = value
        belief.certainty[key] = certainty
        self.save()

    def add_suspicion(self, agent_id: str, target: str, level: float) -> None:
        belief = self.ensure_belief(agent_id)
        belief.suspicions[target] = min(1.0, belief.suspicions.get(target, 0.0) + level)
        self.save()

    def get_visible_facts(self, agent_id: str) -> Dict[str, str]:
        belief = self.ensure_belief(agent_id)
        return {k: v for k, v in belief.facts.items() if belief.certainty.get(k, 0) > 0.5}

    def _default_data(self): return {}
    def _to_dict(self): return {aid: b.model_dump() for aid, b in self._beliefs.items()}
    def _from_dict(self, d):
        self._beliefs = {aid: Belief(**b) for aid, b in d.items()}
