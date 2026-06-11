import random
from pathlib import Path
from bot.storage.base import StorageBackend, ContentFile

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALL_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
TEASER_NAMES = {"teaser.jpg", "teaser.jpeg", "teaser.png", "teaser.webp"}  # preferred names


class LocalStorage(StorageBackend):
    def __init__(self, root_path: str | Path):
        self.root = Path(root_path)

    async def get_categories(self) -> list[str]:
        if not self.root.exists():
            return []
        return [d.name for d in self.root.iterdir() if d.is_dir()]

    async def get_file(self, category: str, exclude_ids: list[str] | None = None, tag: str | None = None) -> ContentFile | None:
        cat_dir = self.root / category
        if not cat_dir.exists():
            return None

        exclude_ids = set(exclude_ids or [])

        if category == "videos":
            return self._get_video_bundle(cat_dir, exclude_ids)

        return self._get_flat_file(cat_dir, category, exclude_ids, tag=tag)

    def _get_flat_file(self, cat_dir: Path, category: str, exclude_ids: set, tag: str | None = None) -> ContentFile | None:
        """Pick a random image/video from a flat folder (selfies), optionally filtered by tag prefix."""
        files = [
            f for f in cat_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ALL_EXTENSIONS and str(f) not in exclude_ids
        ]

        # Filter by tag prefix if specified
        if tag and files:
            tagged = [f for f in files if f.stem.lower().startswith(f"{tag.lower()}_")]
            if tagged:
                files = tagged
            # else: fall through to all files (no match for this tag)

        if not files:
            return None

        chosen = random.choice(files)
        return ContentFile(
            content_id=str(chosen),
            category=category,
            file_path=str(chosen),
            is_video=chosen.suffix.lower() in VIDEO_EXTENSIONS,
        )

    def _get_video_bundle(self, videos_dir: Path, exclude_ids: set) -> ContentFile | None:
        """Pick a random video subfolder with paired teaser.
        
        Structure: videos/001/teaser.jpg + videos/001/video.mp4
        content_id is the subfolder path (e.g. "content/videos/001")
        """
        subfolders = [
            d for d in videos_dir.iterdir()
            if d.is_dir() and str(d) not in exclude_ids
        ]
        if not subfolders:
            return None

        chosen_dir = random.choice(subfolders)

        # Find the video file
        video_file = None
        for f in chosen_dir.iterdir():
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                video_file = f
                break

        if not video_file:
            return None

        # Find the teaser image (prefer 'teaser.*', fallback to any image)
        teaser_file = None
        any_image = None
        for f in chosen_dir.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                if f.name.lower() in TEASER_NAMES:
                    teaser_file = f
                    break
                any_image = f
        if not teaser_file:
            teaser_file = any_image

        return ContentFile(
            content_id=str(chosen_dir),
            category="videos",
            file_path=str(video_file),
            is_video=True,
            teaser_path=str(teaser_file) if teaser_file else None,
        )

    async def get_available_tags(self, category: str) -> list[str]:
        """Get unique filename tag prefixes for a category (everything before first '_')."""
        cat_dir = self.root / category
        if not cat_dir.exists():
            return []
        tags = set()
        for f in cat_dir.iterdir():
            if f.is_file() and f.suffix.lower() in ALL_EXTENSIONS:
                name = f.stem.lower()
                if "_" in name:
                    tags.add(name.split("_", 1)[0])
                else:
                    tags.add("general")
        return sorted(tags)

    async def get_category_count(self, category: str) -> int:
        cat_dir = self.root / category
        if not cat_dir.exists():
            return 0
        if category == "videos":
            return len([d for d in cat_dir.iterdir() if d.is_dir()])
        return len([f for f in cat_dir.iterdir() if f.is_file() and f.suffix.lower() in ALL_EXTENSIONS])
