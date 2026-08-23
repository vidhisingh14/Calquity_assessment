"""The tool protocol. One file, one capability.

A failed tool RETURNS a result, it does not raise. The agent can then recover
and try something else, instead of the turn dying on a recoverable mistake.

TOOL DESCRIPTIONS ARE LOAD-BEARING. When the model picks the wrong tool, the
fix is in the description string, not the system prompt. Each one is written
as: what it does, when to use it, when NOT to use it, one example.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from app.auth.context import AuthContext


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "meta": {"sources": self.sources, "notes": self.notes},
            "error": self.error,
        }


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]
    requires_confirmation: bool

    def run(self, args: BaseModel, ctx: AuthContext) -> ToolResult: ...


def json_schema(tool: Tool) -> dict[str, Any]:
    """OpenAI-style function schema, built from the tool's pydantic model."""
    schema = tool.args_model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }
