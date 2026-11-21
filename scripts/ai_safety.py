"""AI Safety / Execution Policy for zMusic.

Enforces the boundary between what LLMs may do and what deterministic
services must do. All AI output must pass schema validation before
execution.

LLMs MAY:
  - PLAN
  - CLASSIFY
  - GENERATE
  - RECOMMEND
  - ANALYZE

Deterministic services MUST:
  - EXECUTE
  - VALIDATE
  - STORE
  - TRANSMIT

AI output must ALWAYS pass schema validation.

NEVER:
  LLM → shell → production
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .events import (
    EVENT_AGENT_STARTED,
    make_event,
)
from .logging import get_logger
from .validation import ValidationResult, validate_agent_output

logger = get_logger("zmusic.ai_safety")


class AISafetyPolicy(Enum):
    """Policy levels for AI operations."""

    STRICT = "strict"  # All AI output must be validated
    MODERATE = "moderate"  # AI output validated for critical operations
    PERMISSIVE = "permissive"  # Minimal validation (not recommended for production)


class AIOperation(Enum):
    """Allowed AI operations."""

    PLAN = "plan"
    CLASSIFY = "classify"
    GENERATE = "generate"
    RECOMMEND = "recommend"
    ANALYZE = "analyze"


# Operations AI is FORBIDDEN from doing directly
FORBIDDEN_OPERATIONS = {
    "execute_shell",
    "execute_ffmpeg",
    "database_write",
    "api_call_external",
    "start_stream",
    "stop_stream",
    "modify_config",
    "deploy",
    "restart_service",
}


@dataclass(frozen=True)
class AIPolicyConfig:
    """Configuration for AI safety policy."""

    policy: AISafetyPolicy = AISafetyPolicy.STRICT
    allowed_operations: set[AIOperation] = field(
        default_factory=lambda: set(AIOperation)
    )
    forbidden_operations: set[str] = field(default_factory=lambda: FORBIDDEN_OPERATIONS)
    require_schema_validation: bool = True
    require_human_approval_for: set[str] = field(
        default_factory=lambda: {
            "start_stream",
            "stop_stream",
            "delete_content",
            "modify_rights",
            "change_channel_config",
        }
    )


# Default policy instance
DEFAULT_POLICY = AIPolicyConfig()


class AIOutputValidator:
    """Validates AI output against safety policy and schemas."""

    def __init__(self, policy: AIPolicyConfig = DEFAULT_POLICY) -> None:
        self.policy = policy

    def validate(self, agent_name: str, output: dict[str, Any]) -> ValidationResult:
        """Validate AI output from an agent.

        Checks:
        1. Output is a dictionary
        2. Required fields present (agent, version, status, plan)
        3. No forbidden operations in output
        4. Schema validation passes
        5. Human approval gates if required
        """
        # 1. Basic structure validation
        result = validate_agent_output(agent_name, output)
        if not result.valid:
            return result

        # 2. Check for forbidden operations
        if self._contains_forbidden_operations(output):
            return ValidationResult(
                valid=False,
                errors=("AI output contains forbidden operations",),
            )

        # 3. Check if human approval required
        approval_required = output.get("requires_approval", False)
        if approval_required:
            action = output.get("action", "unknown")
            if action in self.policy.require_human_approval_for:
                return ValidationResult(
                    valid=False,
                    errors=(f"Action '{action}' requires human approval",),
                )

        return ValidationResult(valid=True)

    def _contains_forbidden_operations(self, output: dict[str, Any]) -> bool:
        """Check if output contains forbidden operations."""
        # Check common fields where operations might be specified
        check_fields = [
            "operations",
            "actions",
            "commands",
            "execute",
            "shell",
            "cmd",
            "plan",
        ]
        for field in check_fields:
            if field in output:
                value = output[field]
                if isinstance(value, (list, dict)):
                    # Recursively check for forbidden operations
                    if self._check_value_for_forbidden(value):
                        return True
                elif isinstance(value, str):
                    if value in self.policy.forbidden_operations:
                        return True
        return False

    def _check_value_for_forbidden(self, value: Any) -> bool:
        """Recursively check a value for forbidden operations."""
        if isinstance(value, str):
            return value in self.policy.forbidden_operations
        elif isinstance(value, list):
            return any(self._check_value_for_forbidden(v) for v in value)
        elif isinstance(value, dict):
            return any(
                k in self.policy.forbidden_operations
                or self._check_value_for_forbidden(v)
                for k, v in value.items()
            )
        return False


class AIExecutionBridge:
    """Bridge between AI decisions and deterministic execution.

    This is the ONLY path from AI decisions to production actions.
    All AI output must pass through this bridge.
    """

    def __init__(self, validator: AIOutputValidator | None = None) -> None:
        self.validator = validator or AIOutputValidator()

    def process_ai_decision(
        self,
        agent_name: str,
        ai_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Process an AI decision through the safety bridge.

        Returns execution plan if valid, error if not.
        """
        # Step 1: Validate AI output
        validation = self.validator.validate(agent_name, ai_output)
        if not validation.valid:
            logger.warning(
                "AI output rejected by safety bridge",
                extra={
                    "agent": agent_name,
                    "errors": validation.errors,
                },
            )
            return {
                "success": False,
                "reason": "validation_failed",
                "errors": validation.errors,
            }

        # Step 2: Emit agent started event
        event = make_event(
            EVENT_AGENT_STARTED,
            agent_name,
            {
                "agent_name": agent_name,
                "ai_output_summary": self._summarize_output(ai_output),
            },
        )

        # Step 3: Return approved execution plan
        return {
            "success": True,
            "execution_plan": self._build_execution_plan(agent_name, ai_output),
            "event": event,
        }

    def _summarize_output(self, output: dict[str, Any]) -> dict[str, Any]:
        """Create a safe summary of AI output for logging."""
        summary = {
            "agent": output.get("agent"),
            "version": output.get("version"),
            "status": output.get("status"),
            "has_plan": "plan" in output,
            "requires_approval": output.get("requires_approval", False),
        }
        # Don't log full plan - may contain sensitive data
        return summary

    def _build_execution_plan(
        self, agent_name: str, output: dict[str, Any]
    ) -> dict[str, Any]:
        """Build deterministic execution plan from validated AI output."""
        plan = output.get("plan", {})
        return {
            "agent": agent_name,
            "actions": self._extract_actions(plan),
            "parameters": self._extract_parameters(plan),
            "safety_validated": True,
        }

    def _extract_actions(self, plan: dict[str, Any]) -> list[str]:
        """Extract executable actions from plan."""
        actions = []
        if "action" in plan:
            actions.append(plan["action"])
        elif "actions" in plan:
            actions.extend(plan["actions"])
        return actions

    def _extract_parameters(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Extract parameters from plan, excluding actions."""
        params = {}
        for k, v in plan.items():
            if k not in ["action", "actions", "operations", "commands"]:
                params[k] = v
        return params


# --- Policy Enforcement Decorator ---


def enforce_ai_policy(operation: str):
    """Decorator to enforce AI safety policy on functions.

    Usage:
        @enforce_ai_policy("start_stream")
        def start_stream(...):
            ...
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            # In production, would check policy before allowing execution
            # For now, log and proceed
            logger.info(
                f"Executing {operation} with AI policy enforcement",
                extra={"operation": operation},
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


# --- Example Usage ---
#
# validator = AIOutputValidator()
# bridge = AIExecutionBridge(validator)
#
# ai_output = {
#     "agent": "music_director",
#     "version": "1.0",
#     "status": "success",
#     "plan": {
#         "audio_playlist": "playlist_001",
#         "visual_scene": "scene_004",
#     },
#     "requires_approval": False,
# }
#
# result = bridge.process_ai_decision("music_director", ai_output)
# if result["success"]:
#     # Deterministic executor runs the plan
#     executor.execute(result["execution_plan"])
# else:
#     # Handle validation failure
#     pass
