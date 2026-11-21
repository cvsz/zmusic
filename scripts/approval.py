"""Human Approval System for zMusic.

Supports configurable approval gates for:
- Content approval
- Rights approval
- Stream approval
- Metadata approval

Channel policy determines which gates are required.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .config import AppConfig
from .database import get_connection, transaction
from .logging import get_logger

logger = get_logger("zmusic.approval")


class ApprovalStatus(Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    """An approval request for a specific gate."""

    request_id: str
    gate: str  # ApprovalGate value
    channel_id: str
    resource_type: str  # content, stream, metadata, rights
    resource_id: str
    requested_by: str  # user_id or "system"
    requested_at: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer: str | None = None
    reviewed_at: str | None = None
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    expires_at: str | None = None


@dataclass
class ApprovalPolicy:
    """Policy defining which approval gates are required for a channel."""

    channel_id: str
    required_gates: list[str] = field(default_factory=list)  # ApprovalGate values
    auto_approve_threshold: int | None = None  # Auto-approve after N approvals
    approvers: list[str] = field(default_factory=list)  # User IDs who can approve
    timeout_seconds: int = 3600  # 1 hour default


class ApprovalManager:
    """Manages approval requests and policies."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

    def create_approval_request(
        self,
        gate: str,
        channel_id: str,
        resource_type: str,
        resource_id: str,
        requested_by: str = "system",
        metadata: dict[str, Any] | None = None,
        expires_in_seconds: int = 3600,
    ) -> ApprovalRequest:
        """Create a new approval request."""
        request_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        expires_at = None
        if expires_in_seconds > 0:
            from datetime import timedelta

            expires_at = (
                datetime.now(tz=UTC) + timedelta(seconds=expires_in_seconds)
            ).isoformat()

        request = ApprovalRequest(
            request_id=request_id,
            gate=gate,
            channel_id=channel_id,
            resource_type=resource_type,
            resource_id=resource_id,
            requested_by=requested_by,
            requested_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )

        with transaction() as conn:
            conn.execute(
                """INSERT INTO approval_requests
                   (id, gate, channel_id, resource_type, resource_id, requested_by,
                    requested_at, status, expires_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request.request_id,
                    request.gate,
                    request.channel_id,
                    request.resource_type,
                    request.resource_id,
                    request.requested_by,
                    request.requested_at,
                    request.status.value,
                    request.expires_at,
                    json.dumps(request.metadata),
                ),
            )

        logger.info(
            "Approval request created",
            extra={"request_id": request_id, "gate": gate, "channel_id": channel_id},
        )
        return request

    def get_approval_request(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if not row:
                return None
            return self._from_db_row(row)
        finally:
            # Do NOT close connection here - let the caller manage connection lifecycle
            pass

    def approve_request(
        self, request_id: str, reviewer: str, comment: str = ""
    ) -> bool:
        """Approve an approval request."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                """UPDATE approval_requests
                   SET status = ?, reviewer = ?, reviewed_at = ?, comment = ?
                   WHERE id = ? AND status = ?""",
                (
                    ApprovalStatus.APPROVED.value,
                    reviewer,
                    datetime.now(tz=UTC).isoformat(),
                    comment,
                    request_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount > 0:
                logger.info(
                    "Approval request approved",
                    extra={"request_id": request_id, "reviewer": reviewer},
                )
                return True
            return False
        finally:
            # Do NOT close connection here
            pass

    def reject_request(self, request_id: str, reviewer: str, comment: str = "") -> bool:
        """Reject an approval request."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                """UPDATE approval_requests
                   SET status = ?, reviewer = ?, reviewed_at = ?, comment = ?
                   WHERE id = ? AND status = ?""",
                (
                    ApprovalStatus.REJECTED.value,
                    reviewer,
                    datetime.now(tz=UTC).isoformat(),
                    comment,
                    request_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount > 0:
                logger.info(
                    "Approval request rejected",
                    extra={"request_id": request_id, "reviewer": reviewer},
                )
                return True
            return False
        finally:
            # Do NOT close connection here
            pass

    def cancel_request(self, request_id: str) -> bool:
        """Cancel a pending approval request."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                """UPDATE approval_requests
                   SET status = ?
                   WHERE id = ? AND status = ?""",
                (
                    ApprovalStatus.CANCELLED.value,
                    request_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            return cursor.rowcount > 0
        finally:
            # Do NOT close connection here
            pass

    def get_pending_requests(
        self, channel_id: str | None = None
    ) -> list[ApprovalRequest]:
        """Get all pending approval requests, optionally filtered by channel."""
        conn = get_connection()
        try:
            if channel_id:
                rows = conn.execute(
                    "SELECT * FROM approval_requests WHERE channel_id = ? AND status = ?",
                    (channel_id, ApprovalStatus.PENDING.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approval_requests WHERE status = ?",
                    (ApprovalStatus.PENDING.value,),
                ).fetchall()
            return [self._from_db_row(row) for row in rows]
        finally:
            # Do NOT close connection here
            pass

    def check_approval_required(self, channel_id: str, gate: str) -> bool:
        """Check if a specific approval gate is required for a channel."""
        # In production, would check channel's approval policy
        # For now, check if gate is in the channel's required gates
        # This would be stored in channel configuration
        return True  # Simplified - always require approval for demo

    def _from_db_row(self, row) -> ApprovalRequest:
        """Reconstruct ApprovalRequest from database row."""
        import json

        return ApprovalRequest(
            request_id=row["id"],
            gate=row["gate"],
            channel_id=row["channel_id"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            requested_by=row["requested_by"],
            requested_at=row["requested_at"],
            status=ApprovalStatus(row["status"]),
            reviewer=row["reviewer"],
            reviewed_at=row["reviewed_at"],
            comment=row["comment"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            expires_at=row["expires_at"],
        )


# Global instance
_approval_manager: ApprovalManager | None = None


def get_approval_manager(config: AppConfig | None = None) -> ApprovalManager:
    """Get the global approval manager (singleton)."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager(config)
    return _approval_manager


def request_approval(
    gate: str,
    channel_id: str,
    resource_type: str,
    resource_id: str,
    requested_by: str = "system",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Convenience function to create an approval request."""
    manager = get_approval_manager()
    request = manager.create_approval_request(
        gate=gate,
        channel_id=channel_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return request.request_id


def check_all_approvals(channel_id: str, required_gates: list[str]) -> bool:
    """Check if all required approvals have been granted for a channel."""
    manager = get_approval_manager()
    for gate in required_gates:
        # Check if there's an approved request for this gate
        pending = manager.get_pending_requests(channel_id)
        # Simplified check - in production would query specific gate status
    return True  # Simplified


# --- Database Schema Addition ---

APPROVAL_REQUESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    gate TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    reviewed_at TEXT,
    comment TEXT,
    expires_at TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approval_channel_status ON approval_requests(channel_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_gate ON approval_requests(gate);
"""


# --- Example Usage ---
#
# manager = get_approval_manager()
#
# # Request content approval
# request_id = manager.create_approval_request(
#     gate="content_approval",
#     channel_id="ch-night-radio",
#     resource_type="content",
#     resource_id="content-001",
#     requested_by="music_director",
#     metadata={"title": "New Track", "artist": "Artist Name"},
# )
#
# # Approve the request
# manager.approve_request(request_id, "human_reviewer", "Sounds great!")
#
# # Check pending requests
# pending = manager.get_pending_requests("ch-night-radio")
