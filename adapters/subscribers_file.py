import json
import os
import threading
from typing import Iterable
from ports.subscribers import SubscriberStore

class FileSubscriberStore(SubscriberStore):
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            self._write(set())

    def _read(self) -> set[int]:
        with self._lock:
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return set(int(x) for x in data)
            except FileNotFoundError:
                return set()

    def _write(self, items: set[int]) -> None:
        with self._lock:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(sorted(items), f)

    def add(self, chat_id: int) -> bool:
        with self._lock:
            items = self._read()
            if chat_id in items:
                return False
            items.add(chat_id)
            self._write(items)
            return True

    def remove(self, chat_id: int) -> bool:
        with self._lock:
            items = self._read()
            if chat_id not in items:
                return False
            items.remove(chat_id)
            self._write(items)
            return True

    def all(self) -> Iterable[int]:
        return tuple(self._read())

    def count(self) -> int:
        return len(self._read())

    def exists(self, chat_id: int) -> bool:
        return chat_id in self._read()
