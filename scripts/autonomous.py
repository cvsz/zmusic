"""Autonomous Mode Controller for zMusic.

Implements the AUTONOMOUS MODE where the system can:
1. inspect channel configuration
2. generate programming plan
3. select approved assets
4. validate rights
5. compose media
6. generate metadata
7. schedule stream
8. start stream
9. monitor stream
10. recover failures
11. collect analytics
12. produce report
13. improve next programming cycle

Human approval remains configurable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .agents import MusicDirector, RightsValidator, get_agent, register_agent
from .ai_safety import AIExecutionBridge, AIOutputValidator
from .analytics import get_analytics
from .channel import ChannelConfig, ChannelManager, ProgrammingMode, get_channel_manager
from .events import make_event
from .logging import get_logger
from .monitoring import get_monitor
from .scheduler import Scheduler, get_scheduler

logger = get_logger("zmusic.autonomous")


class AutonomousMode(Enum):
    """System operating modes."""

    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTONOMOUS = "autonomous"


class ApprovalGate(Enum):
    """Approval gates that can be required."""

    CONTENT_APPROVAL = "content_approval"
    RIGHTS_APPROVAL = "rights_approval"
    STREAM_APPROVAL = "stream_approval"
    METADATA_APPROVAL = "metadata_approval"


@dataclass
class AutonomousConfig:
    """Configuration for autonomous mode behavior."""

    mode: AutonomousMode = AutonomousMode.MANUAL
    required_approvals: list[ApprovalGate] = field(default_factory=list)
    auto_schedule: bool = False
    auto_start_stream: bool = False
    auto_recover: bool = True
    max_concurrent_streams: int = 1
    human_approval_timeout_seconds: int = 3600  # 1 hour default


@dataclass
class AutonomousCycleResult:
    """Result of an autonomous cycle execution."""

    cycle_id: str
    channel_id: str
    success: bool
    steps_completed: list[str]
    steps_failed: list[str]
    stream_id: str | None = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    completed_at: str | None = None


class AutonomousController:
    """Controls autonomous operation of channels."""

    def __init__(
        self,
        config: AutonomousConfig | None = None,
        channel_manager: ChannelManager | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        self.config = config or AutonomousConfig()
        self.channel_manager = channel_manager or get_channel_manager()
        self.scheduler = scheduler or get_scheduler()
        self.monitor = get_monitor()
        self.analytics = get_analytics()
        self.ai_validator = AIOutputValidator()
        self.ai_bridge = AIExecutionBridge(self.ai_validator)

        # Register agents if not already registered
        self._ensure_agents_registered()

    def _ensure_agents_registered(self) -> None:
        """Ensure required agents are registered."""
        agents_to_register = [
            ("music_director", MusicDirector()),
            ("rights_validator", RightsValidator()),
        ]
        for name, agent in agents_to_register:
            if not get_agent(name):
                register_agent(name, agent)

    def run_autonomous_cycle(self, channel_id: str) -> AutonomousCycleResult:
        """Execute a full autonomous cycle for a channel.

        Steps:
        1. Inspect channel configuration
        2. Generate programming plan
        3. Select approved assets
        4. Validate rights
        5. Compose media
        6. Generate metadata
        7. Schedule stream
        8. Start stream
        9. Monitor stream
        10. Recover failures
        11. Collect analytics
        12. Produce report
        13. Improve next programming cycle
        """
        cycle_id = str(uuid.uuid4())
        result = AutonomousCycleResult(
            cycle_id=cycle_id,
            channel_id=channel_id,
            success=False,
            steps_completed=[],
            steps_failed=[],
        )

        logger.info(
            "Starting autonomous cycle",
            extra={"cycle_id": cycle_id, "channel_id": channel_id},
        )

        try:
            # Step 1: Inspect channel configuration
            channel = self.channel_manager.get_channel(channel_id)
            if not channel:
                raise ValueError(f"Channel not found: {channel_id}")
            if channel.programming_mode != ProgrammingMode.AUTONOMOUS:
                raise ValueError(f"Channel {channel_id} is not in AUTONOMOUS mode")
            result.steps_completed.append("inspect_channel_config")

            # Step 2: Generate programming plan
            plan = self._generate_programming_plan(channel)
            result.steps_completed.append("generate_programming_plan")

            # Step 3: Select approved assets
            assets = self._select_approved_assets(channel, plan)
            result.steps_completed.append("select_approved_assets")

            # Step 4: Validate rights
            rights_valid = self._validate_rights(assets)
            if not rights_valid:
                raise ValueError("Rights validation failed for selected assets")
            result.steps_completed.append("validate_rights")

            # Step 5: Compose media
            composition = self._compose_media(channel, plan, assets)
            result.steps_completed.append("compose_media")

            # Step 6: Generate metadata
            metadata = self._generate_metadata(channel, plan, composition)
            result.steps_completed.append("generate_metadata")

            # Step 7: Schedule stream (if auto_schedule enabled)
            if self.config.auto_schedule:
                stream_id = self._schedule_stream(channel, composition, metadata)
                result.steps_completed.append("schedule_stream")
            else:
                stream_id = self._create_stream(channel, composition)
                result.steps_completed.append("create_stream")

            result.stream_id = stream_id

            # Step 8: Start stream (if auto_start_stream enabled)
            if self.config.auto_start_stream and stream_id:
                self._start_stream(stream_id)
                result.steps_completed.append("start_stream")

                # Step 9: Monitor stream
                self._monitor_stream(stream_id)
                result.steps_completed.append("monitor_stream")

                # Step 10: Recover failures (handled by monitor)
                result.steps_completed.append("recover_failures")

                # Step 11: Collect analytics
                self._collect_analytics(stream_id)
                result.steps_completed.append("collect_analytics")

                # Step 12: Produce report
                self._produce_report(stream_id)
                result.steps_completed.append("produce_report")

                # Step 13: Improve next programming cycle
                self._improve_next_cycle(channel, stream_id)
                result.steps_completed.append("improve_next_cycle")

            result.success = True
            result.completed_at = datetime.now(tz=UTC).isoformat()

            logger.info(
                "Autonomous cycle completed",
                extra={"cycle_id": result.cycle_id, "success": True},
            )

        except Exception as e:  # noqa: BLE001
            result.success = False
            result.error = str(e)
            result.completed_at = datetime.now(tz=UTC).isoformat()
            logger.error(
                "Autonomous cycle failed", extra={"cycle_id": cycle_id, "error": str(e)}
            )

        return result

    def _generate_programming_plan(self, channel: ChannelConfig) -> dict[str, Any]:
        """Generate programming plan using Music Director agent."""
        # Use AI safety bridge to validate AI output
        ai_input = {
            "theme": channel.visual.theme,
            "genres": channel.music.genres,
            "duration_hours": 6,  # Default
            "target_mood": channel.music.mood or "calm",
        }

        # Run Music Director agent
        agent = get_agent("music_director")
        if agent:
            ai_output = agent.run(ai_input)
            # Validate through AI safety bridge
            validated = self.ai_bridge.process_ai_decision("music_director", ai_output)
            if validated["success"]:
                return validated["execution_plan"]

        # Fallback: create basic plan
        return {
            "audio_playlist": f"playlist_{channel.channel_id}",
            "visual_scene": f"scene_{channel.visual.theme}",
            "duration_hours": 6,
        }

    def _select_approved_assets(
        self, channel: ChannelConfig, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Select approved music and visual assets for the plan."""
        # In production, would query asset database for approved assets
        # matching the plan's requirements
        return {
            "audio_assets": ["asset_audio_001", "asset_audio_002"],
            "visual_assets": ["asset_visual_001"],
            "overlay_assets": ["asset_overlay_001"],
        }

    def _validate_rights(self, assets: dict[str, Any]) -> bool:
        """Validate rights for all selected assets."""
        agent = get_agent("rights_validator")
        if not agent:
            return True  # Skip if no validator

        all_valid = True
        for asset_list in assets.values():
            for asset_id in asset_list:
                rights_input = {"track_id": asset_id}
                ai_output = agent.run(rights_input)
                validated = self.ai_bridge.process_ai_decision(
                    "rights_validator", ai_output
                )
                if not validated["success"]:
                    all_valid = False
                    break
        return all_valid

    def _compose_media(
        self, channel: ChannelConfig, plan: dict[str, Any], assets: dict[str, Any]
    ) -> dict[str, Any]:
        """Create media composition plan."""
        return {
            "audio_playlist": plan.get("audio_playlist", "default"),
            "visual_scene": plan.get("visual_scene", "default"),
            "overlay": "overlay_001",
            "now_playing": True,
            "transition": "crossfade",
            "assets": assets,
        }

    def _generate_metadata(
        self, channel: ChannelConfig, plan: dict[str, Any], composition: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate stream metadata (title, description, tags, etc.)."""
        return {
            "title": f"{channel.name} - {channel.visual.theme}",
            "description": f"Autonomous stream for {channel.name}",
            "tags": channel.music.genres + [channel.visual.theme],
            "category": "Music",
        }

    def _schedule_stream(
        self,
        channel: ChannelConfig,
        composition: dict[str, Any],
        metadata: dict[str, Any],
    ) -> str:
        """Schedule a stream using the scheduler."""
        # Create schedule item
        schedule_id = self.scheduler.create_schedule(
            channel_id=channel.channel_id,
            name=f"Autonomous: {channel.name}",
            timezone=channel.schedule.timezone,
        )
        # Add item - would use composition and metadata
        item_id = self.scheduler.add_schedule_item(
            schedule_id=schedule_id,
            content_id=composition.get("audio_playlist", "default"),
            start_time=datetime.now(tz=UTC).isoformat(),
            end_time=datetime.now(tz=UTC).isoformat(),
        )
        return item_id

    def _create_stream(
        self, channel: ChannelConfig, composition: dict[str, Any]
    ) -> str:
        """Create a stream record."""
        import uuid

        stream_id = str(uuid.uuid4())
        # In production, would create stream in database
        return stream_id

    def _start_stream(self, stream_id: str) -> None:
        """Start a stream."""
        # In production, would start FFmpeg process and RTMP stream
        event = make_event(
            "stream.started",
            "autonomous",
            {"stream_id": stream_id},
        )
        logger.info("Stream started", extra={"stream_id": stream_id, "event": event})

    def _monitor_stream(self, stream_id: str) -> None:
        """Monitor stream health."""
        self.monitor.start_monitoring(stream_id)

    def _collect_analytics(self, stream_id: str) -> None:
        """Collect stream analytics."""
        self.analytics.record_stream_session(
            stream_id, "channel_id", datetime.now(tz=UTC).isoformat()
        )

    def _produce_report(self, stream_id: str) -> None:
        """Produce post-stream report."""
        report = self.analytics.generate_post_stream_report(stream_id)
        logger.info("Report produced", extra={"stream_id": stream_id, "report": report})

    def _improve_next_cycle(self, channel: ChannelConfig, stream_id: str) -> None:
        """Analyze results and improve next programming cycle."""
        # In production, would use analytics to optimize future cycles
        logger.info(
            "Cycle improvement analysis",
            extra={"channel_id": channel.channel_id, "stream_id": stream_id},
        )


# Global instance
_autonomous_controller: AutonomousController | None = None


def get_autonomous_controller(
    config: AutonomousConfig | None = None,
) -> AutonomousController:
    """Get the global autonomous controller (singleton)."""
    global _autonomous_controller
    if _autonomous_controller is None:
        _autonomous_controller = AutonomousController(config)
    return _autonomous_controller


def set_autonomous_mode(channel_id: str, mode: AutonomousMode) -> None:
    """Set the autonomous mode for a channel."""
    manager = get_channel_manager()
    manager.update_channel(channel_id, {"programming_mode": mode.value})


def get_approval_status(channel_id: str) -> dict[str, Any]:
    """Get approval status for a channel."""
    manager = get_channel_manager()
    channel = manager.get_channel(channel_id)
    if not channel:
        return {"error": "Channel not found"}

    return {
        "channel_id": channel_id,
        "mode": channel.programming_mode.value,
        "required_approvals": [],  # Would check config
    }


# --- Example Usage ---
#
# controller = get_autonomous_controller(AutonomousConfig(
#     mode=AutonomousMode.AUTONOMOUS,
#     auto_schedule=True,
#     auto_start_stream=True,
#     auto_recover=True,
# ))
#
# result = controller.run_autonomous_cycle("ch-night-radio")
# print(result.success, result.steps_completed)
