"""Location-synced selfie picker.

CANONICAL CONTENT LAYOUT (put Victoria's photos here):

    content/
      Bedroom/    1.jpg 2.jpg ...
      Bathroom/
      Car/
      Kitchen/
      Livingroom/
      Office/

One folder per location; numerically-named files are sent in order. Folder
names are matched case-insensitively, and a few spelling variants are accepted
via LOCATION_ALIASES for backward compatibility. A legacy `content/victoria/<Location>`
root is also still scanned. For NEW content, use the flat `content/<Location>`
layout above. The folder a photo lives in must map to a location tag emitted by
`time_context.get_preferred_tags()` so it can be selected for the current scene.
"""

import time
from pathlib import Path

from bot.config import CONTENT_DIR
from bot.memory.db import get_connection
from bot.time_context import get_preferred_tags

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PHOTO_ROOTS = [CONTENT_DIR / "victoria", CONTENT_DIR]
CATEGORY = "victoria_photo"
LOCATION_ALIASES = {
    "kitchen": ["kitchen", "Kitchen"],
    "living room": ["living_room", "livingroom", "Livingroom", "LivingRoom", "living room", "Living Room"],
    "living_room": ["living_room", "livingroom", "Livingroom", "LivingRoom", "living room", "Living Room"],
    "bathroom": ["bathroom", "Bathroom"],
    "car": ["car", "Car"],
    "office": ["office", "Office"],
    "desk": ["desk", "Desk", "office", "Office"],
    "bedroom": ["bedroom", "Bedroom"],
    "bed": ["bed", "Bed", "bedroom", "Bedroom"],
}


def _url_for(path: Path) -> str:
    rel = path.relative_to(CONTENT_DIR).as_posix()
    return f"/content/{rel}"


def _location_folders(location: str) -> list[Path]:
    names = {name.lower() for name in LOCATION_ALIASES.get(location, [location])}
    folders: list[Path] = []
    seen: set[Path] = set()
    for root in PHOTO_ROOTS:
        if not root.exists() or not root.is_dir():
            continue
        for folder in root.iterdir():
            if folder.is_dir() and folder.name.lower() in names and folder not in seen:
                folders.append(folder)
                seen.add(folder)
    return folders


def _sort_key(path: Path) -> tuple[int, str]:
    try:
        return int(path.stem), path.name.lower()
    except ValueError:
        return 10**9, path.name.lower()


def _eligible_photos() -> list[tuple[str, Path, str]]:
    photos: list[tuple[str, Path, str]] = []
    for location in get_preferred_tags():
        for folder in _location_folders(location):
            for path in sorted(folder.iterdir(), key=_sort_key):
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                    photos.append((location, path, _url_for(path)))
    return photos


async def _sent_ids(user_id: int, urls: set[str]) -> set[str]:
    if not urls:
        return set()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT content_id FROM sent_content WHERE user_id = ? AND category = ?",
            (user_id, CATEGORY),
        )
        rows = await cursor.fetchall()
        return {row["content_id"] for row in rows if row["content_id"] in urls}
    finally:
        await conn.close()


async def _mark_sent(user_id: int, url: str) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO sent_content (user_id, content_id, category, sent_at, paid) VALUES (?, ?, ?, ?, 0)",
            (user_id, url, CATEGORY, time.time()),
        )
        await conn.commit()
    finally:
        await conn.close()


async def _reset_sent(user_id: int, urls: set[str]) -> None:
    if not urls:
        return
    conn = await get_connection()
    try:
        for url in urls:
            await conn.execute(
                "DELETE FROM sent_content WHERE user_id = ? AND category = ? AND content_id = ?",
                (user_id, CATEGORY, url),
            )
        await conn.commit()
    finally:
        await conn.close()


async def is_photo_unlocked(user_id: int, url: str) -> bool:
    """True if this user has already paid to reveal this photo."""
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT 1 FROM sent_content WHERE user_id = ? AND category = ? "
            "AND content_id = ? AND paid = 1 LIMIT 1",
            (user_id, CATEGORY, url),
        )
        return await cursor.fetchone() is not None
    finally:
        await conn.close()


async def mark_photo_unlocked(user_id: int, url: str) -> None:
    """Flag this photo as paid for this user (revealing it permanently). Inserts
    a row if the photo wasn't tracked as sent yet."""
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "UPDATE sent_content SET paid = 1 WHERE user_id = ? AND category = ? "
            "AND content_id = ? RETURNING id",
            (user_id, CATEGORY, url),
        )
        updated = await cursor.fetchone()
        if not updated:
            await conn.execute(
                "INSERT INTO sent_content (user_id, content_id, category, sent_at, paid) "
                "VALUES (?, ?, ?, ?, 1)",
                (user_id, url, CATEGORY, time.time()),
            )
        await conn.commit()
    finally:
        await conn.close()


async def pick_current_location_photo(user_id: int) -> str | None:
    photos = _eligible_photos()
    if not photos:
        return None
    urls = {url for _, _, url in photos}
    sent = await _sent_ids(user_id, urls)
    for _, _, url in photos:
        if url not in sent:
            await _mark_sent(user_id, url)
            return url
    await _reset_sent(user_id, urls)
    url = photos[0][2]
    await _mark_sent(user_id, url)
    return url
