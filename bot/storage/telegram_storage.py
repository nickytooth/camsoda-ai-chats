import json
import random
from pathlib import Path
from bot.storage.base import StorageBackend, ContentFile

INDEX_FILE = "content_index.json"


class TelegramStorage(StorageBackend):
    def __init__(self, index_path: str | Path | None = None):
        self.index_path = Path(index_path) if index_path else Path(INDEX_FILE)
        self._index: dict[str, list[dict]] | None = None

    def _load_index(self) -> dict[str, list[dict]]:
        if self._index is not None:
            return self._index
        if not self.index_path.exists():
            self._index = {}
            return self._index
        with open(self.index_path, "r", encoding="utf-8") as f:
            self._index = json.load(f)
        return self._index

    async def get_categories(self) -> list[str]:
        index = self._load_index()
        return list(index.keys())

    async def get_file(self, category: str, exclude_ids: list[str] | None = None) -> ContentFile | None:
        index = self._load_index()
        items = index.get(category, [])
        if not items:
            return None

        exclude_ids = set(exclude_ids or [])
        available = [item for item in items if item["file_id"] not in exclude_ids]
        if not available:
            return None

        chosen = random.choice(available)
        return ContentFile(
            content_id=chosen["file_id"],
            category=category,
            file_id=chosen["file_id"],
            is_video=chosen.get("is_video", False),
        )

    async def get_category_count(self, category: str) -> int:
        index = self._load_index()
        return len(index.get(category, []))
