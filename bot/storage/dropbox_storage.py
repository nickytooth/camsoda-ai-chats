import random
import logging
import dropbox
from dropbox.files import FileMetadata, FolderMetadata
from bot.storage.base import StorageBackend, ContentFile

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALL_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS


class DropboxStorage(StorageBackend):
    def __init__(self, app_key: str, app_secret: str, refresh_token: str, root_folder: str = "/bot_content"):
        self.root_folder = root_folder
        self._dbx = dropbox.Dropbox(
            app_key=app_key,
            app_secret=app_secret,
            oauth2_refresh_token=refresh_token,
        )
        self._cache: dict[str, list[dict]] = {}

    def _list_folder(self, path: str) -> list:
        entries = []
        try:
            result = self._dbx.files_list_folder(path)
            entries.extend(result.entries)
            while result.has_more:
                result = self._dbx.files_list_folder_continue(result.cursor)
                entries.extend(result.entries)
        except Exception as e:
            logger.error("Dropbox list_folder error for %s: %s", path, e)
        return entries

    async def get_categories(self) -> list[str]:
        entries = self._list_folder(self.root_folder)
        return [e.name for e in entries if isinstance(e, FolderMetadata)]

    async def get_file(self, category: str, exclude_ids: list[str] | None = None) -> ContentFile | None:
        folder_path = f"{self.root_folder}/{category}"
        entries = self._list_folder(folder_path)

        files = [
            e for e in entries
            if isinstance(e, FileMetadata)
            and any(e.name.lower().endswith(ext) for ext in ALL_EXTENSIONS)
        ]

        exclude_ids = set(exclude_ids or [])
        available = [f for f in files if f.path_lower not in exclude_ids]
        if not available:
            return None

        chosen = random.choice(available)
        try:
            _, response = self._dbx.files_download(chosen.path_lower)
            file_bytes = response.content
        except Exception as e:
            logger.error("Dropbox download error for %s: %s", chosen.path_lower, e)
            return None

        is_video = any(chosen.name.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)
        return ContentFile(
            content_id=chosen.path_lower,
            category=category,
            file_bytes=file_bytes,
            is_video=is_video,
        )

    async def get_category_count(self, category: str) -> int:
        folder_path = f"{self.root_folder}/{category}"
        entries = self._list_folder(folder_path)
        return len([
            e for e in entries
            if isinstance(e, FileMetadata)
            and any(e.name.lower().endswith(ext) for ext in ALL_EXTENSIONS)
        ])
