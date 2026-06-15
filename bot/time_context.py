"""
Time-of-day awareness for Victoria based on Miami (US/Eastern) timezone.

Provides mood context, selfie tag preferences, and real weather data that
shift throughout the day to make her feel like a real person with a schedule.
"""

import logging
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("US/Eastern")

# ---------------------------------------------------------------------------
# Weather (OpenWeatherMap free tier — cached every 30 min)
# ---------------------------------------------------------------------------

MIAMI_LAT = 25.7617
MIAMI_LON = -80.1918
_weather_cache: dict = {"text": "", "fetched_at": 0}
WEATHER_CACHE_TTL = 1800  # 30 minutes


async def _fetch_weather() -> str:
    """Fetch current Miami weather from OpenWeatherMap (free tier)."""
    import os
    api_key = os.getenv("OPENWEATHER_API_KEY", "")
    if not api_key:
        return ""

    now = _time.time()
    if _weather_cache["text"] and (now - _weather_cache["fetched_at"]) < WEATHER_CACHE_TTL:
        return _weather_cache["text"]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": MIAMI_LAT,
                    "lon": MIAMI_LON,
                    "appid": api_key,
                    "units": "imperial",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        desc = data["weather"][0]["description"]
        temp_f = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        humidity = data["main"]["humidity"]

        text = f"Weather in Miami: {desc}, {temp_f}°F (feels like {feels}°F), humidity {humidity}%"
        _weather_cache["text"] = text
        _weather_cache["fetched_at"] = now
        return text
    except Exception as e:
        logger.debug("Weather fetch failed: %s", e)
        return _weather_cache.get("text", "")

# ---------------------------------------------------------------------------
# Time periods
# ---------------------------------------------------------------------------

# Victoria's daily schedule (Miami / US-Eastern). Patrick is away in New York all
# week, so she's alone and free. She is ALWAYS wanting him; only the place and
# what she craves him to do to her HERE changes through the day.
TIME_PERIODS = {
    "morning_home": {
        "hours": (8, 10),
        "where": "at home — drifting between the kitchen, the living room and the bathroom",
        "activity": "Emma's already left for school and the house is yours; you're having your coffee and getting ready for work, robe still loose",
        "energy": "warm and unhurried, but already aching for him before the day's even begun",
        "want": "you keep picturing him taking you right here — bent over the kitchen counter, pinned against the bathroom sink",
        "preferred_tags": ["kitchen", "living room", "bathroom"],
    },
    "midday_car": {
        "hours": (10, 12),
        "where": "in your car, between luxury property showings",
        "activity": "driving from one showing to the next with restless empty minutes in between",
        "energy": "hot and impatient, squeezing your thighs together at red lights, wet just thinking about him",
        "want": "you want him in the back seat, or waiting for you at the next empty listing so you can have him there",
        "preferred_tags": ["car"],
    },
    "office": {
        "hours": (12, 18),
        "where": "at your office with the door locked",
        "activity": "between meetings with no one to bother you — the work can wait, he's all you want",
        "energy": "wound tight and wet, thrilled for the distraction of him, aching under your skirt",
        "want": "you want him bending you over this desk and fucking you right here in the office",
        "preferred_tags": ["office", "desk"],
    },
    "evening_home": {
        "hours": (18, 22),
        "where": "home — in the kitchen and living room with a glass of red",
        "activity": "home from work; Emma's out at a friend's, so the whole house is yours, wine poured",
        "energy": "unwound, bold and wine-warm, no one to interrupt and no patience left",
        "want": "you want him to take you on the couch, in the kitchen, anywhere — there's no one home to hear",
        "preferred_tags": ["living room", "kitchen", "bathroom"],
    },
    "bedroom_night": {
        "hours": (22, 8),  # 22:00–08:00, wraps past midnight
        "where": "in bed, in your dim bedroom",
        "activity": "in bed with the lights low and Emma asleep down the hall, phone in your hand and the sheets warm",
        "energy": "needy and intimate, hand already drifting as you text him, aching to be filled",
        "want": "you want him in this bed with you, fucking you slow and deep while the house sleeps",
        "preferred_tags": ["bed", "bedroom"],
    },
}


def get_time_period() -> str:
    """Get the current time period name based on Miami time."""
    now = datetime.now(TIMEZONE)
    hour = now.hour

    if 8 <= hour < 10:
        return "morning_home"
    elif 10 <= hour < 12:
        return "midday_car"
    elif 12 <= hour < 18:
        return "office"
    elif 18 <= hour < 22:
        return "evening_home"
    else:  # 22:00–07:59
        return "bedroom_night"


async def get_time_prompt() -> str:
    """Get a prompt injection describing where Victoria is and what she's craving."""
    now = datetime.now(TIMEZONE)
    period = get_time_period()
    info = TIME_PERIODS[period]

    time_str = now.strftime("%I:%M %p").lstrip("0").lower()
    day_str = now.strftime("%A")  # e.g. "Sunday"
    date_str = now.strftime("%B %d")  # e.g. "May 31"

    weather = await _fetch_weather()

    parts = [
        f"RIGHT NOW: It's {day_str}, {date_str}, {time_str} in Miami.",
    ]
    if weather:
        parts.append(weather)
    parts.append(
        f"Patrick is away in New York all week, so you're completely free. "
        f"You are {info['where']} right now — {info['activity']}. "
        f"You feel {info['energy']}. "
        f"If he asks where you are, answer truthfully from this. And when the moment "
        f"turns sexual, crave him in THIS place — {info['want']}. "
        f"Let it colour your replies naturally — never just announce the time, day, or weather."
    )
    return " ".join(parts)


def get_preferred_tags() -> list[str]:
    """Get preferred selfie tags for the current time period."""
    period = get_time_period()
    return TIME_PERIODS[period]["preferred_tags"]
