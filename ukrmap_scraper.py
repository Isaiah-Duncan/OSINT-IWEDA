"""
ukrmap_scraper.py
-----------------
Scrapes geolocated strike events from map.ukrdailyupdate.com
using the internal API endpoint discovered via reverse engineering.

Role in architecture:
  ukrdailyupdate.com --> ukrmap_scraper.py --> database.py --> database.db

Used for:
  - 24-hour verification of predictions (daily run)
  - Near-real-time event data supplementing ACLED historical base

Schedule:
  Called by scheduler.py every 24 hours

How it works:
  The site loads events via a PHP endpoint: api.php?action=getFilteredEvents
  This accepts a POST with date range and returns JSON.
  Session cookie (PHPSESSID) is obtained by visiting the homepage first.
  cloudscraper handles Cloudflare bypass automatically.

Usage:
  python ukrmap_scraper.py --test        # fetch last 24hrs, print, no DB
  python ukrmap_scraper.py --sync        # fetch last 24hrs, write to DB
  python ukrmap_scraper.py --days 7      # fetch last N days
"""

import re
import json
import time
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cloudscraper

import sys
sys.path.append(str(Path(__file__).parent))
import database

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [UKRMAP] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/ukrmap_scraper.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://map.ukrdailyupdate.com"
API_URL     = f"{BASE_URL}/api.php?action=getFilteredEvents"
MAX_RETRIES = 3
RETRY_DELAY = 10

# Day number epoch — ukrdailyupdate uses days since Unix epoch / 86400
# date=20509 corresponds to 2026-02-25
DAY_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Icon names that indicate Russian strike events
STRIKE_ICONS = {
    "red_plane":       "airstrike",
    "plane":           "airstrike",
    "red_rocket":      "missile",
    "rocket":          "missile",
    "red_drone":       "drone",
    "drone":           "drone",
    "kamikaze":        "drone_kamikaze",
    "red_explosion":   "explosion",
    "explosion":       "explosion",
    "red_shell":       "artillery",
    "shell":           "artillery",
    "red_missile":     "missile",
    "missile":         "missile",
}

# Keywords in title that indicate Russian offensive events
STRIKE_TITLE_KEYWORDS = [
    "russian airstrike", "airstrike", "russian strike",
    "missile", "rocket", "drone strike", "shahed",
    "shelling", "artillery", "explosion", "bombing",
    "russian attack", "kamikaze", "lancet",
]

# ── Session management ─────────────────────────────────────────────────────────

def create_session() -> cloudscraper.CloudScraper:
    """
    Create a cloudscraper session with a valid PHPSESSID cookie.
    Visits the homepage first to obtain the session cookie.
    """
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    log.info("Initializing session with ukrdailyupdate.com")
    r = scraper.get(BASE_URL, timeout=30)

    if r.status_code != 200:
        log.warning(f"Homepage returned {r.status_code} — proceeding anyway")

    session_id = scraper.cookies.get("PHPSESSID", "none")
    log.info(f"Session cookie obtained: PHPSESSID={session_id[:8]}...")

    return scraper


# ── Date utilities ─────────────────────────────────────────────────────────────

def day_number_to_date(day_number: int) -> str:
    """
    Convert ukrdailyupdate day number to ISO date string.
    day_number = days since Unix epoch (1970-01-01)
    e.g. 20509 → "2026-02-25"
    """
    dt = DAY_EPOCH + timedelta(days=day_number)
    return dt.strftime("%Y-%m-%d")


def extract_time_from_description(description: str) -> str:
    """
    Extract time string from event description HTML.
    Format in description: "0:11," or "23:45," etc.
    Returns "HH:MM" or "00:00" if not found.
    """
    # Strip HTML tags first
    clean = re.sub(r"<[^>]+>", "", description)

    # Look for time pattern at start of a line: "0:11," or "23:45,"
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", clean)
    if match:
        hour   = match.group(1).zfill(2)
        minute = match.group(2)
        return f"{hour}:{minute}"

    return "00:00"


def build_timestamp(day_number: int, description: str) -> str:
    """
    Build ISO 8601 UTC timestamp from day number + time in description.
    """
    date_str = day_number_to_date(day_number)
    time_str = extract_time_from_description(description)
    return f"{date_str}T{time_str}:00+00:00"


