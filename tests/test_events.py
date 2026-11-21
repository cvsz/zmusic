"""Event system tests for zMusic."""

import unittest

from scripts.events import (
    EVENT_AGENT_FAILED,
    EVENT_CONTENT_CREATED,
    EVENT_RIGHTS_VALIDATION_FAILED,
    EVENT_STREAM_STARTED,
    DomainEvent,
    deserialize_event,
    is_agent_event,
    is_content_event,
    is_rights_event,
    is_stream_event,
    make_event,
    serialize_event,
    strip_internal_fields,
    validate_required_fields,
)


class DomainEventTest(unittest.TestCase):
    def test_domain_event_creation(self):
        event = DomainEvent(
            event_id="evt-001",
            event_type="test.event",
            source="test_source",
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"key": "value"},
        )
        self.assertEqual(event.event_id, "evt-001")
        self.assertEqual(event.event_type, "test.event")
        self.assertEqual(event.source, "test_source")

    def test_make_event(self):
        event = make_event(EVENT_STREAM_STARTED, "scheduler", {"stream_id": "str-001"})
        self.assertIsNotNone(event.event_id)
        self.assertEqual(event.event_type, EVENT_STREAM_STARTED)
        self.assertEqual(event.source, "scheduler")
        self.assertIsInstance(event.timestamp, str)
        self.assertTrue(len(event.timestamp) > 0)
        self.assertEqual(event.payload, {"stream_id": "str-001"})
        self.assertEqual(event.version, "1.0")

    def test_serialize_deserialize_roundtrip(self):
        event = make_event(EVENT_CONTENT_CREATED, "metadata", {"content_id": "cnt-001"})
        serialized = serialize_event(event)
        deserialized = deserialize_event(serialized)

        self.assertEqual(deserialized.event_id, event.event_id)
        self.assertEqual(deserialized.event_type, event.event_type)
        self.assertEqual(deserialized.source, event.source)
        self.assertEqual(deserialized.payload, event.payload)
        self.assertEqual(deserialized.version, event.version)


class EventClassificationTest(unittest.TestCase):
    def test_is_stream_event(self):
        self.assertTrue(is_stream_event(EVENT_STREAM_STARTED))
        self.assertFalse(is_stream_event(EVENT_CONTENT_CREATED))

    def test_is_content_event(self):
        self.assertTrue(is_content_event(EVENT_CONTENT_CREATED))
        self.assertFalse(is_content_event(EVENT_STREAM_STARTED))

    def test_is_agent_event(self):
        self.assertTrue(is_agent_event(EVENT_AGENT_FAILED))
        self.assertFalse(is_agent_event(EVENT_STREAM_STARTED))

    def test_is_rights_event(self):
        self.assertTrue(is_rights_event(EVENT_RIGHTS_VALIDATION_FAILED))


class PayloadValidationTest(unittest.TestCase):
    def test_validate_required_fields_existing(self):
        self.assertTrue(validate_required_fields({"a": 1, "b": 2}, ["a", "b"]))

    def test_validate_required_fields_missing(self):
        self.assertFalse(validate_required_fields({"a": 1}, ["a", "b", "c"]))

    def test_strip_internal_fields(self):
        payload = {"event_id": "evt-001", "key": "value", "timestamp": "2026-01-01"}
        result = strip_internal_fields(payload)
        self.assertEqual(result, {"key": "value"})


if __name__ == "__main__":
    unittest.main()
