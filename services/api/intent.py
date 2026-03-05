import re
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import dateparser
from database import SessionLocal, ReminderDB, TimerDB
from scheduler import schedule_reminder, schedule_timer

logger = logging.getLogger(__name__)

_INTENT_RE = re.compile(
    r'\b(remind|reminder|set a timer|timer for|set timer|alert me|ping me|don\'t let me forget|notify me)\b',
    re.IGNORECASE
)

def _looks_like_intent(text: str) -> bool:
    return bool(_INTENT_RE.search(text))


async def extract_intent(prompt: str, llm_url: str, local_tz: str) -> dict | None:
    extraction_prompt = (
        "<|system|>You are a data extraction assistant. Extract structured data and output only valid JSON, nothing else."
        "<|user|>Extract the intent from this message. Output JSON with exactly these fields:\n"
        '- "intent": one of "create_reminder", "set_timer", or "none"\n'
        '- "text": the reminder text or timer label (string)\n'
        '- "datetime_str": for reminders, the natural language time expression (string or null)\n'
        '- "duration_str": for timers, the natural language duration (string or null)\n\n'
        f'Message: "{prompt}"\n'
        '<|assistant|>{"intent":'
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)) as client:
            resp = await client.post(
                f"{llm_url}/completion",
                json={"prompt": extraction_prompt, "n_predict": 80, "stream": False,
                      "stop": ["<|user|>", "<|system|>", "\n\n"]},
            )
            resp.raise_for_status()
            raw = '{"intent":' + resp.json().get("content", "")
            return _parse_extraction(raw)
    except Exception as e:
        logger.warning(f"[INTENT] extraction failed: {e}")
        return None


def _parse_extraction(raw: str) -> dict | None:
    raw = re.sub(r"```[a-z]*", "", raw).strip()

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end])
            if data.get("intent") in ("create_reminder", "set_timer", "none"):
                return data
        except json.JSONDecodeError:
            pass

    intent_m = re.search(r'"intent"\s*:\s*"(\w+)"', raw)
    if not intent_m or intent_m.group(1) not in ("create_reminder", "set_timer"):
        return None

    data = {"intent": intent_m.group(1)}

    text_m = re.search(r'"text"\s*:\s*"([^"]+)"', raw)
    data["text"] = text_m.group(1) if text_m else ""

    dt_m = re.search(r'"datetime_str"\s*:\s*"([^"]+)"', raw)
    data["datetime_str"] = dt_m.group(1) if dt_m else None

    dur_m = re.search(r'"duration_str"\s*:\s*"([^"]+)"', raw)
    data["duration_str"] = dur_m.group(1) if dur_m else None

    return data


_TODAY_WORDS = re.compile(
    r'\b(tonight|this evening|this afternoon|this morning|this noon)\b', re.IGNORECASE
)

def _resolve_datetime(datetime_str: str, local_tz: str) -> datetime | None:
    if not datetime_str:
        return None
    # Normalize ambiguous same-day words that dateparser pushes to tomorrow
    normalized = _TODAY_WORDS.sub("today", datetime_str)
    dt = dateparser.parse(
        normalized,
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True, "TIMEZONE": local_tz},
    )
    if dt is None:
        return None
    if dt < datetime.now(timezone.utc):
        return None
    return dt


def _resolve_duration(duration_str: str) -> int | None:
    if not duration_str:
        return None

    dt = dateparser.parse(
        "in " + duration_str,
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True},
    )
    if dt:
        delta = dt - datetime.now(timezone.utc)
        seconds = int(delta.total_seconds())
        if seconds > 0:
            return seconds

    m = re.search(
        r"(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)",
        duration_str,
        re.IGNORECASE,
    )
    if m:
        val = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("s"):
            return val
        elif unit.startswith("m"):
            return val * 60
        elif unit.startswith("h"):
            return val * 3600
    return None


def _format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) or f"{seconds} seconds"


async def execute_intent(extracted: dict, local_tz: str) -> tuple[str | None, str | None]:
    intent = extracted.get("intent")
    text = extracted.get("text", "").strip()

    if intent == "create_reminder":
        dt = _resolve_datetime(extracted.get("datetime_str", ""), local_tz)
        if dt is None:
            return None, "I couldn't parse that time — try something like 'remind me tomorrow at 9am to call the doctor'."
        if not text:
            text = extracted.get("datetime_str", "reminder")

        db = SessionLocal()
        try:
            record = ReminderDB(
                text=text,
                trigger_at=dt.replace(tzinfo=None),
                recurring=None,
                completed=False,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            schedule_reminder(record.id, record.text, record.trigger_at, record.recurring)
            label = dt.strftime("%A, %b %-d at %-I:%M %p")
            return f"Done — reminder set for {label}: \"{text}\".", None
        except Exception as e:
            logger.error(f"[INTENT] reminder DB write failed: {e}")
            return None, "Something went wrong saving the reminder. Try again."
        finally:
            db.close()

    elif intent == "set_timer":
        duration_seconds = _resolve_duration(extracted.get("duration_str", ""))
        if duration_seconds is None:
            return None, "I couldn't parse that duration — try something like 'set a timer for 20 minutes'."
        if not text:
            text = f"{_format_duration(duration_seconds)} timer"

        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            fire_at = now + timedelta(seconds=duration_seconds)
            record = TimerDB(
                label=text,
                duration_seconds=duration_seconds,
                fire_at=fire_at.replace(tzinfo=None),
                fired=False,
                created_at=now.replace(tzinfo=None),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            schedule_timer(record.id, record.label, fire_at)
            return f"Done — timer set for {_format_duration(duration_seconds)}: \"{text}\".", None
        except Exception as e:
            logger.error(f"[INTENT] timer DB write failed: {e}")
            return None, "Something went wrong saving the timer. Try again."
        finally:
            db.close()

    return None, None
