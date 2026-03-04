import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import os

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/db/pi_node.db")

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=DATABASE_URL)},
    timezone=os.getenv("TZ", "America/Chicago"),
)


async def fire_reminder(reminder_id: int, text: str):
    logger.info(f"[REMINDER] #{reminder_id}: {text}")
    # TODO: push to UI notification / websocket


def schedule_reminder(reminder_id: int, text: str, trigger_at, recurring: str | None):
    trigger_kwargs = {"run_date": trigger_at} if not recurring else {}

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
        )
