"""Scheduler for zMusic.

Supports one-time, recurring, daily, weekly, and 24/7 channel schedules
with timezone-aware cron expressions. Produces schedule items that link
content to specific time slots.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import AppConfig
from .database import get_connection, transaction
from .logging import get_logger

logger = get_logger("zmusic.scheduler")


@dataclass(frozen=True)
class ScheduleItem:
    """A scheduled content slot."""

    id: str
    schedule_id: str
    content_id: str
    start_time: str  # ISO 8601
    end_time: str  # ISO 8601


@dataclass
class ChannelSchedule:
    """A channel's programming schedule."""

    id: str
    channel_id: str
    name: str
    cron_expression: str | None
    timezone: str
    is_active: bool
    items: list[ScheduleItem] = field(default_factory=list)


class Scheduler:
    """Creates and manages channel schedules.

    Supports:
    - one-time streams (single schedule item)
    - recurring streams (cron-based)
    - daily programming
    - weekly programming
    - 24/7 channels
    - timezone-aware schedules
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def create_schedule(
        self,
        channel_id: str,
        name: str,
        timezone: str = "UTC",
        cron_expression: str | None = None,
        is_active: bool = True,
    ) -> str:
        """Create a new schedule for a channel.

        Returns the schedule ID.
        """
        schedule_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO schedules
                (id, channel_id, name, cron_expression, timezone,
                 is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id,
                    channel_id,
                    name,
                    cron_expression,
                    timezone,
                    1 if is_active else 0,
                    now,
                    now,
                ),
            )

        logger.info(
            "Schedule created",
            extra={
                "schedule_id": schedule_id,
                "channel_id": channel_id,
                "schedule_name": name,
                "cron_expression": cron_expression,
                "timezone": timezone,
            },
        )
        return schedule_id

    def add_schedule_item(
        self,
        schedule_id: str,
        content_id: str,
        start_time: str,
        end_time: str,
    ) -> str:
        """Add a content item to a schedule.

        Returns the schedule item ID.
        """
        item_id = str(uuid.uuid4())

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO schedule_items
                (id, schedule_id, content_id, start_time, end_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    schedule_id,
                    content_id,
                    start_time,
                    end_time,
                    datetime.now(tz=UTC).isoformat(),
                ),
            )

        logger.info(
            "Schedule item added",
            extra={
                "item_id": item_id,
                "schedule_id": schedule_id,
                "content_id": content_id,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return item_id

    def create_one_time_stream(
        self,
        channel_id: str,
        content_id: str,
        start_time: str,
        duration_hours: float,
    ) -> tuple[str, str]:
        """Create a one-time stream schedule.

        Returns (schedule_id, item_id).
        """
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(hours=duration_hours)

        schedule_id = self.create_schedule(
            channel_id=channel_id,
            name=f"One-time stream {start_dt.isoformat()}",
            cron_expression=None,
            is_active=True,
        )

        item_id = self.add_schedule_item(
            schedule_id=schedule_id,
            content_id=content_id,
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
        )

        return schedule_id, item_id

    def create_recurring_schedule(
        self,
        channel_id: str,
        name: str,
        cron_expression: str,
        timezone: str = "UTC",
    ) -> str:
        """Create a recurring schedule using cron expression."""
        return self.create_schedule(
            channel_id=channel_id,
            name=name,
            cron_expression=cron_expression,
            timezone=timezone,
            is_active=True,
        )

    def create_daily_programming(
        self,
        channel_id: str,
        programs: list[dict[str, Any]],
        timezone: str = "UTC",
    ) -> str:
        """Create daily repeating programming.

        Each program dict has: name, start_time (HH:MM), duration_hours,
        content_id.
        """
        schedule_id = self.create_schedule(
            channel_id=channel_id,
            name=f"Daily programming ({timezone})",
            cron_expression=None,
            timezone=timezone,
            is_active=True,
        )

        today = datetime.now(tz=UTC).date()
        for program in programs:
            start_time_str = program["start_time"]  # "HH:MM"
            duration_hours = program["duration_hours"]
            content_id = program["content_id"]

            start_dt = datetime.combine(
                today,
                datetime.strptime(start_time_str, "%H:%M").time(),
            ).replace(tzinfo=UTC)
            end_dt = start_dt + timedelta(hours=duration_hours)

            self.add_schedule_item(
                schedule_id=schedule_id,
                content_id=content_id,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
            )

        return schedule_id

    def create_weekly_programming(
        self,
        channel_id: str,
        programs: list[dict[str, Any]],
        timezone: str = "UTC",
    ) -> str:
        """Create weekly repeating programming.

        Each program dict has: name, weekday (0=Monday), start_time (HH:MM),
        duration_hours, content_id.
        """
        schedule_id = self.create_schedule(
            channel_id=channel_id,
            name=f"Weekly programming ({timezone})",
            cron_expression=None,
            timezone=timezone,
            is_active=True,
        )

        # Find the next occurrence of each weekday
        today = datetime.now(tz=UTC).date()
        for program in programs:
            weekday = program["weekday"]  # 0=Monday
            start_time_str = program["start_time"]
            duration_hours = program["duration_hours"]
            content_id = program["content_id"]

            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0 and datetime.now(tz=UTC).hour >= int(
                start_time_str.split(":")[0]
            ):
                days_ahead = 7  # Next week if time already passed today

            target_date = today + timedelta(days=days_ahead)
            start_dt = datetime.combine(
                target_date,
                datetime.strptime(start_time_str, "%H:%M").time(),
            ).replace(tzinfo=UTC)
            end_dt = start_dt + timedelta(hours=duration_hours)

            self.add_schedule_item(
                schedule_id=schedule_id,
                content_id=content_id,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
            )

        return schedule_id

    def create_24_7_schedule(
        self,
        channel_id: str,
        content_ids: list[str],
        timezone: str = "UTC",
    ) -> str:
        """Create a 24/7 looping schedule.

        Distributes content IDs across 24 hours in round-robin fashion.
        """
        schedule_id = self.create_schedule(
            channel_id=channel_id,
            name=f"24/7 schedule ({timezone})",
            cron_expression=None,
            timezone=timezone,
            is_active=True,
        )

        if not content_ids:
            return schedule_id

        today = datetime.now(tz=UTC).date()
        hours_per_content = 24.0 / len(content_ids)

        for i, content_id in enumerate(content_ids):
            start_hour = int(i * hours_per_content)
            end_hour = int((i + 1) * hours_per_content)
            if i == len(content_ids) - 1:
                end_hour = 23
                end_minute = 59
                end_second = 59
            else:
                end_minute = 0
                end_second = 0

            start_dt = datetime.combine(
                today,
                datetime.min.time().replace(hour=start_hour),
            ).replace(tzinfo=UTC)
            end_dt = datetime.combine(
                today,
                datetime.min.time().replace(
                    hour=end_hour, minute=end_minute, second=end_second
                ),
            ).replace(tzinfo=UTC)

            self.add_schedule_item(
                schedule_id=schedule_id,
                content_id=content_id,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
            )

        return schedule_id

    def get_schedule(self, schedule_id: str) -> ChannelSchedule | None:
        """Retrieve a schedule with its items."""
        conn = get_connection()
        row = conn.execute(
            """
            SELECT id, channel_id, name, cron_expression, timezone,
                   is_active, created_at, updated_at
            FROM schedules
            WHERE id = ? AND deleted_at IS NULL
            """,
            (schedule_id,),
        ).fetchone()

        if row is None:
            return None

        items = []
        item_rows = conn.execute(
            """
            SELECT id, schedule_id, content_id, start_time, end_time
            FROM schedule_items
            WHERE schedule_id = ? AND deleted_at IS NULL
            ORDER BY start_time
            """,
            (schedule_id,),
        ).fetchall()

        for item_row in item_rows:
            items.append(
                ScheduleItem(
                    id=item_row["id"],
                    schedule_id=item_row["schedule_id"],
                    content_id=item_row["content_id"],
                    start_time=item_row["start_time"],
                    end_time=item_row["end_time"],
                )
            )

        return ChannelSchedule(
            id=row["id"],
            channel_id=row["channel_id"],
            name=row["name"],
            cron_expression=row["cron_expression"],
            timezone=row["timezone"],
            is_active=bool(row["is_active"]),
            items=items,
        )

    def get_channel_schedules(self, channel_id: str) -> list[ChannelSchedule]:
        """Retrieve all active schedules for a channel."""
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT id, channel_id, name, cron_expression, timezone,
                   is_active, created_at, updated_at
            FROM schedules
            WHERE channel_id = ? AND deleted_at IS NULL
            ORDER BY created_at
            """,
            (channel_id,),
        ).fetchall()

        schedules: list[ChannelSchedule] = []
        for row in rows:
            schedule = self.get_schedule(row["id"])
            if schedule:
                schedules.append(schedule)

        return schedules

    def get_upcoming_items(
        self,
        channel_id: str,
        from_time: str | None = None,
        limit: int = 10,
    ) -> list[ScheduleItem]:
        """Get upcoming schedule items for a channel."""
        if from_time is None:
            from_time = datetime.now(tz=UTC).isoformat()

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT si.id, si.schedule_id, si.content_id, si.start_time, si.end_time
            FROM schedule_items si
            JOIN schedules s ON si.schedule_id = s.id
            WHERE s.channel_id = ?
              AND s.deleted_at IS NULL
              AND si.deleted_at IS NULL
              AND si.start_time >= ?
              AND s.is_active = 1
            ORDER BY si.start_time
            LIMIT ?
            """,
            (channel_id, from_time, limit),
        ).fetchall()

        return [
            ScheduleItem(
                id=row["id"],
                schedule_id=row["schedule_id"],
                content_id=row["content_id"],
                start_time=row["start_time"],
                end_time=row["end_time"],
            )
            for row in rows
        ]

    def deactivate_schedule(self, schedule_id: str) -> bool:
        """Deactivate a schedule (soft delete)."""
        conn = get_connection()
        row = conn.execute(
            "SELECT id FROM schedules WHERE id = ? AND deleted_at IS NULL",
            (schedule_id,),
        ).fetchone()

        if row is None:
            return False

        with transaction() as conn:
            conn.execute(
                "UPDATE schedules SET is_active = 0, updated_at = ? WHERE id = ?",
                (datetime.now(tz=UTC).isoformat(), schedule_id),
            )
            conn.execute(
                "UPDATE schedule_items SET deleted_at = ? WHERE schedule_id = ?",
                (datetime.now(tz=UTC).isoformat(), schedule_id),
            )

        logger.info(
            "Schedule deactivated",
            extra={"schedule_id": schedule_id},
        )
        return True


# Global instance
_scheduler: Scheduler | None = None


def get_scheduler(config: AppConfig | None = None) -> Scheduler:
    """Return the global scheduler (singleton)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler(config)
    return _scheduler
