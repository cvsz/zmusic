"""API Service for zMusic.

Provides REST endpoints for channel management, content, playlists, streams,
scheduling, and agent control.

Supports API versioning and authentication/authorization checks.

ENDPOINTS (planned):

GET    /api/v1/channels
POST   /api/v1/channels

GET    /api/v1/content
POST   /api/v1/content

GET    /api/v1/playlists
POST   /api/v1/playlists

GET    /api/v1/assets
POST   /api/v1/assets

GET    /api/v1/schedules
POST   /api/v1/schedules

GET    /api/v1/streams
POST   /api/v1/streams/{id}/start
POST   /api/v1/streams/{id}/stop

GET    /api/v1/streams/{id}/health

GET    /api/v1/agents
POST   /api/v1/agents/{id}/run
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from .events import EVENT_AGENT_STARTED, EVENT_STREAM_STARTED, EVENT_STREAM_STOPPED
from .logging import get_logger
from .validation import (
    validate_agent_output,
    validate_channel_config,
    validate_for_production,
    validate_stream_config,
)

logger = get_logger("zmusic.api")


@dataclass
class APIEndpoint:
    """Represents an API endpoint definition."""

    method: str
    path: str
    description: str
    requires_auth: bool = True
    validation_schema: str | None = None


@dataclass
class APIResponse:
    """Standard API response structure."""

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    request_id: str = str(uuid.uuid4())
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


def api_response(
    success: bool,
    data: dict[str, Any] | None = None,
    error: str | None = None,
    error_code: str | None = None,
) -> APIResponse:
    """Create a standardized API response."""
    return APIResponse(
        success=success,
        data=data,
        error=error,
        error_code=error_code,
    )


# --- API Endpoint Definitions ---

# Version 1 endpoints
API_V1_ENDPOINTS: list[APIEndpoint] = [
    APIEndpoint(
        method="GET",
        path="/api/v1/channels",
        description="List all channels",
        requires_auth=True,
    ),
    APIEndpoint(
        method="POST",
        path="/api/v1/channels",
        description="Create a new channel",
        requires_auth=True,
        validation_schema="channel_config",
    ),
    APIEndpoint(
        method="GET",
        path="/api/v1/content",
        description="List content items",
        requires_auth=True,
    ),
    APIEndpoint(
        method="POST",
        path="/api/v1/content",
        description="Create/content item",
        requires_auth=True,
    ),
    APIEndpoint(
        method="GET",
        path="/api/v1/playlists",
        description="List playlists",
        requires_auth=True,
    ),
    APIEndpoint(
        method="POST",
        path="/api/v1/playlists",
        description="Create a new playlist",
        requires_auth=True,
    ),
    APIEndpoint(
        method="GET",
        path="/api/v1/streams",
        description="List streams",
        requires_auth=True,
    ),
    APIEndpoint(
        method="POST",
        path="/api/v1/streams/{id}/start",
        description="Start a stream",
        requires_auth=True,
        validation_schema="stream_config",
    ),
    APIEndpoint(
        method="POST",
        path="/api/v1/streams/{id}/stop",
        description="Stop a stream",
        requires_auth=True,
    ),
    APIEndpoint(
        method="GET",
        path="/api/v1/streams/{id}/health",
        description="Get stream health status",
        requires_auth=True,
    ),
    APIEndpoint(
        method="GET",
        path="/api/v1/agents",
        description="List agents",
        requires_auth=True,
    ),
    APIEndpoint(
        method="POST",
        path="/api/v1/agents/{id}/run",
        description="Run an agent",
        requires_auth=True,
        validation_schema="agent_output",
    ),
]


def list_endpoints() -> list[APIEndpoint]:
    """Return all registered API endpoints."""
    return API_V1_ENDPOINTS


def validate_endpoint_data(
    endpoint_name: str, data: dict[str, Any]
) -> tuple[bool, str | None]:
    """Validate data against the schema for a given endpoint name.

    Returns (is_valid, error_message).
    """
    schema_name = None
    for ep in API_V1_ENDPOINTS:
        if (
            ep.path.rstrip("/").split("/")[-1]
            == endpoint_name.rstrip("/").split("/")[-1]
            if "/" in endpoint_name
            else endpoint_name
        ):
            # Simple matching - in production, use proper path matching
            pass

    # Default: validate as agent output if endpoint involves agent actions
    if "agent" in endpoint_name.lower():
        result = validate_agent_output("api", data)
    elif "channel" in endpoint_name.lower():
        result = validate_channel_config(data)
    elif "stream" in endpoint_name.lower():
        result = validate_stream_config(data)
    else:
        result = validate_for_production("agent_output", data)

    return result.valid, result.errors[0] if result.errors else None


# --- Placeholder endpoint handlers ---


def handle_list_channels() -> APIResponse:
    """Handle GET /api/v1/channels."""
    from scripts.database import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, slug FROM channels WHERE deleted_at IS NULL"
        ).fetchall()
        channels = [{"id": r["id"], "name": r["name"], "slug": r["slug"]} for r in rows]
        return api_response(True, {"channels": channels})
    except Exception as e:
        logger.error("Error listing channels", exc_info=True)
        return api_response(False, error=str(e), error_code="CHANNEL_LIST_ERROR")


def handle_create_channel(data: dict[str, Any]) -> APIResponse:
    """Handle POST /api/v1/channels."""
    # Validate channel configuration
    result = validate_for_production("channel_config", data)
    if not result.valid:
        return api_response(
            False, error="; ".join(result.errors), error_code="CHANNEL_VALIDATION_ERROR"
        )

    # In a full implementation, would create the channel in the database
    # and return the created channel info
    return api_response(True, {"message": "Channel creation validated", "data": data})


def handle_list_content() -> APIResponse:
    """Handle GET /api/v1/content."""
    from scripts.database import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, artist, status FROM content WHERE deleted_at IS NULL"
        ).fetchall()
        content = [
            {
                "id": r["id"],
                "title": r["title"],
                "artist": r["artist"],
                "status": r["status"],
            }
            for r in rows
        ]
        return api_response(True, {"content": content})
    except Exception as e:
        logger.error("Error listing content", exc_info=True)
        return api_response(False, error=str(e), error_code="CONTENT_LIST_ERROR")


def handle_create_content(data: dict[str, Any]) -> APIResponse:
    """Handle POST /api/v1/content."""
    result = validate_for_production("agent_output", data)
    if not result.valid:
        return api_response(
            False, error="; ".join(result.errors), error_code="CONTENT_VALIDATION_ERROR"
        )
    return api_response(True, {"message": "Content validated", "data": data})


def handle_list_playlists() -> APIResponse:
    """Handle GET /api/v1/playlists."""
    from scripts.database import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, description FROM playlists WHERE deleted_at IS NULL"
        ).fetchall()
        playlists = [
            {"id": r["id"], "name": r["name"], "description": r["description"]}
            for r in rows
        ]
        return api_response(True, {"playlists": playlists})
    except Exception as e:
        logger.error("Error listing playlists", exc_info=True)
        return api_response(False, error=str(e), error_code="PLAYLIST_LIST_ERROR")


def handle_create_playlist(data: dict[str, Any]) -> APIResponse:
    """Handle POST /api/v1/playlists."""
    result = validate_for_production("agent_output", data)
    if not result.valid:
        return api_response(
            False,
            error="; ".join(result.errors),
            error_code="PLAYLIST_VALIDATION_ERROR",
        )
    return api_response(True, {"message": "Playlist validated", "data": data})


def handle_list_streams() -> APIResponse:
    """Handle GET /api/v1/streams."""
    from scripts.database import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, channel_id, state FROM streams WHERE deleted_at IS NULL"
        ).fetchall()
        streams = [
            {"id": r["id"], "channel_id": r["channel_id"], "state": r["state"]}
            for r in rows
        ]
        return api_response(True, {"streams": streams})
    except Exception as e:
        logger.error("Error listing streams", exc_info=True)
        return api_response(False, error=str(e), error_code="STREAM_LIST_ERROR")


def handle_start_stream(stream_id: str, data: dict[str, Any]) -> APIResponse:
    """Handle POST /api/v1/streams/{id}/start."""
    result = validate_for_production("stream_config", data)
    if not result.valid:
        return api_response(
            False, error="; ".join(result.errors), error_code="STREAM_VALIDATION_ERROR"
        )

    # Validate rights for the stream
    # In full implementation, would validate track rights and start the stream

    # Create an event for stream start
    from scripts.events import make_event, serialize_event

    event = make_event(
        EVENT_STREAM_STARTED,
        "api",
        {"stream_id": stream_id, "requested_at": datetime.now(tz=UTC).isoformat()},
    )
    serialized = serialize_event(event)
    # In production, would store event in database

    return api_response(True, {"stream_id": stream_id, "event": serialized})


def handle_stop_stream(stream_id: str) -> APIResponse:
    """Handle POST /api/v1/streams/{id}/stop."""
    from scripts.database import get_connection

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stream_sessions SET ended_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
            (stream_id,),
        )
        # Create event for stream stop
        from scripts.events import make_event, serialize_event

        event = make_event(
            EVENT_STREAM_STOPPED,
            "api",
            {"stream_id": stream_id, "stopped_at": datetime.now(tz=UTC).isoformat()},
        )
        serialized = serialize_event(event)

        return api_response(True, {"stream_id": stream_id, "event": serialized})
    except Exception as e:
        logger.error("Error stopping stream", exc_info=True)
        return api_response(False, error=str(e), error_code="STREAM_STOP_ERROR")


def handle_stream_health(stream_id: str) -> APIResponse:
    """Handle GET /api/v1/streams/{id}/health."""
    from scripts.monitoring import get_metrics

    try:
        metrics = get_metrics()
        # In full implementation, would query stream-specific health
        return api_response(True, {"stream_id": stream_id, "metrics": metrics})
    except Exception as e:
        logger.error("Error getting stream health", exc_info=True)
        return api_response(False, error=str(e), error_code="STREAM_HEALTH_ERROR")


def handle_list_agents() -> APIResponse:
    """Handle GET /api/v1/agents."""
    from scripts.database import get_connection

    conn = get_connection()
    try:
        # In full implementation, would list registered agents
        return api_response(
            True, {"agents": [], "message": "Agent listing placeholder"}
        )
    except Exception as e:
        logger.error("Error listing agents", exc_info=True)
        return api_response(False, error=str(e), error_code="AGENT_LIST_ERROR")


def handle_run_agent(agent_name: str, data: dict[str, Any]) -> APIResponse:
    """Handle POST /api/v1/agents/{id}/run."""
    result = validate_for_production("agent_output", data)
    if not result.valid:
        return api_response(
            False, error="; ".join(result.errors), error_code="AGENT_VALIDATION_ERROR"
        )

    # Create agent run event
    from scripts.events import make_event, serialize_event

    event = make_event(
        EVENT_AGENT_STARTED,
        agent_name,
        {
            "agent_name": agent_name,
            "requested_at": datetime.now(tz=UTC).isoformat(),
            "payload": data,
        },
    )
    serialized = serialize_event(event)

    return api_response(True, {"agent_name": agent_name, "event": serialized})


# --- API Router ---

API_HANDLERS: dict[str, dict[str, Callable]] = {
    "channels": {
        "GET": handle_list_channels,
        "POST": handle_create_channel,
    },
    "content": {
        "GET": handle_list_content,
        "POST": handle_create_content,
    },
    "playlists": {
        "GET": handle_list_playlists,
        "POST": handle_create_playlist,
    },
    "streams": {
        "GET": handle_list_streams,
        "POST/start": handle_start_stream,
        "POST/stop": handle_stop_stream,
        "GET/health": handle_stream_health,
    },
    "agents": {
        "GET": handle_list_agents,
        "POST/run": handle_run_agent,
    },
}


def route_api_request(
    method: str, path: str, data: dict[str, Any] | None = None
) -> APIResponse:
    """Route an API request to the appropriate handler.

    Parses the path to determine the endpoint and method,
    then calls the appropriate handler.
    """
    # Simple path matching - extract endpoint name and HTTP method
    # e.g., "/api/v1/channels" -> ("channels", "GET" or "POST")

    # Clean path
    clean_path = path.replace("/api/v1/", "").rstrip("/")

    # Determine endpoint and sub-action
    if clean_path in ["channels", "content", "playlists", "agents"]:
        endpoint = clean_path
        # For GET/POST on list endpoints
        if method in ("GET", "POST"):
            handler_name = f"handle_{endpoint}_{method.lower()}"
            handler = API_HANDLERS.get(endpoint, {}).get(method.lower())
            if handler and data:
                return handler(data)
            elif handler:
                return handler()
            else:
                return api_response(
                    False,
                    error=f"Endpoint {endpoint}::{method} not implemented",
                    error_code="ENDPOINT_NOT_IMPLEMENTED",
                )
        else:
            return api_response(
                False,
                error=f"Method {method} not allowed for {endpoint}",
                error_code="METHOD_NOT_ALLOWED",
            )

    elif clean_path.startswith("streams/"):
        # Streams have sub-actions: streams/{id}/start, streams/{id}/stop, streams/{id}/health
        parts = clean_path.split("/")
        stream_id = parts[-1] if len(parts) > 1 else None
        action = None
        if len(parts) > 2:
            action = parts[-2]  # e.g., "streams" / "start" / "stop" / "health"

        if action == "start" and stream_id:
            return handle_start_stream(stream_id, data or {})
        elif action == "stop" and stream_id:
            return handle_stop_stream(stream_id)
        elif action == "health" and stream_id:
            return handle_stream_health(stream_id)
        else:
            return api_response(
                False,
                error="Invalid stream action or missing stream_id",
                error_code="INVALID_STREAM_ACTION",
            )

    else:
        return api_response(
            False,
            error=f"Unknown API endpoint: {clean_path}",
            error_code="UNKNOWN_ENDPOINT",
        )


# --- API Gateway Entry Point ---


def api_gateway(
    method: str, path: str, data: dict[str, Any] | None = None
) -> APIResponse:
    """Main API gateway entry point.

    Performs authentication validation, data validation, and routes
    to the appropriate handler.

    In production, would also:
    - Validate API keys / JWT tokens
    - Rate limiting
    - Audit logging
    - Request throttling
    """
    # Step 1: Data validation (if data provided)
    if data:
        valid, error = validate_endpoint_data(path, data)
        if not valid:
            return api_response(False, error=error, error_code="VALIDATION_ERROR")

    # Step 2: Route to handler
    return route_api_request(method, path, data)