def extract_telegram_source(description: str) -> str:
    """
    Extract first Telegram source URL from description HTML.
    Returns URL string or empty string.
    """
    match = re.search(r'href="(https://t\.me/[^"]+)"', description)
    if match:
        return match.group(1)
    return ""


# ── Event classification ───────────────────────────────────────────────────────

def is_strike_event(event: dict) -> bool:
    """
    Returns True if this event represents a Russian strike or attack.
    Filters out Ukrainian actions, civilian incidents, and non-strike events.
    """
    title     = event.get("title", "").lower()
    icon_name = event.get("icon_name", "").lower()
    icon_color = event.get("icon_color", "").lower()

    # Must be Russian (red = Russian in this map's color scheme)
    if icon_color and icon_color not in ("ru", "red", ""):
        return False

    # Check title keywords
    if any(kw in title for kw in STRIKE_TITLE_KEYWORDS):
        return True

    # Check icon type
    if any(icon in icon_name for icon in STRIKE_ICONS):
        return True

    return False


def classify_from_event(event: dict) -> str:
    """
    Classify event type from icon_name and title.
    """
    icon_name = event.get("icon_name", "").lower()
    title     = event.get("title", "").lower()
    text      = f"{icon_name} {title}"

    if "shahed" in text or "kamikaze" in text or "geran" in text:
        return "drone_kamikaze"
    if "lancet" in text:
        return "drone_loitering"
    if "drone" in text:
        return "drone"
    if "plane" in text or "airstrike" in text or "air strike" in text:
        return "airstrike"
    if "rocket" in text:
        return "rocket"
    if "missile" in text or "kalibr" in text or "iskander" in text:
        return "missile"
    if "shell" in text or "artillery" in text or "shelling" in text:
        return "artillery"
    if "explosion" in text:
        return "explosion"

    return "unknown"


# ── Normalization ──────────────────────────────────────────────────────────────

def normalize_event(raw: dict) -> dict | None:
    """
    Normalize one ukrdailyupdate event into our database schema.
    Returns None if event should be filtered out.
    """
    if not is_strike_event(raw):
        return None

    try:
        lat = float(raw["lat"])
        lng = float(raw["lng"])
    except (KeyError, ValueError, TypeError):
        return None

    day_number  = int(raw.get("date", 0))
    description = raw.get("description", "")
    title       = raw.get("title", "").strip()
    event_id    = str(raw.get("id", ""))

    if not event_id or not title:
        return None

    timestamp = build_timestamp(day_number, description)
    source_url = extract_telegram_source(description)

    # Strip HTML from description for storage
    clean_desc = re.sub(r"<[^>]+>", " ", description).strip()
    clean_desc = re.sub(r"\s+", " ", clean_desc)[:1000]

    return {
        "event_id":      f"ukrmap_{event_id}",
        "timestamp_utc": timestamp,
        "latitude":      lat,
        "longitude":     lng,
        "title":         title,
        "description":   clean_desc,
        "event_type":    classify_from_event(raw),
        "source_url":    source_url,
        "region":        "ukraine",
        "oblast":        "",
        "location_name": "",
        "actor":         "Russian Forces",
        "fatalities":    0,
        "geo_precision": 1,
        "acled_source":  "",
        "data_source":   "ukrdailyupdate",
        "raw_json":      json.dumps(raw),
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
    }


# ── Core fetch ─────────────────────────────────────────────────────────────────

