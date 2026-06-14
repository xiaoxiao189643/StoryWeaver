from typing import List, Optional, Tuple

from backend.framework.json_store import JsonStore
from backend.modules.memory.schema import DialogueRecord


class DialogueStore(JsonStore):
    """JSON-backed dialogue history storage."""

    def __init__(self, storage_dir: str = "./data"):
        self._records: List[dict] = []
        super().__init__(storage_dir, "dialogues.json")

    def append(self, record: DialogueRecord) -> None:
        self._records.append(record.model_dump())
        self.save()

    def get_history(
        self,
        world_id: str,
        limit: int = 20,
        cursor: Optional[str] = None,
        agent_id: Optional[str] = None,
        other_agent_id: Optional[str] = None,
    ) -> Tuple[List[DialogueRecord], bool]:
        records = [record for record in self._records if record.get("world_id") == world_id]
        if agent_id:
            records = [
                record for record in records
                if record.get("speaker_id") == agent_id or record.get("target_id") == agent_id
            ]
        if other_agent_id:
            records = [
                record for record in records
                if record.get("speaker_id") == other_agent_id or record.get("target_id") == other_agent_id
            ]
        records.sort(key=lambda record: record.get("timestamp", ""), reverse=True)
        if cursor:
            records = [record for record in records if record.get("timestamp", "") <= cursor]
        has_more = len(records) > limit
        return [DialogueRecord(**record) for record in records[:limit]], has_more

    def rollback_after(self, tick: int, world_id: Optional[str] = None) -> int:
        before = len(self._records)
        self._records = [
            record for record in self._records
            if (
                (world_id and record.get("world_id") != world_id)
                or record.get("tick") is None
                or int(record["tick"]) <= tick
            )
        ]
        deleted = before - len(self._records)
        if deleted:
            self.save()
        return deleted

    def _default_data(self):
        return []

    def _to_dict(self):
        return self._records

    def _from_dict(self, data):
        self._records = data
