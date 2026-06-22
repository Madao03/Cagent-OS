"""Argument checker — JSON Schema validation for tool arguments.

Validates the arguments dict the LLM produces against the tool's
declared JSON Schema before the dispatcher forwards them to the
handler. Catches type mismatches, missing required keys, unknown
keys, and invalid enum values early — before they reach the tool.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cagent_os.plugins.manifests import ToolSpec


@dataclass(frozen=True)
class ArgumentError(Exception):
    """Raised when a tool argument fails schema validation.

    Carries both *field* (the argument key that failed) and *reason*
    (a human-readable explanation) so callers can surface the exact
    problem to the LLM for self-correction.
    """
    field: str
    reason: str

    def __str__(self) -> str:
        return f"Argument '{self.field}': {self.reason}"


class ArgumentChecker:
    """Validate tool arguments against their declared JSON Schema.

    The checker follows JSON Schema (draft-07) subset conventions:
    ``type``, ``properties``, ``required``, ``enum``, ``items``, and
    ``default``.  An open schema (no properties, no required) passes
    through unchanged — this is the escape hatch for tools that accept
    arbitrary payloads.
    """

    def check(
        self,
        *,
        manifest: ToolSpec,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate *arguments* against *manifest.parameters*.

        Returns a normalized dict (unknown keys dropped, defaults
        filled in). Raises :class:`ArgumentError` on any mismatch.
        """
        if not isinstance(arguments, dict):
            raise ArgumentError(field="(root)", reason="arguments must be a JSON object")

        schema = manifest.parameters or {"type": "object", "properties": {}}
        if schema.get("type") != "object":
            raise ArgumentError(
                field="(root)",
                reason=f"tool '{manifest.capability_id}' must declare an object schema",
            )

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required", [])
        if not isinstance(required, list):
            required = []

        # Open schema — accept anything
        if not properties and not required:
            return dict(arguments)

        # Reject unknown keys
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ArgumentError(
                field=unknown[0],
                reason=f"unknown argument(s): {', '.join(unknown)}",
            )

        # Check required keys
        for key in required:
            if key not in arguments:
                raise ArgumentError(field=key, reason="required argument is missing")

        # Type-check each present key and fill defaults
        normalized: dict[str, Any] = {}
        for key, prop_schema in properties.items():
            if key in arguments:
                normalized[key] = self._check_value(
                    key, arguments[key],
                    prop_schema if isinstance(prop_schema, dict) else {},
                )
            elif isinstance(prop_schema, dict) and "default" in prop_schema:
                normalized[key] = prop_schema["default"]

        return normalized

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_value(self, key: str, value: Any, schema: dict[str, Any]) -> Any:
        """Recursively validate a single value against its sub-schema."""
        declared_type = schema.get("type")

        # No type declared — accept as-is
        if not declared_type:
            return self._check_enum(key, value, schema.get("enum"))

        if declared_type == "string":
            self._expect_type(key, value, str)
            return self._check_enum(key, value, schema.get("enum"))

        if declared_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ArgumentError(field=key, reason=f"expected integer, got {type(value).__name__}")
            return self._check_enum(key, value, schema.get("enum"))

        if declared_type == "boolean":
            self._expect_type(key, value, bool)
            return self._check_enum(key, value, schema.get("enum"))

        if declared_type == "array":
            self._expect_type(key, value, list)
            item_schema = schema.get("items", {})
            if not isinstance(item_schema, dict):
                item_schema = {}
            return [
                self._check_value(f"{key}[{i}]", item, item_schema)
                for i, item in enumerate(value)
            ]

        if declared_type == "object":
            self._expect_type(key, value, dict)
            return self._check_nested_object(key, value, schema)

        # Unknown type — accept
        return value

    def _check_nested_object(self, key: str, value: dict, schema: dict) -> dict:
        """Validate a nested object against its properties/required."""
        nested_props = schema.get("properties")
        if not isinstance(nested_props, dict) or not nested_props:
            return value

        nested_required = schema.get("required", [])
        if not isinstance(nested_required, list):
            nested_required = []

        # Unknown keys in nested object
        nested_unknown = sorted(set(value) - set(nested_props))
        if nested_unknown:
            raise ArgumentError(
                field=f"{key}.{nested_unknown[0]}",
                reason=f"unknown nested argument(s): {', '.join(nested_unknown)}",
            )

        # Required keys in nested object
        for req_key in nested_required:
            if req_key not in value:
                raise ArgumentError(
                    field=f"{key}.{req_key}",
                    reason="required nested argument is missing",
                )

        # Recursively check each nested property
        result: dict[str, Any] = {}
        for nk, ns in nested_props.items():
            if nk in value:
                result[nk] = self._check_value(
                    f"{key}.{nk}", value[nk],
                    ns if isinstance(ns, dict) else {},
                )
            elif isinstance(ns, dict) and "default" in ns:
                result[nk] = ns["default"]

        return result

    @staticmethod
    def _expect_type(key: str, value: Any, expected: type) -> None:
        if not isinstance(value, expected):
            raise ArgumentError(
                field=key,
                reason=f"expected {expected.__name__}, got {type(value).__name__}",
            )

    @staticmethod
    def _check_enum(key: str, value: Any, enum_values: Any) -> Any:
        """If the schema declares an enum, verify *value* is one of them."""
        if not isinstance(enum_values, list) or not enum_values:
            return value
        if value not in enum_values:
            allowed = ", ".join(str(v) for v in enum_values)
            raise ArgumentError(
                field=key,
                reason=f"value '{value}' is not one of: {allowed}",
            )
        return value
