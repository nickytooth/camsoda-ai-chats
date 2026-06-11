"""
Time-of-day awareness for Aishha based on Miami (US/Eastern) timezone.

Provides mood context, selfie tag preferences, response delay multipliers,
and real weather data that shift throughout the day to make her feel like
a real person with a schedule.
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

TIME_PERIODS = {
    "early_morning": {
        "hours": (5, 9),
        "mood": "sleepy but horny, woke up thinking about someone",
        "activity": "just woke up, still in bed, feeling warm and touchy, scrolling her phone",
        "energy": "low but flirty — sleepy-horny, cozy and wanting attention",
        "preferred_tags": ["bed", "kitchen"],
        "delay_multiplier": 2.5,  # she's "sleeping" or barely awake
    },
    "morning": {
        "hours": (9, 12),
        "mood": "flirty, teasing, bored and looking for someone to entertain her",
        "activity": "doing skincare, maybe studying, but really just wants to flirt",
        "energy": "medium — playful, warm, looking for attention",
        "preferred_tags": ["mirror", "couch", "bed"],
        "delay_multiplier": 1.2,
    },
    "afternoon": {
        "hours": (12, 17),
        "mood": "confident, flirty, feeling herself",
        "activity": "by the pool, studying but distracted, feeling hot and bored",
        "energy": "high — flirty, confident, playful, wants to tease",
        "preferred_tags": ["pool", "couch", "mirror"],
        "delay_multiplier": 1.0,
    },
    "evening": {
        "hours": (17, 21),
        "mood": "hyped, horny, getting ready to go out or stream",
        "activity": "doing makeup, picking outfits, feeling sexy, maybe streaming on CamSoda",
        "energy": "high — flirty, confident, hyped up, feeling herself",
        "preferred_tags": ["mirror", "party"],
        "delay_multiplier": 1.0,
    },
    "night": {
        "hours": (21, 25),  # 21-01 (25 = 1am next day for easy comparison)
        "mood": "uninhibited, horny, tipsy flirty energy",
        "activity": "at a club, streaming, or partying with the girls, feeling bold",
        "energy": "high — uninhibited, chaotic, horny, no filter",
        "preferred_tags": ["party", "couch"],
        "delay_multiplier": 0.8,  # she's active and on her phone
    },
    "late_night": {
        "hours": (1, 5),
        "mood": "horny, vulnerable, intimate, post-party warmth",
        "activity": "just got home, in bed, can't sleep, thinking about sex",
        "energy": "intimate — soft but horny, no filter, wanting connection",
        "preferred_tags": ["bed", "couch"],
        "delay_multiplier": 1.5,
    },
}


def get_time_period() -> str:
    """Get the current time period name based on Miami time."""
    now = datetime.now(TIMEZONE)
    hour = now.hour

    if 5 <= hour < 9:
        return "early_morning"
    elif 9 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    elif 21 <= hour or hour < 1:
        return "night"
    else:  # 1-5
        return "late_night"


async def get_time_prompt() -> str:
    """Get a prompt injection describing what time it is and what Aishha is doing."""
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
        f"You're {info['activity']}. "
        f"Your energy: {info['energy']}. "
        f"Let this naturally color your responses — don't announce the time, day, or weather unless it comes up naturally."
    )
    return " ".join(parts)


def get_preferred_tags() -> list[str]:
    """Get preferred selfie tags for the current time period."""
    period = get_time_period()
    return TIME_PERIODS[period]["preferred_tags"]


def get_response_delay_multiplier() -> float:
    """Get delay multiplier for current time (higher = slower replies)."""
    period = get_time_period()
    return TIME_PERIODS[period]["delay_multiplier"]
