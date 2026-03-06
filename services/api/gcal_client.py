import os
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Standard Google Calendar colorId → hex
GCAL_COLOR_MAP = {
    "1": "#a4bdfc",  # Lavender
    "2": "#7ae28c",  # Sage
    "3": "#dbadff",  # Grape
    "4": "#ff887c",  # Flamingo
    "5": "#fbd75b",  # Banana
    "6": "#ffb878",  # Tangerine
    "7": "#46d6db",  # Peacock
    "8": "#e1e1e1",  # Graphite
    "9": "#5484ed",  # Blueberry
    "10": "#51b749", # Basil
    "11": "#dc2127", # Tomato
}
GCAL_DEFAULT_COLOR = "#4285f4"

# Keywords that identify a meeting/appointment worth surfacing in briefings
MEETING_KEYWORDS = {
    "weekly", "monthly", "meeting", "meet", "sync", "syncup", "sync-up",
    "standup", "stand-up", "catchup", "catch-up", "call", "1:1", "1on1",
    "review", "interview", "demo", "retro", "retrospective", "sprint",
    "check-in", "checkin", "session", "workshop", "webinar", "conference",
    "onboarding", "planning", "kickoff", "debrief", "presentation",
}


def is_briefing_worthy(event: dict) -> bool:
    """Return True if the event should appear in the morning briefing.

    Rule: include if non-recurring, OR if title contains a meeting keyword.
    """
    if not event.get("recurring", False):
        return True
    title_words = set(event.get("summary", "").lower().replace("-", " ").split())
    return bool(title_words & MEETING_KEYWORDS)
CREDENTIALS_PATH = os.getenv("GCAL_CREDENTIALS_PATH", "/data/db/gcal_credentials.json")
TOKEN_PATH = os.getenv("GCAL_TOKEN_PATH", "/data/db/gcal_token.json")
REDIRECT_URI = os.getenv("GCAL_REDIRECT_URI", "http://127.0.0.1:8000/calendar/callback")

# In-memory state for the OAuth CSRF state parameter
_flow_state: dict = {}


def credentials_exist() -> bool:
    return Path(CREDENTIALS_PATH).exists()


def is_authorized() -> bool:
    return Path(TOKEN_PATH).exists()


def get_auth_url() -> str:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(CREDENTIALS_PATH, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    url, state = flow.authorization_url(prompt="consent", access_type="offline")
    _flow_state["state"] = state
    return url


def exchange_code(code: str, state: str) -> None:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=_flow_state.get("state", state),
    )
    flow.fetch_token(code=code)
    Path(TOKEN_PATH).write_text(flow.credentials.to_json())
    logger.info("[GCAL] OAuth token saved")


def _get_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(TOKEN_PATH).write_text(creds.to_json())
    return creds if creds and creds.valid else None


def list_events(days_before: int = 1, days_after: int = 35) -> list[dict]:
    if not is_authorized():
        return []
    try:
        from googleapiclient.discovery import build
        creds = _get_creds()
        if not creds:
            return []
        service = build("calendar", "v3", credentials=creds)

        # Fetch calendar default color (one call, cheap)
        try:
            cal_info = service.calendarList().get(calendarId="primary").execute()
            default_color = cal_info.get("backgroundColor", GCAL_DEFAULT_COLOR)
        except Exception:
            default_color = GCAL_DEFAULT_COLOR

        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=days_before)).isoformat()
        time_max = (now + timedelta(days=days_after)).isoformat()
        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=200,
        ).execute()
        events = []
        for item in result.get("items", []):
            start = item["start"].get("dateTime", item["start"].get("date", ""))
            end = item["end"].get("dateTime", item["end"].get("date", ""))
            color_id = item.get("colorId", "")
            color = GCAL_COLOR_MAP.get(color_id, default_color)
            events.append({
                "id": item["id"],
                "summary": item.get("summary", "(no title)"),
                "start": start,
                "end": end,
                "description": item.get("description", ""),
                "source": "google",
                "color": color,
                "url": item.get("htmlLink", ""),
                "recurring": "recurringEventId" in item,
            })
        return events
    except Exception as e:
        logger.warning(f"[GCAL] list_events failed: {e}")
        return []


def create_event(summary: str, start: str, end: str, description: str = "") -> dict:
    from googleapiclient.discovery import build
    creds = _get_creds()
    if not creds:
        raise ValueError("Google Calendar not authorized")
    local_tz = os.getenv("TZ", "UTC")
    service = build("calendar", "v3", credentials=creds)
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": local_tz},
        "end": {"dateTime": end, "timeZone": local_tz},
    }
    created = service.events().insert(calendarId="primary", body=body).execute()
    return {
        "id": created["id"],
        "summary": created.get("summary", ""),
        "source": "google",
        "url": created.get("htmlLink", ""),
    }
