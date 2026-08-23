"""Translating OpenAI-shaped tool calling into Gemini's dialect.

Two incompatibilities make a naive pass-through fail, and both fail LOUDLY as a
400 rather than silently, which is the one merciful thing about them:

1. SCHEMA DIALECT. Pydantic's `model_json_schema()` emits keys Gemini's
   function-declaration parser rejects outright:
     - `additionalProperties`, produced by any `dict` field
     - `anyOf: [{...}, {"type": "null"}]`, produced by every `X | None` field
     - `$defs` / `$ref`, `title`, `default`
   Gemini wants a trimmed OpenAPI subset with `nullable` instead of a null
   union.

2. CONVERSATION SHAPE. OpenAI represents a tool round trip as an assistant
   message carrying `tool_calls` followed by `role: "tool"` messages. Gemini
   represents both as *parts*: a `function_call` part on a model turn, and a
   `function_response` part on a user turn. Dropping them -- which is what a
   role filter does -- leaves the model unable to see its own tool results, so
   it either repeats the call forever or answers from nothing.

Gemini also identifies calls by NAME, not by id. Ids are synthesised so the
agent loop's id-based bookkeeping keeps working unchanged.
"""

from __future__ import annotations

import json
from typing import Any

_STRIP_KEYS = {"title", "default", "additionalProperties", "$schema", "examples"}


def _resolve_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"].rsplit("/", 1)[-1]
            return _resolve_refs(dict(defs.get(ref, {})), defs)
        return {k: _resolve_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, defs) for v in node]
    return node


def sanitise_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a pydantic JSON schema into Gemini's accepted subset."""
    defs = schema.get("$defs", {})
    schema = _resolve_refs({k: v for k, v in schema.items() if k != "$defs"}, defs)
    return _clean(schema)


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(v) for v in node]
    if not isinstance(node, dict):
        return node

    # `X | None` becomes a nullable single type rather than a null union.
    if "anyOf" in node:
        variants = [v for v in node["anyOf"] if v.get("type") != "null"]
        nullable = len(variants) != len(node["anyOf"])
        if len(variants) == 1:
            merged = _clean(variants[0])
            merged.update({k: v for k, v in node.items()
                           if k not in ("anyOf",) and k not in _STRIP_KEYS})
            if nullable:
                merged["nullable"] = True
            return merged
        node = {k: v for k, v in node.items() if k != "anyOf"}
        node["type"] = "string"
        if nullable:
            node["nullable"] = True

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _STRIP_KEYS:
            continue
        out[key] = _clean(value)

    # A free-form object with no declared properties is not expressible; Gemini
    # rejects `type: object` without `properties`, so it degrades to a string
    # the tool parses. Only `stated_facts` and `filters` hit this.
    if out.get("type") == "object" and "properties" not in out:
        return {"type": "string",
                "description": (out.get("description", "") +
                                " Provide as a JSON object string.").strip(),
                **({"nullable": True} if out.get("nullable") else {})}

    return out


def to_function_declarations(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations = []
    for tool in tools:
        fn = tool["function"]
        declarations.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "parameters": sanitise_schema(dict(fn.get("parameters") or {})),
        })
    return declarations


def to_contents(messages: list[dict[str, Any]], types) -> tuple[str, list[Any]]:
    """Split OpenAI-style messages into (system_instruction, contents).

    Tool calls and tool results are carried as parts, not dropped.
    """
    system_chunks: list[str] = []
    contents: list[Any] = []

    for message in messages:
        role = message.get("role")

        if role == "system":
            system_chunks.append(str(message.get("content") or ""))
            continue

        if role == "user":
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=str(message.get("content") or ""))],
            ))
            continue

        if role == "assistant":
            # Replay the provider's own turn verbatim when we have it, so
            # thought_signature survives. Rebuilding loses it and the next
            # request fails with INVALID_ARGUMENT mid-chain.
            provider_content = message.get("_provider_content")
            if provider_content is not None:
                contents.append(provider_content)
                continue
            parts = []
            if message.get("content"):
                parts.append(types.Part(text=str(message["content"])))
            for call in message.get("tool_calls") or []:
                fn = call["function"]
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                parts.append(types.Part(
                    function_call=types.FunctionCall(name=fn["name"], args=args)
                ))
            if parts:
                contents.append(types.Content(role="model", parts=parts))
            continue

        if role == "tool":
            payload = message.get("content")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {"result": payload}
            contents.append(types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(
                    name=message.get("name") or message.get("tool_call_id", "tool"),
                    response=payload if isinstance(payload, dict) else {"result": payload},
                ))],
            ))

    return "\n".join(system_chunks), contents
