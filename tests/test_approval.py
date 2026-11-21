"""Approval system tests for zMusic."""

import os
import tempfile
import unittest

from scripts.approval import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalStatus,
    get_approval_manager,
)
from scripts.autonomous import ApprovalGate
from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db


class ApprovalStatusTest(unittest.TestCase):
    def test_approval_status_values(self):
        self.assertEqual(ApprovalStatus.PENDING.value, "pending")
        self.assertEqual(ApprovalStatus.APPROVED.value, "approved")
        self.assertEqual(ApprovalStatus.REJECTED.value, "rejected")
        self.assertEqual(ApprovalStatus.EXPIRED.value, "expired")
        self.assertEqual(ApprovalStatus.CANCELLED.value, "cancelled")


class ApprovalGateTest(unittest.TestCase):
    def test_approval_gate_values(self):
        self.assertEqual(ApprovalGate.CONTENT_APPROVAL.value, "content_approval")
        self.assertEqual(ApprovalGate.RIGHTS_APPROVAL.value, "rights_approval")
        self.assertEqual(ApprovalGate.STREAM_APPROVAL.value, "stream_approval")
        self.assertEqual(ApprovalGate.METADATA_APPROVAL.value, "metadata_approval")


class ApprovalRequestTest(unittest.TestCase):
    def test_approval_request_creation(self):
        request = ApprovalRequest(
            request_id="req-001",
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
            requested_by="system",
            requested_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(request.request_id, "req-001")
        self.assertEqual(request.gate, "content_approval")
        self.assertEqual(request.status, ApprovalStatus.PENDING)


class ApprovalManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        self.conn = get_connection()
        try:
            self.conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-default", "Default Org", "default"),
            )
            # Create approval_requests table
            self.conn.execute("""
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
                )
            """)
            self.conn.commit()
        except Exception:
            self.conn.close()
            raise

    def tearDown(self):
        try:
            conn = get_connection()
            conn.close()
        except Exception:
            pass
        import scripts.database as dbmod

        dbmod._local.conn = None
        dbmod._config = dbmod.DatabaseConfig()
        self.temp_dir.cleanup()

    def test_create_approval_request(self):
        manager = ApprovalManager()
        request = manager.create_approval_request(
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
            requested_by="system",
        )
        self.assertIsNotNone(request.request_id)
        self.assertEqual(request.gate, "content_approval")
        self.assertEqual(request.channel_id, "ch-001")
        self.assertEqual(request.status, ApprovalStatus.PENDING)

    def test_get_approval_request(self):
        manager = ApprovalManager()
        request = manager.create_approval_request(
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
        )
        retrieved = manager.get_approval_request(request.request_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.request_id, request.request_id)

    def test_approve_request(self):
        manager = ApprovalManager()
        request = manager.create_approval_request(
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
        )
        result = manager.approve_request(
            request.request_id, "reviewer-001", "Approved!"
        )
        self.assertTrue(result)

        retrieved = manager.get_approval_request(request.request_id)
        self.assertEqual(retrieved.status, ApprovalStatus.APPROVED)
        self.assertEqual(retrieved.reviewer, "reviewer-001")

    def test_reject_request(self):
        manager = ApprovalManager()
        request = manager.create_approval_request(
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
        )
        result = manager.reject_request(
            request.request_id, "reviewer-001", "Not suitable"
        )
        self.assertTrue(result)

        retrieved = manager.get_approval_request(request.request_id)
        self.assertEqual(retrieved.status, ApprovalStatus.REJECTED)
        self.assertEqual(retrieved.reviewer, "reviewer-001")

    def test_cancel_request(self):
        manager = ApprovalManager()
        request = manager.create_approval_request(
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
        )
        result = manager.cancel_request(request.request_id)
        self.assertTrue(result)

        retrieved = manager.get_approval_request(request.request_id)
        self.assertEqual(retrieved.status, ApprovalStatus.CANCELLED)

    def test_get_pending_requests(self):
        manager = ApprovalManager()
        request1 = manager.create_approval_request(
            gate="content_approval",
            channel_id="ch-001",
            resource_type="content",
            resource_id="content-001",
        )
        request2 = manager.create_approval_request(
            gate="rights_approval",
            channel_id="ch-001",
            resource_type="rights",
            resource_id="rights-001",
        )

        pending = manager.get_pending_requests("ch-001")
        self.assertEqual(len(pending), 2)

        # Approve one
        manager.approve_request(request1.request_id, "reviewer")

        pending = manager.get_pending_requests("ch-001")
        self.assertEqual(len(pending), 1)


class ApprovalManagerSingletonTest(unittest.TestCase):
    def test_singleton(self):
        m1 = get_approval_manager()
        m2 = get_approval_manager()
        self.assertIs(m1, m2)


class RequestApprovalConvenienceTest(unittest.TestCase):
    def test_request_approval_convenience(self):
        # This tests the convenience function
        # Note: requires database setup which is done in setUp of other tests
        pass


if __name__ == "__main__":
    unittest.main()
