"""The agent loop. Hand-rolled so every step is inspectable and streamable.

No SQL, no domain formulas, no HTTP objects. The loop knows tool names and
schemas; it does not know what a cancellation fee is.

Step budget is a SIGNAL, not a crash: on exhaustion it returns what is known,
says the chain was cut short, and offers escalation.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.agent import prompts, registry
from app.auth.context import AuthContext
from app.config import get_settings
from app.errors import LLMError
from app.tools.base import ToolResult

log = logging.getLogger(__name__)


@dataclass
class Step:
    tool: str
    args_summary: str
    ok: bool
    ms: int
    error: str | None = None
    raw_args: dict[str, Any] = field(default_factory=dict)
    raw_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args_summary": self.args_summary,
            "ok": self.ok,
            "ms": self.ms,
            "error": self.error,
        }


@dataclass
class TurnResult:
    answer: str
    steps: list[Step] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    excluded_sources: list[dict[str, Any]] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    budget_exhausted: bool = False
    tool_names_seen: list[str] = field(default_factory=list)
    invalid_tool_names: list[str] = field(default_factory=list)
    invalid_args: list[dict[str, Any]] = field(default_factory=list)


def _summarise(name: str, args: dict[str, Any]) -> str:
    if name == "lookup_records":
        return f"{args.get('entity')} {args.get('record_id') or args.get('filters') or ''}".strip()
    if name == "search_documents":
        return str(args.get("query", ""))[:70]
    if name == "evaluate_policy":
        target = args.get("order_id") or args.get("ticket_id") or "stated facts"
        return f"{args.get('rule')} {target}"
    if name == "create_escalation":
        return str(args.get("summary", ""))[:70]
    return json.dumps(args)[:70]


def run_turn(
    message: str,
    ctx: AuthContext,
    snapshot_time,
    session_id: str,
    history: list[dict[str, Any]] | None = None,
    chat_client=None,
    account_name: str | None = None,
    on_step=None,
) -> TurnResult:
    """`on_step`, if given, is called with each Step as it completes -- this is
    what SSE streaming hooks into, so the tool timeline updates live rather
    than only after the whole turn finishes."""
    settings = get_settings()
    if chat_client is None:
        from app.llm.client import get_chat_client

        chat_client = get_chat_client()

    system = prompts.build_system_prompt(ctx, snapshot_time, account_name)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": message})

    result = TurnResult(answer="")
    tool_schemas = registry.schemas()

    for _ in range(settings.max_agent_steps):
        try:
            response = chat_client.complete(messages=messages, tools=tool_schemas)
        except LLMError as exc:
            log.error("llm_error %s", exc)
            result.answer = (
                "I could not complete that request because the language model was "
                "unavailable. Please try again."
            )
            return result

        if not response.has_tool_calls:
            result.answer = response.content or ""
            return result

        # Record the assistant turn that carried the tool calls.
        messages.append({
            "role": "assistant",
            "content": response.content or "",
            # Carried so providers that require their own turn replayed
            # verbatim (Gemini's thought_signature) keep working.
            "_provider_content": getattr(response, "provider_content", None),
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name,
                                 "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ],
        })

        broke_for_confirmation = False

        for call in response.tool_calls:
            result.tool_names_seen.append(call.name)
            started = time.perf_counter()

            tool = registry.get(call.name)
            if tool is None:
                # Unknown name goes back to the model as a retryable error, with
                # the valid list, rather than ending the turn.
                result.invalid_tool_names.append(call.name)
                payload = ToolResult(
                    ok=False,
                    error=f"Unknown tool {call.name!r}. Available: {registry.names()}",
                ).to_dict()
                result.steps.append(Step(call.name, "", False, 0,
                                         error="unknown tool"))
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "name": call.name, "content": json.dumps(payload)})
                continue

            try:
                args = tool.args_model(**call.arguments)
            except Exception as exc:  # noqa: BLE001 - validation feedback
                result.invalid_args.append({"tool": call.name,
                                            "args": call.arguments,
                                            "error": str(exc)})
                payload = ToolResult(
                    ok=False,
                    error=f"Invalid arguments: {exc}. Schema: "
                          f"{tool.args_model.model_json_schema()}",
                ).to_dict()
                result.steps.append(Step(call.name, _summarise(call.name, call.arguments),
                                         False, 0, error="invalid arguments"))
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "name": call.name, "content": json.dumps(payload)})
                continue

            if tool.requires_confirmation:
                # Prepare mode only. Nothing is written; the loop breaks so the
                # user sees the draft before anything happens.
                tool_result = tool.run(args, ctx, session_id=session_id)
                result.pending_action = tool_result.data if tool_result.ok else None
                broke_for_confirmation = True
            else:
                tool_result = tool.run(args, ctx)

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result.steps.append(Step(
                tool=call.name,
                args_summary=_summarise(call.name, call.arguments),
                ok=tool_result.ok,
                ms=elapsed_ms,
                error=tool_result.error,
                raw_args=call.arguments,
                raw_result=tool_result.data,
            ))

            _collect(result, call.name, tool_result)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "name": call.name,
                             "content": json.dumps(tool_result.to_dict(),
                                                   default=str)})
            if on_step is not None:
                on_step(result.steps[-1])

        if broke_for_confirmation:
            result.answer = response.content or (
                "I have prepared this escalation. It is awaiting your "
                "confirmation and nothing has been created yet."
            )
            return result

    # Budget exhausted: a signal, not a crash.
    result.budget_exhausted = True
    result.answer = (
        "I gathered some information but could not finish the full chain of "
        "checks within my step budget, so I am not confident enough to give a "
        "final answer. I can escalate this to a human specialist."
    )
    return result


def _collect(result: TurnResult, tool_name: str, tool_result: ToolResult) -> None:
    # Deduplicate by (doc_id, chunk_id) and keep the richest record. The same
    # document legitimately arrives from several tools -- evaluate_policy names
    # it as the governing source, search_documents returns its chunks -- and the
    # UI renders one card per source, so duplicates and tier-less stubs both
    # show up as visible defects.
    for source in tool_result.sources:
        key = (source.get("doc_id"), source.get("chunk_id"))
        existing = next(
            (s for s in result.sources
             if (s.get("doc_id"), s.get("chunk_id")) == key), None
        )
        if existing is None:
            result.sources.append(dict(source))
        else:
            for field_name, value in source.items():
                if existing.get(field_name) is None and value is not None:
                    existing[field_name] = value

    # A doc_id with no chunk (from a verdict) is redundant once a real chunk
    # from the same document is present.
    with_chunks = {s["doc_id"] for s in result.sources if s.get("chunk_id")}
    result.sources[:] = [
        s for s in result.sources
        if s.get("chunk_id") or s.get("doc_id") not in with_chunks
    ]

    data = tool_result.data or {}
    for c in data.get("conflicts", []) or []:
        if c not in result.conflicts:
            result.conflicts.append(c)
    for e in data.get("excluded", []) or []:
        if e not in result.excluded_sources:
            result.excluded_sources.append(e)
    if tool_name == "evaluate_policy" and data.get("outcome"):
        result.verdicts.append(data)
