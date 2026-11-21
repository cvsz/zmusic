"""Development Mode for zMusic.

Provides a complete local development environment with:
- One-command startup
- Database migrations
- Seed data
- Development configuration
- Hot reloading support
- Debug endpoints
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from .config import DatabaseConfig
from .database import init_db, transaction
from .logging import get_logger

logger = get_logger("zmusic.dev")


@dataclass
class DevConfig:
    """Development environment configuration."""

    auto_migrate: bool = True
    seed_data: bool = True
    hot_reload: bool = True
    debug_mode: bool = True
    log_level: str = "DEBUG"
    api_port: int = 8000
    worker_count: int = 2
    use_docker: bool = False


@dataclass
class SeedData:
    """Seed data for development."""

    organizations: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    content: list[dict[str, Any]] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)
    schedules: list[dict[str, Any]] = field(default_factory=list)


DEFAULT_SEED_DATA = SeedData(
    organizations=[
        {"id": "org-dev", "name": "Development Org", "slug": "dev"},
    ],
    channels=[
        {"id": "ch-dev-1", "organization_id": "org-dev", "name": "Dev Channel 1"},
        {"id": "ch-dev-2", "organization_id": "org-dev", "name": "Dev Channel 2"},
    ],
    content=[
        {
            "id": "content-dev-1",
            "channel_id": "ch-dev-1",
            "title": "Test Track 1",
            "description": "Test description",
            "state": "approved",
        },
        {
            "id": "content-dev-2",
            "channel_id": "ch-dev-2",
            "title": "Test Track 2",
            "description": "Test description",
            "state": "approved",
        },
    ],
    tracks=[
        {
            "id": "track-dev-1",
            "title": "Test Track 1",
            "artist": "Test Artist",
            "file_path": "/media/track1.mp3",
            "duration_seconds": 180,
        },
        {
            "id": "track-dev-2",
            "title": "Test Track 2",
            "artist": "Test Artist",
            "file_path": "/media/track2.mp3",
            "duration_seconds": 240,
        },
    ],
    schedules=[
        {
            "id": "sched-dev-1",
            "channel_id": "ch-dev-1",
            "name": "Dev Schedule",
            "timezone": "UTC",
        },
    ],
)


class DevEnvironment:
    """Manages the development environment."""

    def __init__(self, config: DevConfig | None = None) -> None:
        self.config = config or DevConfig()
        self._processes: list[subprocess.Popen] = []
        self._running = False

    def setup_database(self, config: DatabaseConfig | None = None) -> None:
        """Initialize database with migrations and seed data."""
        if config is None:
            config = DatabaseConfig(url="sqlite:///data/zmusic_dev.db")

        logger.info("Initializing development database")
        init_db(config)

        if self.config.seed_data:
            self._seed_database()

    def _seed_database(self) -> None:
        """Seed database with development data."""
        logger.info("Seeding development database")

        with transaction() as conn:
            # Seed organizations
            for org in DEFAULT_SEED_DATA.organizations:
                conn.execute(
                    """INSERT OR IGNORE INTO organizations (id, name, slug)
                       VALUES (?, ?, ?)""",
                    (org["id"], org["name"], org["slug"]),
                )

            # Seed channels
            for ch in DEFAULT_SEED_DATA.channels:
                conn.execute(
                    """INSERT OR IGNORE INTO channels (id, organization_id, name)
                       VALUES (?, ?, ?)""",
                    (ch["id"], ch["organization_id"], ch["name"]),
                )

            # Seed content
            for c in DEFAULT_SEED_DATA.content:
                conn.execute(
                    """INSERT OR IGNORE INTO content (id, channel_id, title, description, state)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        c["id"],
                        c.get("channel_id", "ch-dev-1"),
                        c["title"],
                        c.get("description", ""),
                        c["state"],
                    ),
                )

            # Seed tracks
            for t in DEFAULT_SEED_DATA.tracks:
                conn.execute(
                    """INSERT OR IGNORE INTO tracks (id, title, artist, file_path, duration_seconds)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        t["id"],
                        t["title"],
                        t["artist"],
                        t.get("file_path", ""),
                        t.get("duration_seconds", 0),
                    ),
                )

            # Seed schedules
            for s in DEFAULT_SEED_DATA.schedules:
                conn.execute(
                    """INSERT OR IGNORE INTO schedules (id, channel_id, name, timezone)
                       VALUES (?, ?, ?, ?)""",
                    (s["id"], s["channel_id"], s["name"], s["timezone"]),
                )

        logger.info("Database seeded successfully")

    def run_migrations(self) -> None:
        """Run database migrations (placeholder for migration system)."""
        logger.info("Running database migrations")
        # In production, would run alembic or similar

    def start_api_server(self, port: int | None = None) -> subprocess.Popen:
        """Start the API development server."""
        port = port or self.config.api_port
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "scripts.api:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--reload" if self.config.hot_reload else "",
            "--log-level",
            self.config.log_level.lower(),
        ]
        cmd = [c for c in cmd if c]

        logger.info(f"Starting API server on port {port}")
        proc = subprocess.Popen(cmd)
        self._processes.append(proc)
        return proc

    def start_workers(self, count: int | None = None) -> list[subprocess.Popen]:
        """Start background workers."""
        count = count or self.config.worker_count
        procs = []

        for i in range(count):
            cmd = [
                sys.executable,
                "-m",
                "scripts.worker_main",
                "--worker-id",
                f"dev-worker-{i}",
            ]

            logger.info(f"Starting worker {i}")
            proc = subprocess.Popen(cmd)
            self._processes.append(proc)
            procs.append(proc)

        return procs

    def start_scheduler(self) -> subprocess.Popen:
        """Start the scheduler service."""
        cmd = [
            sys.executable,
            "-m",
            "scripts.scheduler_main",
            "--dev-mode",
        ]

        logger.info("Starting scheduler")
        proc = subprocess.Popen(cmd)
        self._processes.append(proc)
        return proc

    def start_media_worker(self) -> subprocess.Popen:
        """Start the media worker."""
        cmd = [
            sys.executable,
            "-m",
            "scripts.media_worker",
            "--dev-mode",
        ]

        logger.info("Starting media worker")
        proc = subprocess.Popen(cmd)
        self._processes.append(proc)
        return proc

    def start_stream_worker(self) -> subprocess.Popen:
        """Start the stream worker."""
        cmd = [
            sys.executable,
            "-m",
            "scripts.stream_worker",
            "--dev-mode",
        ]

        logger.info("Starting stream worker")
        proc = subprocess.Popen(cmd)
        self._processes.append(proc)
        return proc

    def start_all(self) -> None:
        """Start all development services."""
        if self._running:
            logger.warning("Development environment already running")
            return

        self._running = True
        logger.info("Starting development environment")

        # Setup database
        self.setup_database()

        # Run migrations
        if self.config.auto_migrate:
            self.run_migrations()

        # Start services
        self.start_scheduler()
        self.start_workers()
        self.start_media_worker()
        self.start_stream_worker()
        self.start_api_server()

        logger.info("Development environment started")

    def stop_all(self) -> None:
        """Stop all development services."""
        if not self._running:
            return

        logger.info("Stopping development environment")
        self._running = False

        for proc in self._processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception as e:
                logger.error(f"Error stopping process: {e}")

        self._processes.clear()
        logger.info("Development environment stopped")

    def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown signal received")
            self.stop_all()

    def run_tests(self, test_path: str = "tests", verbose: bool = True) -> int:
        """Run the test suite."""
        cmd = [sys.executable, "-m", "pytest", test_path]
        if verbose:
            cmd.append("-v")

        logger.info("Running tests")
        result = subprocess.run(cmd)
        return result.returncode

    def run_lint(self) -> int:
        """Run linting checks."""
        cmd = [sys.executable, "-m", "ruff", "check", "scripts/", "tests/"]
        logger.info("Running lint")
        result = subprocess.run(cmd)
        return result.returncode

    def run_format(self) -> int:
        """Run code formatting."""
        cmd = [sys.executable, "-m", "black", "scripts/", "tests/"]
        logger.info("Running format")
        result = subprocess.run(cmd)
        return result.returncode

    def run_type_check(self) -> int:
        """Run type checking."""
        cmd = [sys.executable, "-m", "mypy", "scripts/"]
        logger.info("Running type check")
        result = subprocess.run(cmd)
        return result.returncode


def create_dev_config() -> DevConfig:
    """Create development configuration from environment."""
    return DevConfig(
        auto_migrate=os.environ.get("ZMUSIC_DEV_AUTO_MIGRATE", "true").lower()
        == "true",
        seed_data=os.environ.get("ZMUSIC_DEV_SEED_DATA", "true").lower() == "true",
        hot_reload=os.environ.get("ZMUSIC_DEV_HOT_RELOAD", "true").lower() == "true",
        debug_mode=os.environ.get("ZMUSIC_DEV_DEBUG", "true").lower() == "true",
        log_level=os.environ.get("ZMUSIC_LOG_LEVEL", "DEBUG"),
        api_port=int(os.environ.get("ZMUSIC_DEV_API_PORT", "8000")),
        worker_count=int(os.environ.get("ZMUSIC_DEV_WORKER_COUNT", "2")),
        use_docker=os.environ.get("ZMUSIC_DEV_USE_DOCKER", "false").lower() == "true",
    )


def main() -> None:
    """Main entry point for development mode."""
    import argparse

    parser = argparse.ArgumentParser(description="zMusic Development Environment")
    parser.add_argument(
        "command",
        choices=[
            "start",
            "stop",
            "restart",
            "test",
            "lint",
            "format",
            "type-check",
            "migrate",
            "seed",
        ],
        help="Command to execute",
    )
    parser.add_argument("--api-port", type=int, default=8000, help="API server port")
    parser.add_argument("--workers", type=int, default=2, help="Number of workers")
    parser.add_argument("--no-seed", action="store_true", help="Skip database seeding")
    parser.add_argument("--no-migrate", action="store_true", help="Skip migrations")

    args = parser.parse_args()

    config = create_dev_config()
    config.api_port = args.api_port
    config.worker_count = args.workers
    config.seed_data = not args.no_seed
    config.auto_migrate = not args.no_migrate

    env = DevEnvironment(config)

    if args.command == "start":
        env.start_all()
        env.wait_for_shutdown()
    elif args.command == "stop":
        env.stop_all()
    elif args.command == "restart":
        env.stop_all()
        time.sleep(1)
        env.start_all()
        env.wait_for_shutdown()
    elif args.command == "test":
        sys.exit(env.run_tests())
    elif args.command == "lint":
        sys.exit(env.run_lint())
    elif args.command == "format":
        sys.exit(env.run_format())
    elif args.command == "type-check":
        sys.exit(env.run_type_check())
    elif args.command == "migrate":
        env.run_migrations()
    elif args.command == "seed":
        env.setup_database()
        env._seed_database()


# --- Example Usage ---
#
# # Run development environment
# python -m scripts.dev start
#
# # Run tests
# python -m scripts.dev test
#
# # Run linting
# python -m scripts.dev lint
#
# # Format code
# python -m scripts.dev format
