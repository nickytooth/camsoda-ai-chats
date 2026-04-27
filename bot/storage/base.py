from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ContentFile:
    content_id: str
    category: str
    file_path: str | None = None
    file_id: str | None = None
    file_bytes: bytes | None = None
    is_video: bool = False
    teaser_path: str | None = None


class StorageBackend(ABC):
    @abstractmethod
    async def get_categories(self) -> list[str]:
        ...

    @abstractmethod
    async def get_file(self, category: str, exclude_ids: list[str] | None = None) -> ContentFile | None:
        ...

    @abstractmethod
    async def get_category_count(self, category: str) -> int:
        ...
