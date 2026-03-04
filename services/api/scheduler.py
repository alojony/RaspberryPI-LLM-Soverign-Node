import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.base import JobLookupError
import os
from database import SessionLocal, TimerDB, ReminderDB

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/db/pi_node.db")

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=DATABASE_URL)},
    timezone=os.getenv("TZ", "America/Chicago"),
)


async def fire_reminder(reminder_id: int, text: str):
    logger.info(f"[REMINDER] #{reminder_id}: {text}")
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
