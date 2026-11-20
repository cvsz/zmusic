"""Scheduler tests for zMusic."""

import os
import tempfile
import unittest

from scripts.config import AppConfig, DatabaseConfig
from scripts.database import get_connection, init_db, transaction
from scripts.scheduler import Scheduler, get_scheduler, _scheduler


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            conn.execute(
                "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
                ("ch-1", "org-1", "Test Channel"),
            )
            conn.execute(
                "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
                ("ch-2", "org-1", "Test Channel 2"),
            )
            conn.execute(
                "INSERT INTO content (id, channel_id, title, state) VALUES (?, ?, ?, ?)",
                ("content-1", "ch-1", "Test Content 1", "ready"),
            )
            conn.execute(
                "INSERT INTO content (id, channel_id, title, state) VALUES (?, ?, ?, ?)",
                ("content-2", "ch-1", "Test Content 2", "ready"),
            )
            conn.execute(
                "INSERT INTO content (id, channel_id, title, state) VALUES (?, ?, ?, ?)",
                ("content-3", "ch-2", "Test Content 3", "ready"),
            )
            conn.commit()
        finally:
            pass

    def tearDown(self):
        conn = get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_create_schedule(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_schedule(
            channel_id="ch-1",
            name="Morning Schedule",
            cron_expression="0 6 * * *",
            timezone="Asia/Bangkok",
        )
        self.assertIsNotNone(schedule_id)

        schedule = scheduler.get_schedule(schedule_id)
        self.assertIsNotNone(schedule)
        self.assertEqual(schedule.channel_id, "ch-1")
        self.assertEqual(schedule.name, "Morning Schedule")
        self.assertEqual(schedule.cron_expression, "0 6 * * *")
        self.assertEqual(schedule.timezone, "Asia/Bangkok")
        self.assertTrue(schedule.is_active)
        self.assertEqual(len(schedule.items), 0)

    def test_get_nonexistent_schedule(self):
        scheduler = Scheduler()
        result = scheduler.get_schedule("nonexistent")
        self.assertIsNone(result)

    def test_add_schedule_item(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_schedule(
            channel_id="ch-1",
            name="Test Schedule",
        )

        item_id = scheduler.add_schedule_item(
            schedule_id=schedule_id,
            content_id="content-1",
            start_time="2026-01-01T06:00:00Z",
            end_time="2026-01-01T09:00:00Z",
        )
        self.assertIsNotNone(item_id)

        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(len(schedule.items), 1)
        self.assertEqual(schedule.items[0].content_id, "content-1")
        self.assertEqual(schedule.items[0].start_time, "2026-01-01T06:00:00Z")

    def test_create_one_time_stream(self):
        scheduler = Scheduler()
        schedule_id, item_id = scheduler.create_one_time_stream(
            channel_id="ch-1",
            content_id="content-1",
            start_time="2026-01-01T06:00:00Z",
            duration_hours=3.0,
        )
        self.assertIsNotNone(schedule_id)
        self.assertIsNotNone(item_id)

        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(len(schedule.items), 1)
        item = schedule.items[0]
        self.assertEqual(item.content_id, "content-1")
        self.assertEqual(item.start_time, "2026-01-01T06:00:00+00:00")
        # End time should be 3 hours later
        self.assertIn("09:00:00", item.end_time)

    def test_create_recurring_schedule(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_recurring_schedule(
            channel_id="ch-1",
            name="Daily Loop",
            cron_expression="0 0 * * *",
            timezone="UTC",
        )
        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(schedule.cron_expression, "0 0 * * *")
        self.assertTrue(schedule.is_active)

    def test_create_daily_programming(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_daily_programming(
            channel_id="ch-1",
            programs=[
                {
                    "name": "Morning Chill",
                    "start_time": "06:00",
                    "duration_hours": 3.0,
                    "content_id": "content-1",
                },
                {
                    "name": "Evening LoFi",
                    "start_time": "18:00",
                    "duration_hours": 4.0,
                    "content_id": "content-2",
                },
            ],
            timezone="Asia/Bangkok",
        )
        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(len(schedule.items), 2)
        self.assertEqual(schedule.timezone, "Asia/Bangkok")

    def test_create_weekly_programming(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_weekly_programming(
            channel_id="ch-1",
            programs=[
                {
                    "name": "Monday Morning",
                    "weekday": 0,
                    "start_time": "08:00",
                    "duration_hours": 2.0,
                    "content_id": "content-1",
                },
                {
                    "name": "Friday Night",
                    "weekday": 4,
                    "start_time": "20:00",
                    "duration_hours": 3.0,
                    "content_id": "content-2",
                },
            ],
            timezone="UTC",
        )
        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(len(schedule.items), 2)

    def test_create_24_7_schedule(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_24_7_schedule(
            channel_id="ch-1",
            content_ids=["content-1", "content-2"],
            timezone="UTC",
        )
        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(len(schedule.items), 2)
        # Each content should get 12 hours
        self.assertIn("content-1", [i.content_id for i in schedule.items])
        self.assertIn("content-2", [i.content_id for i in schedule.items])

    def test_create_24_7_empty_content(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_24_7_schedule(
            channel_id="ch-1",
            content_ids=[],
            timezone="UTC",
        )
        schedule = scheduler.get_schedule(schedule_id)
        self.assertEqual(len(schedule.items), 0)

    def test_get_channel_schedules(self):
        scheduler = Scheduler()
        scheduler.create_schedule(channel_id="ch-1", name="Schedule 1")
        scheduler.create_schedule(channel_id="ch-1", name="Schedule 2")
        scheduler.create_schedule(channel_id="ch-2", name="Other Channel Schedule")

        ch1_schedules = scheduler.get_channel_schedules("ch-1")
        self.assertEqual(len(ch1_schedules), 2)

        ch2_schedules = scheduler.get_channel_schedules("ch-2")
        self.assertEqual(len(ch2_schedules), 1)

    def test_get_upcoming_items(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_schedule(channel_id="ch-1", name="Test")

        scheduler.add_schedule_item(
            schedule_id=schedule_id,
            content_id="content-1",
            start_time="2026-01-01T06:00:00Z",
            end_time="2026-01-01T09:00:00Z",
        )
        scheduler.add_schedule_item(
            schedule_id=schedule_id,
            content_id="content-2",
            start_time="2026-01-01T10:00:00Z",
            end_time="2026-01-01T12:00:00Z",
        )

        items = scheduler.get_upcoming_items(
            channel_id="ch-1",
            from_time="2026-01-01T00:00:00Z",
            limit=5,
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].content_id, "content-1")
        self.assertEqual(items[1].content_id, "content-2")

    def test_deactivate_schedule(self):
        scheduler = Scheduler()
        schedule_id = scheduler.create_schedule(
            channel_id="ch-1", name="To Deactivate"
        )

        result = scheduler.deactivate_schedule(schedule_id)
        self.assertTrue(result)

        schedule = scheduler.get_schedule(schedule_id)
        self.assertFalse(schedule.is_active)
        self.assertEqual(len(schedule.items), 0)

    def test_deactivate_nonexistent(self):
        scheduler = Scheduler()
        result = scheduler.deactivate_schedule("nonexistent")
        self.assertFalse(result)


class GlobalSchedulerTest(unittest.TestCase):
    def test_get_scheduler_singleton(self):
        global _scheduler
        saved = _scheduler
        _scheduler = None
        try:
            s1 = get_scheduler()
            s2 = get_scheduler()
            self.assertIs(s1, s2)
        finally:
            _scheduler = saved


if __name__ == "__main__":
    unittest.main()
