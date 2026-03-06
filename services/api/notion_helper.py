import os
import logging
from notion_client import Client

logger = logging.getLogger(__name__)

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_IDS = [x.strip() for x in os.getenv("NOTION_DATABASE_IDS", "").split(",") if x.strip()]
NOTION_CALENDAR_DB_ID = os.getenv("NOTION_CALENDAR_DB_ID", "").strip()


def is_configured() -> bool:
    return bool(NOTION_TOKEN)


def get_client() -> Client:
    return Client(auth=NOTION_TOKEN)


def _rich_text_to_str(rt_list: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rt_list)


def _block_to_text(block: dict) -> str:
    btype = block.get("type", "")
    content = block.get(btype, {})
    if isinstance(content, dict) and "rich_text" in content:
        return _rich_text_to_str(content["rich_text"])
    return ""


def page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _rich_text_to_str(prop.get("title", []))
    return "Untitled"


def page_date(page: dict) -> str | None:
    """Return ISO date string from the first Date property found, or None."""
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "date" and prop.get("date"):
            return prop["date"].get("start")
    return None


def get_database_pages(client: Client, database_id: str) -> list[dict]:
    pages = []
    cursor = None
    while True:
        params: dict = {"database_id": database_id, "page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = client.databases.query(**params)
        pages.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return pages


def get_page_text(client: Client, page_id: str) -> str:
    """Walk top-level blocks of a page and return plain text."""
    lines = []
    cursor = None
    while True:
        params: dict = {"block_id": page_id, "page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = client.blocks.children.list(**params)
        for block in resp.get("results", []):
            text = _block_to_text(block)
            if text:
                lines.append(text)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return "\n".join(lines)


def get_calendar_events(days_before: int = 1, days_after: int = 14) -> list[dict]:
    """Return upcoming events from NOTION_CALENDAR_DB_ID as a list of dicts."""
    if not is_configured() or not NOTION_CALENDAR_DB_ID:
        return []
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_before)).date().isoformat()
    time_max = (now + timedelta(days=days_after)).date().isoformat()
    try:
        client = get_client()
        pages = get_database_pages(client, NOTION_CALENDAR_DB_ID)
        events = []
        for page in pages:
            date_str = page_date(page)
            if not date_str:
                continue
            # Keep only events in range (date strings compare lexicographically)
            if date_str < time_min or date_str > time_max:
                continue
            events.append({
                "id": page["id"],
                "summary": page_title(page),
                "start": date_str,
                "end": date_str,
                "description": "",
                "source": "notion",
                "url": page.get("url", ""),
            })
        events.sort(key=lambda e: e["start"])
        return events
    except Exception as e:
        logger.warning(f"[NOTION] calendar fetch failed: {e}")
        return []