def fetch_events(
    from_date: str,
    to_date:   str,
    scraper:   cloudscraper.CloudScraper = None
) -> list[dict]:
    """
    Fetch all events for a date range from the API.

    Args:
        from_date: "YYYY-MM-DD"
        to_date:   "YYYY-MM-DD"
        scraper:   existing session (creates new one if None)

    Returns:
        List of raw event dicts
    """
    if scraper is None:
        scraper = create_session()

    payload = {
        "search":     "",
        "bbox":       "",
        "from":       from_date,
        "to":         to_date,
        "title_only": 0,
    }

    headers = {
        "Referer":           BASE_URL + "/",
        "X-Requested-With":  "XMLHttpRequest",
        "Content-Type":      "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept":            "application/json, text/javascript, */*; q=0.01",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"Fetching events {from_date} → {to_date} (attempt {attempt})")

            r = scraper.post(API_URL, data=payload, headers=headers, timeout=60)

            log.info(f"Response: {r.status_code}, size={len(r.text):,} chars")

            if r.status_code != 200:
                log.warning(f"HTTP {r.status_code}")
                time.sleep(RETRY_DELAY)
                continue

            # Strip PHP warnings before the JSON using string find (not regex)
            raw_text   = r.text
            json_start = raw_text.find('{"message":')
            if json_start == -1:
                log.error("No JSON found in response")
                log.debug(f"Response preview: {raw_text[:300]}")
                return []

            clean_json = raw_text[json_start:]
            data       = json.loads(clean_json)

            events = list(data.get("events", {}).values())
            log.info(f"Fetched {len(events)} raw events ({data.get('message', '?')})")
            return events

        except json.JSONDecodeError as e:
            log.error(f"JSON parse error: {e}")
            return []

        except Exception as e:
            log.error(f"Fetch error (attempt {attempt}): {e}")
            time.sleep(RETRY_DELAY * attempt)

    log.error("All fetch attempts failed")
    return []


# ── Main operations ────────────────────────────────────────────────────────────

def run_sync(days_back: int = 1) -> dict:
    """
    Fetch events for the last N days, normalize, write to DB.
    Primary use: daily 24-hour verification against predictions.
    Called by scheduler.py.
    """
    to_date   = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    log.info(f"Sync: {from_date} → {to_date}")

    scraper    = create_session()
    raw_events = fetch_events(from_date, to_date, scraper)

    inserted  = 0
    skipped   = 0
    filtered  = 0
    errors    = 0

    for raw in raw_events:
        try:
            normalized = normalize_event(raw)
            if not normalized:
                filtered += 1
                continue

            was_inserted = database.insert_event(normalized)
            if was_inserted:
                inserted += 1
                log.debug(f"NEW: [{normalized['event_type']}] {normalized['title']} @ {normalized['timestamp_utc']}")
            else:
                skipped += 1

        except Exception as e:
            log.error(f"Error processing event {raw.get('id', '?')}: {e}")
            errors += 1

    stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fetched":   len(raw_events),
        "processed": len(raw_events) - filtered,
        "inserted":  inserted,
        "duplicates": skipped,
        "filtered":  filtered,
        "errors":    errors,
    }

    log.info(f"Sync complete: {stats}")
    database.log_scraper_run(stats)
    return stats


def run_test(days_back: int = 1) -> None:
    """
    Test mode — fetch and print events without writing to DB.
    """
    to_date   = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    log.info(f"TEST MODE — {from_date} → {to_date}, no DB writes")

    scraper    = create_session()
    raw_events = fetch_events(from_date, to_date, scraper)

    print(f"\n{'='*60}")
    print(f"RAW EVENTS: {len(raw_events)}")
    print(f"{'='*60}")

    strike_count = 0
    for raw in raw_events[:20]:   # Print first 20 only
        normalized = normalize_event(raw)
        if normalized:
            strike_count += 1
            print(f"\n[{normalized['event_type'].upper()}]")
            print(f"  Title:     {normalized['title']}")
            print(f"  Timestamp: {normalized['timestamp_utc']}")
            print(f"  Coords:    {normalized['latitude']}, {normalized['longitude']}")
            print(f"  Source:    {normalized['source_url']}")
            print(f"  Desc:      {normalized['description'][:100]}...")

    total_strikes = sum(1 for e in raw_events if normalize_event(e))
    print(f"\n{'='*60}")
    print(f"Total raw: {len(raw_events)} | Strike events: {total_strikes}")
    print(f"{'='*60}\n")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ukrdailyupdate scraper")
    parser.add_argument("--test",  action="store_true", help="Fetch and print, no DB write")
    parser.add_argument("--sync",  action="store_true", help="Fetch and write to DB")
    parser.add_argument("--days",  type=int, default=1, help="Days back to fetch (default: 1)")
    args = parser.parse_args()

    Path("logs").mkdir(exist_ok=True)
    database.init_db()

    if args.test:
        run_test(days_back=args.days)
    elif args.sync:
        stats = run_sync(days_back=args.days)
        print(json.dumps(stats, indent=2))
    else:
        print("Specify --test or --sync")
        print("Start with: python ukrmap_scraper.py --test")
