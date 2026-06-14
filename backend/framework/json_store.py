import json
import os
from typing import Any


class JsonStore:
    """JSON 文件存储基类。子类实现 _default_data() 和 _to_dict() / _from_dict()。"""

    def __init__(self, storage_dir: str, filename: str):
        self._path = os.path.join(storage_dir, filename)
        self._data: Any = self._default_data()
        self.load()

    def _default_data(self) -> Any:
        raise NotImplementedError

    def load(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        if os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as f:
                self._from_dict(json.load(f))
        else:
            self.save()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._to_dict(), f, ensure_ascii=False, indent=2, default=str)

    def _to_dict(self) -> Any:
        raise NotImplementedError

    def _from_dict(self, d: Any) -> None:
        raise NotImplementedError
