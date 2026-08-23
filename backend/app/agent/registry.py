"""Tool name -> callable + JSON schema. Deliberately dumb.

The registry knows tool NAMES and SCHEMAS. It does not know what a
cancellation fee is. Adding a capability means adding a file in tools/ and one
line here.
"""

from __future__ import annotations

from typing import Any

from app.tools import (
    create_escalation,
    evaluate_policy,
    lookup_records,
    search_documents,
)
from app.tools.base import Tool, json_schema

_TOOLS: dict[str, Tool] = {
    lookup_records.TOOL.name: lookup_records.TOOL,
    search_documents.TOOL.name: search_documents.TOOL,
    evaluate_policy.TOOL.name: evaluate_policy.TOOL,
    create_escalation.TOOL.name: create_escalation.TOOL,
}


def get(name: str) -> Tool | None:
    return _TOOLS.get(name)


def names() -> list[str]:
    return list(_TOOLS)


def schemas() -> list[dict[str, Any]]:
    return [json_schema(tool) for tool in _TOOLS.values()]


def requires_confirmation(name: str) -> bool:
    tool = _TOOLS.get(name)
    return bool(tool and tool.requires_confirmation)
