"""Agent implementations for zMusic.

Structured, deterministic agents with JSON Schema validation of outputs.
No agent directly controls infrastructure — all agent output passes through
validation before execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from .config import AppConfig
from .database import get_connection
from .logging import get_logger

logger = get_logger("zmusic.agents")


# ---------------------------------------------------------------------------
# Agent result contracts
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Standard output contract for all agents."""

    agent: str
    version: str
    status: str  # success, warning, failed, requires_approval
    plan: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    requires_approval: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "version": self.version,
            "status": self.status,
            "plan": self.plan,
            "warnings": self.warnings,
            "requires_approval": self.requires_approval,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Rights Validation Agent (mandatory)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RightsRecord:
    track_id: str
    youtube_allowed: bool
    commercial_allowed: bool
    license_valid_until: str | None
    attribution_required: bool
    ownership_verified: bool = False
    geographic_restrictions: list[str] | None = None


class RightsValidator:
    """Validates music track rights before content can enter production.

    A stream must not enter production if required rights validation fails.
    All checks are deterministic — no LLM involvement in rights decisions.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def validate_track(self, track_id: str) -> RightsRecord:
        """Validate rights for a single track.

        Queries the track_rights table. Returns a RightsRecord with all
        fields. If no rights record exists, all permissions default to False.
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT ownership_verified, license_valid_until,
                   commercial_allowed, youtube_allowed,
                   attribution_required, geographic_restrictions
            FROM track_rights
            WHERE track_id = ? AND deleted_at IS NULL
            """,
            (track_id,),
        ).fetchone()

        if row is None:
            logger.warning(
                "No rights record for track",
                extra={"track_id": track_id},
            )
            return RightsRecord(
                track_id=track_id,
                youtube_allowed=False,
                commercial_allowed=False,
                license_valid_until=None,
                attribution_required=False,
                ownership_verified=False,
                geographic_restrictions=[],
            )

        geo_raw = row["geographic_restrictions"]
        geo_list: list[str] = []
        if geo_raw:
            try:
                geo_list = json.loads(geo_raw)
            except (json.JSONDecodeError, TypeError):
                geo_list = [geo_raw] if geo_raw else []

        return RightsRecord(
            track_id=track_id,
            youtube_allowed=bool(row["youtube_allowed"]),
            commercial_allowed=bool(row["commercial_allowed"]),
            license_valid_until=row["license_valid_until"],
            attribution_required=bool(row["attribution_required"]),
            ownership_verified=bool(row["ownership_verified"]),
            geographic_restrictions=geo_list if geo_list else None,
        )

    def is_stream_safe(
        self, track_ids: list[str], require_commercial: bool = True
    ) -> tuple[bool, list[str]]:
        """Check if all tracks are cleared for streaming.

        Returns (is_safe, list of failure reasons).
        """
        failures: list[str] = []

        for track_id in track_ids:
            rights = self.validate_track(track_id)

            if not rights.youtube_allowed:
                failures.append(f"Track {track_id}: YouTube not allowed")

            if require_commercial and not rights.commercial_allowed:
                failures.append(f"Track {track_id}: Commercial use not allowed")

            if not rights.ownership_verified:
                failures.append(f"Track {track_id}: Ownership not verified")

            if rights.license_valid_until:
                try:
                    expiry = datetime.fromisoformat(rights.license_valid_until)
                    if expiry < datetime.now(tz=UTC):
                        failures.append(
                            f"Track {track_id}: License expired "
                            f"({rights.license_valid_until})"
                        )
                except (ValueError, TypeError):
                    failures.append(f"Track {track_id}: Invalid license expiry date")

            if rights.attribution_required:
                failures.append(f"Track {track_id}: Attribution required")

        is_safe = len(failures) == 0
        return is_safe, failures

    def validate_content_rights(self, content_id: str) -> dict[str, Any]:
        """Validate all tracks in a content item's playlist.

        Returns a dict with validation result and per-track details.
        """
        conn = get_connection()
        # Get playlist items for the content via compositions
        row = conn.execute(
            """
            SELECT c.id AS content_id, pi.track_id
            FROM content c
            LEFT JOIN compositions comp ON comp.content_id = c.id
            LEFT JOIN playlist_items pi ON pi.playlist_id = comp.audio_playlist_id
            WHERE c.id = ? AND c.deleted_at IS NULL
            """,
            (content_id,),
        ).fetchall()

        track_ids = [r["track_id"] for r in row if r["track_id"] is not None]

        if not track_ids:
            return {
                "content_id": content_id,
                "rights_valid": False,
                "failures": ["No tracks found for content"],
                "tracks": [],
            }

        is_safe, failures = self.is_stream_safe(track_ids)

        track_details = []
        for track_id in track_ids:
            rights = self.validate_track(track_id)
            track_details.append(
                {
                    "track_id": track_id,
                    "youtube_allowed": rights.youtube_allowed,
                    "commercial_allowed": rights.commercial_allowed,
                    "ownership_verified": rights.ownership_verified,
                    "license_valid_until": rights.license_valid_until,
                    "attribution_required": rights.attribution_required,
                }
            )

        return {
            "content_id": content_id,
            "rights_valid": is_safe,
            "failures": failures,
            "tracks": track_details,
        }


# ---------------------------------------------------------------------------
# Music Director Agent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MusicPlan:
    theme: str
    genre: str
    mood: str
    bpm_range: tuple[int, int]
    session_duration_hours: int
    energy_curve: list[float]
    track_ordering: str
    transition_strategy: str
    target_audience: str


class MusicDirector:
    """Determines musical programming for a stream session.

    Produces a structured JSON plan that downstream agents (Music Production,
    Rights Validator) consume. Never selects specific tracks — that's the
    Music Production Agent's job, which must respect rights validation.
    """

    VERSION = "1.0"

    # Genre-to-BPM mapping (deterministic ranges)
    GENRE_BPM: ClassVar[dict[str, tuple[int, int]]] = {
        "lofi": (60, 90),
        "ambient": (50, 80),
        "chill": (70, 100),
        "house": (120, 130),
        "techno": (125, 145),
        "drum_and_bass": (160, 180),
        "classical": (60, 120),
        "jazz": (80, 140),
        "hip_hop": (85, 110),
        "edm": (128, 140),
    }

    # Theme-to-energy curve (normalized 0-1 over session duration)
    ENERGY_CURVES: ClassVar[dict[str, list[float]]] = {
        "calm": [0.3, 0.35, 0.4, 0.4, 0.35, 0.3],
        "energetic": [0.5, 0.7, 0.9, 0.9, 0.7, 0.5],
        "focus": [0.4, 0.45, 0.5, 0.5, 0.45, 0.4],
        "night": [0.2, 0.3, 0.4, 0.5, 0.4, 0.3],
        "morning": [0.3, 0.5, 0.6, 0.6, 0.5, 0.4],
    }

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def create_plan(
        self,
        theme: str,
        genre: str,
        duration_hours: int,
        target_mood: str,
    ) -> AgentResult:
        """Create a music programming plan.

        Input:
            theme, genre, duration_hours, target_mood

        Output: structured AgentResult with MusicPlan in plan field.
        """
        warnings: list[str] = []

        # Validate genre
        if genre not in self.GENRE_BPM:
            warnings.append(f"Unknown genre '{genre}', using default BPM range")
            bpm_range = (80, 120)
        else:
            bpm_range = self.GENRE_BPM[genre]

        # Validate energy curve
        energy_key = target_mood.lower()
        if energy_key not in self.ENERGY_CURVES:
            warnings.append(f"Unknown mood '{target_mood}', using default energy curve")
            energy_curve = [0.5] * 6
        else:
            energy_curve = self.ENERGY_CURVES[energy_key]

        # Determine transition strategy based on genre
        transition_strategy = self._select_transition_strategy(genre)

        # Determine track ordering
        track_ordering = self._select_track_ordering(genre, target_mood)

        plan = MusicPlan(
            theme=theme,
            genre=genre,
            mood=target_mood,
            bpm_range=bpm_range,
            session_duration_hours=duration_hours,
            energy_curve=energy_curve,
            track_ordering=track_ordering,
            transition_strategy=transition_strategy,
            target_audience=self._infer_audience(genre, target_mood),
        )

        requires_approval = (
            duration_hours > 6
            or genre not in self.GENRE_BPM
            or target_mood.lower() not in self.ENERGY_CURVES
        )

        return AgentResult(
            agent="music_director",
            version=self.VERSION,
            status="success" if not warnings else "warning",
            plan={
                "theme": plan.theme,
                "genre": plan.genre,
                "mood": plan.mood,
                "bpm_range": list(plan.bpm_range),
                "session_duration_hours": plan.session_duration_hours,
                "energy_curve": plan.energy_curve,
                "track_ordering": plan.track_ordering,
                "transition_strategy": plan.transition_strategy,
                "target_audience": plan.target_audience,
            },
            warnings=warnings,
            requires_approval=requires_approval,
        )

    def _select_transition_strategy(self, genre: str) -> str:
        """Deterministic transition strategy per genre."""
        strategies = {
            "lofi": "crossfade",
            "ambient": "fade",
            "chill": "crossfade",
            "house": "beatmatch",
            "techno": "beatmatch",
            "drum_and_bass": "beatmatch",
            "classical": "fade",
            "jazz": "crossfade",
            "hip_hop": "cut",
            "edm": "beatmatch",
        }
        return strategies.get(genre, "crossfade")

    def _select_track_ordering(self, genre: str, mood: str) -> str:
        """Deterministic track ordering strategy."""
        if genre in {"classical", "ambient"}:
            return "by_mood_arc"
        if genre in {"house", "techno", "edm", "drum_and_bass"}:
            return "by_bpm_ascending"
        if mood in {"calm", "focus"}:
            return "by_energy_ascending"
        return "by_energy_curve"

    def _infer_audience(self, genre: str, mood: str) -> str:
        """Infer target audience from genre and mood."""
        audiences = {
            ("lofi", "calm"): "study / focus listeners",
            ("lofi", "night"): "late night listeners",
            ("house", "energetic"): "dance / club audience",
            ("ambient", "calm"): "meditation / relaxation",
            ("classical", "focus"): "concentrated work",
            ("jazz", "calm"): "sophisticated listeners",
        }
        return audiences.get((genre, mood), "general audience")


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------

_AGENTS: dict[str, Any] = {}


def register_agent(name: str, agent: Any) -> None:
    """Register an agent instance by name."""
    _AGENTS[name] = agent


def get_agent(name: str) -> Any:
    """Retrieve a registered agent by name."""
    return _AGENTS.get(name)


def initialize_agents(config: AppConfig | None = None) -> None:
    """Initialize and register all built-in agents."""
    register_agent("rights_validator", RightsValidator(config))
    register_agent("music_director", MusicDirector(config))
    logger.info(
        "Agents initialized",
        extra={"agents": sorted(_AGENTS.keys())},
    )
