"""AI Safety tests for zMusic."""

import unittest

from scripts.ai_safety import (
    DEFAULT_POLICY,
    FORBIDDEN_OPERATIONS,
    AIExecutionBridge,
    AIOperation,
    AIOutputValidator,
    AISafetyPolicy,
)


class AIPolicyTest(unittest.TestCase):
    def test_default_policy_exists(self):
        self.assertIsNotNone(DEFAULT_POLICY)
        self.assertEqual(DEFAULT_POLICY.policy, AISafetyPolicy.STRICT)

    def test_forbidden_operations_not_empty(self):
        self.assertGreater(len(FORBIDDEN_OPERATIONS), 0)
        self.assertIn("execute_shell", FORBIDDEN_OPERATIONS)
        self.assertIn("execute_ffmpeg", FORBIDDEN_OPERATIONS)
        self.assertIn("start_stream", FORBIDDEN_OPERATIONS)

    def test_ai_operations_enum(self):
        self.assertEqual(AIOperation.PLAN.value, "plan")
        self.assertEqual(AIOperation.CLASSIFY.value, "classify")
        self.assertEqual(AIOperation.GENERATE.value, "generate")
        self.assertEqual(AIOperation.RECOMMEND.value, "recommend")
        self.assertEqual(AIOperation.ANALYZE.value, "analyze")


class AIOutputValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = AIOutputValidator()

    def test_valid_ai_output_passes(self):
        output = {
            "agent": "music_director",
            "version": "1.0",
            "status": "success",
            "plan": {
                "audio_playlist": "playlist_001",
                "visual_scene": "scene_004",
            },
            "requires_approval": False,
        }
        result = self.validator.validate("music_director", output)
        self.assertTrue(result.valid)

    def test_invalid_structure_rejected(self):
        output = "not a dictionary"
        result = self.validator.validate("test", output)
        self.assertFalse(result.valid)

    def test_missing_required_fields_rejected(self):
        output = {
            "agent": "music_director",
            # missing version, status, plan
        }
        result = self.validator.validate("music_director", output)
        self.assertFalse(result.valid)

    def test_forbidden_operation_in_output_rejected(self):
        output = {
            "agent": "test",
            "version": "1.0",
            "status": "success",
            "plan": {
                "action": "execute_shell",  # forbidden!
            },
            "requires_approval": False,
        }
        result = self.validator.validate("test", output)
        self.assertFalse(result.valid)
        self.assertIn("forbidden", str(result.errors).lower())

    def test_forbidden_in_nested_structure_rejected(self):
        output = {
            "agent": "test",
            "version": "1.0",
            "status": "success",
            "plan": {
                "operations": ["safe_op", "execute_ffmpeg"],  # forbidden!
            },
            "requires_approval": False,
        }
        result = self.validator.validate("test", output)
        self.assertFalse(result.valid)

    def test_approval_required_triggers_check(self):
        output = {
            "agent": "test",
            "version": "1.0",
            "status": "success",
            "plan": {
                "action": "delete_content",  # requires approval but not forbidden
            },
            "requires_approval": True,
            "action": "delete_content",
        }
        result = self.validator.validate("test", output)
        self.assertFalse(result.valid)
        self.assertIn("approval", str(result.errors).lower())


class AIExecutionBridgeTest(unittest.TestCase):
    def setUp(self):
        self.bridge = AIExecutionBridge()

    def test_bridge_processes_valid_decision(self):
        ai_output = {
            "agent": "music_director",
            "version": "1.0",
            "status": "success",
            "plan": {
                "audio_playlist": "playlist_001",
            },
            "requires_approval": False,
        }
        result = self.bridge.process_ai_decision("music_director", ai_output)
        self.assertTrue(result["success"])
        self.assertIn("execution_plan", result)

    def test_bridge_rejects_invalid_decision(self):
        ai_output = {
            "agent": "test",
            "version": "1.0",
            "status": "success",
            "plan": {
                "action": "execute_shell",
            },
            "requires_approval": False,
        }
        result = self.bridge.process_ai_decision("test", ai_output)
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "validation_failed")

    def test_bridge_builds_execution_plan(self):
        ai_output = {
            "agent": "test",
            "version": "1.0",
            "status": "success",
            "plan": {
                "action": "create_playlist",
                "parameters": {"name": "test"},
            },
            "requires_approval": False,
        }
        result = self.bridge.process_ai_decision("test", ai_output)
        self.assertTrue(result["success"])
        plan = result["execution_plan"]
        self.assertIn("create_playlist", plan["actions"])


if __name__ == "__main__":
    unittest.main()
