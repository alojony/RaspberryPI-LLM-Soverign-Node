import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
import os
from database import SessionLocal, TimerDB, ReminderDB, BriefingDB

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/db/pi_node.db")

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=DATABASE_URL)},
    timezone=os.getenv("TZ", "America/Chicago"),
)


async def _play_alert():
    """Play the alert WAV via aplay. Soft-fails if no audio device or aplay not available."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "aplay", "-q", "/app/sounds/alert.wav",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except Exception as e:
        logger.warning(f"[AUDIO] alert playback failed: {e}")


async def fire_reminder(reminder_id: int, text: str):
    logger.info(f"[REMINDER] #{reminder_id}: {text}")
    await _play_alert()
    db = SessionLocal()
    try:
        record = db.query(ReminderDB).filter(ReminderDB.id == reminder_id).first()
        if record and not record.recurring:
            record.completed = True
            db.commit()
    finally:
        db.close()


def schedule_reminder(reminder_id: int, text: str, trigger_at, recurring: str | None):
    if recurring == "daily":
        scheduler.add_job(
            fire_reminder,
            "cron",
            id=f"reminder_{reminder_id}",
            hour=trigger_at.hour,
            minute=trigger_at.minute,
            kwargs={"reminder_id": reminder_id, "text": text},
            replace_existing=True,
        )
    elif recurring == "weekly":
        scheduler.add_job(
            fire_reminder,
            "cron",
            id=f"reminder_{reminder_id}",
            day_of_week=trigger_at.strftime("%a").lower(),
            hour=trigger_at.hour,
            minute=trigger_at.minute,
            kwargs={"reminder_id": reminder_id, "text": text},
            replace_existing=True,
        )
    else:
        scheduler.add_job(
            fire_reminder,
            "date",
            id=f"reminder_{reminder_id}",
            run_date=trigger_at,
            kwargs={"reminder_id": reminder_id, "text": text},
            replace_existing=True,
        )


async def fire_timer(timer_id: int, label: str):
    logger.info(f"Timer fired: [{timer_id}] {label}")
    await _play_alert()
    db = SessionLocal()
    try:
        record = db.query(TimerDB).filter(TimerDB.id == timer_id).first()
        if record:
            record.fired = True
            db.commit()
    finally:
        db.close()


def schedule_timer(timer_id: int, label: str, fire_at):
    scheduler.add_job(
        fire_timer,
        trigger="date",
        run_date=fire_at,
        kwargs={"timer_id": timer_id, "label": label},
        id=f"timer_{timer_id}",
        replace_existing=True,
    )


def cancel_timer(timer_id: int):
    try:
        scheduler.remove_job(f"timer_{timer_id}")
    except JobLookupError:
        pass


async def generate_briefing():
    from datetime import date, datetime, timedelta, time
    import httpx
    import pytz

    local_tz_name = os.getenv("TZ", "UTC")
    weather_location = os.getenv("WEATHER_LOCATION", "Davis,California")
    local_tz = pytz.timezone(local_tz_name)
    today = datetime.now(local_tz).date()
    today_str = today.isoformat()

    db = SessionLocal()
    try:
        existing = db.query(BriefingDB).filter(BriefingDB.date == today_str).first()
        if existing:
            return
    finally:
        db.close()

    weather_line = ""
    try:
        url = f"https://wttr.in/{weather_location.replace(' ', '+')}?format=j1"
        def _fetch_weather():
            return httpx.get(url, headers={"User-Agent": "pi-node/1.0"}, timeout=15)
        resp = await asyncio.to_thread(_fetch_weather)
        resp.raise_for_status()
        c = resp.json()["current_condition"][0]
        weather_line = f"**Weather:** {c['weatherDesc'][0]['value']}, {c['temp_C']}°C / {c['temp_F']}°F"
    except Exception as e:
        logger.warning(f"[BRIEFING] weather fetch failed: {type(e).__name__}: {e}")

    db = SessionLocal()
    try:
        today_dt = datetime.combine(today, time.min)
        tomorrow_dt = datetime.combine(today + timedelta(days=1), time.min)
        reminders = db.query(ReminderDB).filter(
            ReminderDB.completed == False,
            ReminderDB.trigger_at >= today_dt,
            ReminderDB.trigger_at < tomorrow_dt,
        ).order_by(ReminderDB.trigger_at).all()
        remind_lines = [f"- {r.trigger_at.strftime('%-I:%M %p')}: {r.text}" for r in reminders]
    finally:
        db.close()

    import gcal_client as gcal
    today_str_full = today.isoformat()
    gcal_events = await asyncio.to_thread(gcal.list_events, 0, 1)
    today_events = [
        e for e in gcal_events
        if e["start"][:10] == today_str_full and gcal.is_briefing_worthy(e)
    ]
    today_events.sort(key=lambda e: e["start"])

    lines = [f"## {today.strftime('%A, %B %-d %Y')}"]
    if weather_line:
        lines.append(weather_line)
    lines.append("")
    if remind_lines:
        lines.append("**Today's reminders:**")
        lines.extend(remind_lines)
    else:
        lines.append("**Reminders:** None for today.")
    if today_events:
        lines.append("")
        lines.append("**Today's calendar:**")
        for e in today_events:
            if len(e["start"]) > 10:
                from datetime import datetime as _dt
                t = _dt.fromisoformat(e["start"]).strftime("%-I:%M %p")
                lines.append(f"- {t}: {e['summary']}")
            else:
                lines.append(f"- {e['summary']}")
    content = "\n".join(lines)

    db = SessionLocal()
    try:
        db.add(BriefingDB(date=today_str, content=content, created_at=datetime.utcnow()))
        db.commit()
        logger.info(f"[BRIEFING] Generated briefing for {today_str}")
    finally:
        db.close()


scheduler.add_job(
    generate_briefing,
    trigger=CronTrigger(hour=8, minute=0),
    id="daily_briefing",
    replace_existing=True,
    misfire_grace_time=3600,
)
