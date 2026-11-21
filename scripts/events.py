"""Event system for zMusic.

Publishes and tracks domain events throughout the streaming pipeline.

Events are idempotent and logged for audit, recovery, and analytics.

Example events:
  - content.created
  - content.validated
  - content.approved
  - stream.created
  - stream.started
  - stream.degraded
  - stream.recovered
  - stream.failed
  - stream.stopped
  - track.started
  - track.completed
  - agent.started
  - agent.completed
  - agent.failed
  - rights.validation.failed
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Event types
CLASS_CONTENT = "content"
CLASS_STREAM = "stream"
CLASS_AGENT = "agent"
CLASS_RIGHTS = "rights"

EVENT_CONTENT_CREATED = "content.created"
EVENT_CONTENT_VALIDATED = "content.validated"
EVENT_CONTENT_APPROVED = "content.approved"
EVENT_STREAM_CREATED = "stream.created"
EVENT_STREAM_STARTED = "stream.started"
EVENT_STREAM_DEGRADED = "stream.degraded"
EVENT_STREAM_RECOVERED = "stream.recovered"
EVENT_STREAM_FAILED = "stream.failed"
EVENT_STREAM_STOPPED = "stream.stopped"
EVENT_TRACK_STARTED = "track.started"
EVENT_TRACK_COMPLETED = "track.completed"
EVENT_AGENT_STARTED = "agent.started"
EVENT_AGENT_COMPLETED = "agent.completed"
EVENT_AGENT_FAILED = "agent.failed"
EVENT_RIGHTS_VALIDATION_FAILED = "rights.validation.failed"


@dataclass(frozen=True)
class DomainEvent:
    """Base domain event structure."""

    event_id: str
    event_type: str
    source: str  # e.g., "music_director", "rights_validator", "scheduler"
    timestamp: str
    payload: dict[str, Any]
    version: str = "1.0"


def make_event(
    event_type: str,
    source: str,
    payload: dict[str, Any],
    version: str = "1.0",
) -> DomainEvent:
    """Create a new domain event with a UUID event_id and ISO timestamp."""
    return DomainEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        source=source,
        timestamp=datetime.now(tz=UTC).isoformat(),
        payload=payload,
        version=version,
    )


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    """Serialize a domain event to a dictionary for storage/transmission."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "source": event.source,
        "timestamp": event.timestamp,
        "payload": event.payload,
        "version": event.version,
    }


def deserialize_event(data: dict[str, Any]) -> DomainEvent:
    """Deserialize a domain event from a dictionary."""
    return DomainEvent(
        event_id=data["event_id"],
        event_type=data["event_type"],
        source=data["source"],
        timestamp=data["timestamp"],
        payload=data["payload"],
        version=data.get("version", "1.0"),
    )


# Event storage (database-backed in production)
# In production, events are stored in the stream_events table

# Event filtering/categorization
STREAM_EVENTS = {
    EVENT_STREAM_CREATED,
    EVENT_STREAM_STARTED,
    EVENT_STREAM_DEGRADED,
    EVENT_STREAM_RECOVERED,
    EVENT_STREAM_FAILED,
    EVENT_STREAM_STOPPED,
}

CONTENT_EVENTS = {
    EVENT_CONTENT_CREATED,
    EVENT_CONTENT_VALIDATED,
    EVENT_CONTENT_APPROVED,
}

AGENT_EVENTS = {
    EVENT_AGENT_STARTED,
    EVENT_AGENT_COMPLETED,
    EVENT_AGENT_FAILED,
}

RIGHTS_EVENTS = {
    EVENT_RIGHTS_VALIDATION_FAILED,
}


def is_stream_event(event_type: str) -> bool:
    """Check if an event type is a stream-related event."""
    return event_type in STREAM_EVENTS


def is_content_event(event_type: str) -> bool:
    """Check if an event type is a content-related event."""
    return event_type in CONTENT_EVENTS


def is_agent_event(event_type: str) -> bool:
    """Check if an event type is an agent-related event."""
    return event_type in AGENT_EVENTS


def is_rights_event(event_type: str) -> bool:
    """Check if an event type is a rights-related event."""
    return event_type in RIGHTS_EVENTS


# Payload validation helpers


def validate_required_fields(payload: dict[str, Any], required: list[str]) -> bool:
    """Check that payload contains all required fields."""
    return all(field in payload for field in required)


def strip_internal_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove internal/system fields from payload before storage."""
    result = dict(payload)
    internal_keys = {"event_id", "timestamp", "version"}
    for key in internal_keys:
        result.pop(key, None)
    return result


# Example payload schemas per event type

CONTENT_EVENT_SCHEMAS = {
    EVENT_CONTENT_CREATED: ["content_id", "title", "artist", "source_url"],
    EVENT_CONTENT_VALIDATED: ["content_id", "rights_valid", "validation_errors"],
    EVENT_CONTENT_APPROVED: ["content_id", "approved_by", "approval_timestamp"],
}

STREAM_EVENT_SCHEMAS = {
    EVENT_STREAM_CREATED: ["stream_id", "channel_id", "title", "config"],
    EVENT_STREAM_STARTED: ["stream_id", "started_at", "encoder_status"],
    EVENT_STREAM_DEGRADED: ["stream_id", "reason", "metadata"],
    EVENT_STREAM_RECOVERED: ["stream_id", "recovery_time", "duration_to_recover"],
    EVENT_STREAM_FAILED: ["stream_id", "failure_time", "error_type"],
    EVENT_STREAM_STOPPED: ["stream_id", "stopped_at", "final_viewer_count"],
}

AGENT_EVENT_SCHEMAS = {
    EVENT_AGENT_STARTED: ["agent_name", "plan_id", "scheduled_at"],
    EVENT_AGENT_COMPLETED: ["agent_name", "plan_id", "result", "duration_seconds"],
    EVENT_AGENT_FAILED: ["agent_name", "plan_id", "error_type", "retry_count"],
}

RIGHTS_EVENT_SCHEMAS = {
    EVENT_RIGHTS_VALIDATION_FAILED: ["track_id", "failure_reason", "rights_record_id"],
}


# Example usage:
#
# event = make_event(
#     EVENT_STREAM_STARTED,
#     "scheduler",
#     {"stream_id": "str-001", "channel_id": "ch-001"},
# )
# serialized = serialize_event(event)
# deserialize_event(serialized)  # round-trip
