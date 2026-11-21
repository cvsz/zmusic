"""YouTube integration tests for zMusic."""

import unittest
from unittest.mock import MagicMock, patch

from scripts.config import AppConfig, YouTubeConfig
from scripts.youtube import (
    YouTubeBroadcast,
    YouTubeClient,
    YouTubeIntegration,
    YouTubeProvider,
    YouTubeStream,
)


class YouTubeProviderTest(unittest.TestCase):
    def test_provider_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            provider = YouTubeProvider()
            provider.authenticate()


class YouTubeClientTest(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(
            youtube=YouTubeConfig(
                client_id="test-client-id",
                client_secret="test-client-secret",
            )
        )

    def test_client_creation(self):
        client = YouTubeClient(config=self.config)
        self.assertIsNotNone(client)
        self.assertEqual(client.config.youtube.client_id, "test-client-id")

    def test_missing_credentials(self):
        config = AppConfig(youtube=YouTubeConfig(client_id="", client_secret=""))
        client = YouTubeClient(config=config)
        with self.assertRaises(ValueError):
            client._oauth_credentials()

    def test_discover_channels(self):
        client = YouTubeClient(config=self.config)
        mock_response = {
            "items": [
                {
                    "id": "UC123456789",
                    "snippet": {
                        "title": "Test Channel",
                        "description": "A test channel",
                        "publishedAt": "2026-01-01T00:00:00Z",
                    },
                }
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            channels = client.discover_channels("fake-token")
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0].channel_id, "UC123456789")
            self.assertEqual(channels[0].title, "Test Channel")

    def test_create_broadcast(self):
        client = YouTubeClient(config=self.config)
        mock_response = {
            "id": "broadcast-123",
            "snippet": {"title": "Test Stream"},
            "status": {
                "lifeCycleStatus": "upcoming",
                "scheduledStartTime": "2026-01-01T06:00:00Z",
            },
            "contentDetails": {"boundStreamId": "stream-456"},
        }

        with patch.object(client, "_request", return_value=mock_response):
            broadcast = client.create_broadcast(
                access_token="fake-token",
                title="Test Stream",
                scheduled_start_time="2026-01-01T06:00:00Z",
            )
            self.assertEqual(broadcast.broadcast_id, "broadcast-123")
            self.assertEqual(broadcast.title, "Test Stream")
            self.assertEqual(broadcast.status, "upcoming")
            self.assertEqual(broadcast.stream_id, "stream-456")

    def test_create_stream(self):
        client = YouTubeClient(config=self.config)
        mock_response = {
            "id": "stream-456",
            "snippet": {"title": "Test Stream"},
            "cdn": {
                "ingestionInfo": {
                    "ingestionAddress": "rtmp://a.rtmp.youtube.com/live2",
                    "playbackUrl": "https://youtube.com/channel/UC123/live",
                }
            },
            "status": {"streamStatus": "active"},
        }

        with patch.object(client, "_request", return_value=mock_response):
            stream = client.create_stream(
                access_token="fake-token",
                title="Test Stream",
            )
            self.assertEqual(stream.stream_id, "stream-456")
            self.assertEqual(stream.status, "active")
            self.assertTrue(stream.ingest_address.startswith("rtmp://"))

    def test_bind_stream_to_broadcast(self):
        client = YouTubeClient(config=self.config)
        with patch.object(client, "_request", return_value={}) as mock_request:
            client.bind_stream_to_broadcast(
                access_token="fake-token",
                broadcast_id="broadcast-123",
                stream_id="stream-456",
            )
            # Verify the bind call was made with correct params
            call_args = mock_request.call_args
            self.assertEqual(call_args[0][0], "POST")
            self.assertEqual(call_args[0][1], "/liveBroadcasts/bind")
            params = call_args[1]["params"]
            self.assertEqual(params["id"], "broadcast-123")
            self.assertEqual(params["streamId"], "stream-456")

    def test_get_broadcast_status(self):
        client = YouTubeClient(config=self.config)
        mock_response = {
            "items": [
                {
                    "id": "broadcast-123",
                    "status": {"lifeCycleStatus": "active"},
                }
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            status = client.get_broadcast_status("fake-token", "broadcast-123")
            self.assertEqual(status, "active")

    def test_get_stream_status(self):
        client = YouTubeClient(config=self.config)
        mock_response = {
            "items": [
                {
                    "id": "stream-456",
                    "status": {"streamStatus": "active"},
                }
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            status = client.get_stream_status("fake-token", "stream-456")
            self.assertEqual(status, "active")


class YouTubeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(
            youtube=YouTubeConfig(
                client_id="test-client-id",
                client_secret="test-client-secret",
            )
        )

    def test_integration_singleton(self):
        integration1 = YouTubeIntegration()
        integration2 = YouTubeIntegration()
        self.assertIsNot(integration1, integration2)  # Different instances

    def test_create_live_stream_setup(self):
        provider = MagicMock(spec=YouTubeClient)
        provider.authenticate.return_value = "access-token-123"
        provider.create_broadcast.return_value = YouTubeBroadcast(
            broadcast_id="broadcast-123",
            title="Test Stream",
            status="upcoming",
            scheduled_start_time="2026-01-01T06:00:00Z",
            stream_id="stream-456",
        )
        provider.create_stream.return_value = YouTubeStream(
            stream_id="stream-456",
            ingest_address="rtmp://a.rtmp.youtube.com/live2/xyz",
            playback_url="https://youtube.com/channel/UC123/live",
            status="active",
        )

        integration = YouTubeIntegration(provider=provider)
        result = integration.create_live_stream_setup(
            title="Test Stream",
            scheduled_start_time="2026-01-01T06:00:00Z",
        )

        self.assertEqual(result["broadcast_id"], "broadcast-123")
        self.assertEqual(result["stream_id"], "stream-456")
        self.assertEqual(result["stream_status"], "active")
        self.assertTrue(result["ingest_address"].startswith("rtmp://"))
        self.assertTrue(result["playback_url"].startswith("https://"))

        # Verify bind was called
        provider.bind_stream_to_broadcast.assert_called_once_with(
            access_token="access-token-123",
            broadcast_id="broadcast-123",
            stream_id="stream-456",
        )

    def test_check_broadcast_health(self):
        provider = MagicMock(spec=YouTubeClient)
        provider.get_broadcast_status.return_value = "active"

        integration = YouTubeIntegration(provider=provider)
        result = integration.check_broadcast_health("broadcast-123")

        self.assertEqual(result["broadcast_id"], "broadcast-123")
        self.assertEqual(result["status"], "active")
        self.assertTrue(result["is_live"])
        self.assertFalse(result["is_completed"])

    def test_authenticate(self):
        provider = MagicMock(spec=YouTubeClient)
        provider.authenticate.return_value = "access-token-123"

        integration = YouTubeIntegration(provider=provider)
        token = integration.authenticate()
        self.assertEqual(token, "access-token-123")


if __name__ == "__main__":
    unittest.main()
