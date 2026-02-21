"""Request and response validation layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from blast_radius_mcp.schemas.common import (
    StructuredError,
    ToolRequestEnvelope,
    ToolResponseEnvelope,
)
from blast_radius_mcp.schemas.tool1_ast import Tool1Request
from blast_radius_mcp.schemas.tool2_lineage import Tool2Request
from blast_radius_mcp.schemas.tool3_semantic import Tool3Request
from blast_radius_mcp.schemas.tool4_coupling import Tool4Request
from blast_radius_mcp.schemas.tool5_tests import Tool5Request
from blast_radius_mcp.schemas.tool1_ast import Tool1Result
from blast_radius_mcp.schemas.tool2_lineage import Tool2Result
from blast_radius_mcp.schemas.tool3_semantic import Tool3Result
from blast_radius_mcp.schemas.tool4_coupling import Tool4Result
from blast_radius_mcp.schemas.tool5_tests import Tool5Result

# Tool name → request model mapping
_TOOL_REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "get_ast_dependencies": Tool1Request,
    "trace_data_shape": Tool2Request,
    "find_semantic_neighbors": Tool3Request,
    "get_historical_coupling": Tool4Request,
    "get_covering_tests": Tool5Request,
}

# Tool name → response result model mapping
_TOOL_RESULT_MODELS: dict[str, type[BaseModel]] = {
    "get_ast_dependencies": Tool1Result,
    "trace_data_shape": Tool2Result,
    "find_semantic_neighbors": Tool3Result,
    "get_historical_coupling": Tool4Result,
    "get_covering_tests": Tool5Result,
}

VALID_TOOL_NAMES = set(_TOOL_REQUEST_MODELS.keys())


def validate_request(envelope: dict[str, Any], tool_name: str) -> ToolRequestEnvelope:
    """Parse and validate an incoming request envelope.

    Args:
        envelope: Raw dictionary from MCP call.
        tool_name: The tool being invoked.

    Returns:
        Validated ToolRequestEnvelope instance.

    Raises:
        ValueError: If tool_name is unknown.
        ValidationError: If envelope is invalid.
    """
    if tool_name not in VALID_TOOL_NAMES:
        raise ValueError(f"Unknown tool: {tool_name!r}. Valid: {sorted(VALID_TOOL_NAMES)}")

    return ToolRequestEnvelope.model_validate(envelope)


def validate_tool_inputs(inputs: dict[str, Any], tool_name: str) -> BaseModel:
    """Validate tool-specific inputs against the correct schema.

    Args:
        inputs: The 'inputs' dict from the request envelope.
        tool_name: The tool being invoked.

    Returns:
        Validated tool-specific request model instance.

    Raises:
        ValueError: If tool_name is unknown.
        ValidationError: If inputs are invalid.
    """
    if tool_name not in _TOOL_REQUEST_MODELS:
        raise ValueError(f"Unknown tool: {tool_name!r}. Valid: {sorted(VALID_TOOL_NAMES)}")

    model_cls = _TOOL_REQUEST_MODELS[tool_name]
    return model_cls.model_validate(inputs)


def validate_response(result: dict[str, Any], tool_name: str) -> ToolResponseEnvelope:
    """Validate an outgoing response envelope (used in tests and debug mode).

    Args:
        result: Raw dictionary of the response.
        tool_name: The tool that produced the response.

    Returns:
        Validated ToolResponseEnvelope instance.

    Raises:
        ValueError: If tool_name is unknown or inconsistent with result.tool_name.
        ValidationError: If response shape is invalid.
    """
    if tool_name not in _TOOL_RESULT_MODELS:
        raise ValueError(f"Unknown tool: {tool_name!r}. Valid: {sorted(VALID_TOOL_NAMES)}")

    envelope = ToolResponseEnvelope.model_validate(result)

    if envelope.tool_name != tool_name:
        raise ValueError(
            f"Response tool_name mismatch: expected {tool_name!r}, got {envelope.tool_name!r}"
        )

    model_cls = _TOOL_RESULT_MODELS[tool_name]
    model_cls.model_validate(envelope.result)

    return envelope


def make_validation_error_response(
    error: ValidationError | ValueError,
    tool_name: str,
) -> StructuredError:
    """Convert a validation error into a StructuredError.

    Args:
        error: The validation or value error.
        tool_name: The tool that was being invoked.

    Returns:
        A StructuredError with code='validation_error'.
    """
    return StructuredError(
        code="validation_error",
        message=str(error),
        retryable=False,
    )
