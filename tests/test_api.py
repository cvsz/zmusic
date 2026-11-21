"""API tests for zMusic."""

import unittest

from scripts.api import (
    APIResponse,
    api_gateway,
    api_response,
    list_endpoints,
    route_api_request,
)


def assertAnyIn(substring: str, container: tuple) -> None:
    """Assert that substring is contained in any element of the tuple."""
    found = any(substring in error for error in container)
    if not found:
        raise AssertionError(f"'{substring}' not found in any element of {container}")


class APIResponseTest(unittest.TestCase):
    def test_api_response_creation(self):
        response = api_response(True, data={"key": "value"})
        self.assertTrue(response.success)
        self.assertEqual(response.data, {"key": "value"})

        response_error = api_response(False, error="test error", error_code="ERR_TEST")
        self.assertFalse(response_error.success)
        self.assertEqual(response_error.error, "test error")
        self.assertEqual(response_error.error_code, "ERR_TEST")

    def test_api_response_defaults(self):
        response = api_response(True)
        self.assertTrue(response.success)
        self.assertIsNone(response.data)
        self.assertIsNone(response.error)
        self.assertIsNone(response.error_code)
        self.assertIsNotNone(response.request_id)


class ListEndpointsTest(unittest.TestCase):
    def test_list_endpoints_not_empty(self):
        endpoints = list_endpoints()
        self.assertGreater(len(endpoints), 0)
        # Verify we have endpoints for major resources
        endpoint_paths = [ep.path for ep in endpoints]
        self.assertIn("/api/v1/channels", endpoint_paths)


class GatewayTest(unittest.TestCase):
    def test_api_gateway_with_data_validation(self):
        # Test that api_gateway validates data
        data = {
            "name": "Test Channel",
            "programming": {"mode": "autonomous"},
            "music": {"genres": ["lofi"]},
            "visual": {"theme": "rainy_city"},
            "stream": {"resolution": "1080p", "fps": 30},
            "schedule": {"timezone": "Asia/Bangkok"},
        }
        response = api_gateway("POST", "/api/v1/channels", data)
        # Should either succeed or fail validation (not crash)
        self.assertIsInstance(response, APIResponse)

    def test_api_gateway_without_data(self):
        response = api_gateway("GET", "/api/v1/channels")
        self.assertIsInstance(response, APIResponse)


class RouteAPITest(unittest.TestCase):
    def test_route_start_stream(self):
        response = route_api_request(
            "POST",
            "/api/v1/streams/str-001/start",
            {"stream_id": "str-001", "config": {"resolution": "1080p"}},
        )
        self.assertIsInstance(response, APIResponse)

    def test_route_stop_stream(self):
        response = route_api_request("POST", "/api/v1/streams/str-001/stop")
        self.assertIsInstance(response, APIResponse)

    def test_route_invalid_endpoint(self):
        response = route_api_request("GET", "/api/v1/nonexistent")
        self.assertIsInstance(response, APIResponse)
        self.assertFalse(response.success)


if __name__ == "__main__":
    unittest.main()
