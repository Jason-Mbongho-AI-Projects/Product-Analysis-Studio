"""Pydantic -> strict JSON Schema conversion.

Strict structured output is stricter than JSON Schema in general:

* every object must set ``additionalProperties: false``
* every property must appear in ``required`` (optionality is expressed as a
  ``null`` member of an ``anyOf`` instead)
* validation keywords such as ``minimum`` / ``maxLength`` / ``format`` are
  rejected outright

Pydantic emits none of that by default, so we normalise here rather than
hand-maintaining a second copy of every schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: Keywords the strict decoder rejects. Stripped rather than passed through,
#: because Pydantic still enforces them on the way back in.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "format",
        "examples",
        "discriminator",
    }
)


def _normalise(node: Any) -> Any:
    if isinstance(node, list):
        return [_normalise(item) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned: dict[str, Any] = {
        key: _normalise(value)
        for key, value in node.items()
        if key not in _UNSUPPORTED_KEYWORDS
    }

    # A `$ref` may not carry sibling keywords in strict mode. Pydantic attaches
    # `description` next to the ref whenever an enum field has a Field(...)
    # description, so drop the siblings; the referenced definition keeps its own.
    if "$ref" in cleaned and len(cleaned) > 1:
        return {"$ref": cleaned["$ref"]}

    if cleaned.get("type") == "object" or "properties" in cleaned:
        properties = cleaned.get("properties", {})
        cleaned["properties"] = properties
        cleaned["additionalProperties"] = False
        # Strict mode requires *every* property to be required.
        cleaned["required"] = list(properties.keys())

    return cleaned


def to_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a strict-mode JSON Schema for ``model``."""
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    return _normalise(schema)


def response_format_for(model: type[BaseModel]) -> dict[str, Any]:
    """Build the ``response_format`` payload for a chat completion."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "strict": True,
            "schema": to_strict_schema(model),
        },
    }
