"""Chat turn orchestration: the single entry point the controller calls.

Sits between the API and the agent so the controller stays HTTP-only and the
agent stays free of persistence concerns.
"""

from __future__ import annotations

import time
from typing import Any

from app.agent import loop, memory, prompts, validator
from app.auth.context import AuthContext
from app.repositories import accounts_repo, messages_repo, system_repo, users_repo


def _account_name(ctx: AuthContext) -> str | None:
    if not ctx.account_id:
        return None
    row = accounts_repo.get_account(ctx.account_id, ctx.account_scope_filter())
    return row["account_name"] if row else None


def handle_turn(session_id: str, message: str, ctx: AuthContext) -> dict[str, Any]:
    started = time.perf_counter()
    snapshot = system_repo.get_snapshot_time()

    history = memory.load_history(session_id, ctx.user_id)
    memory.append_user(session_id, ctx.user_id, message)

    turn = loop.run_turn(
        message=message,
        ctx=ctx,
        snapshot_time=snapshot,
        session_id=session_id,
        history=history,
        account_name=_account_name(ctx),
    )

    verdict = validator.validate(
        answer=turn.answer,
        question=message,
        sources=turn.sources,
        verdicts=turn.verdicts,
        conflicts=turn.conflicts,
        steps=turn.steps,
        account_scope=ctx.account_scope_filter(),
    )

    escalation_offered = (
        verdict.escalation_offered
        or turn.budget_exhausted
        or any(v.get("outcome") == "undecidable" for v in turn.verdicts)
    )

    envelope = {
        "session_id": session_id,
        "answer": verdict.answer or turn.answer,
        "confidence": verdict.confidence,
        "sources": turn.sources,
        "steps": [s.to_dict() for s in turn.steps],
        "conflicts": turn.conflicts,
        "excluded_sources": turn.excluded_sources,
        "verdicts": turn.verdicts,
        "pending_action": turn.pending_action,
        "escalation_offered": escalation_offered,
        "validator_flags": verdict.flags,
        "prompt_version": prompts.PROMPT_VERSION,
    }

    memory.append_assistant(session_id, ctx.user_id, envelope["answer"], envelope)

    messages_repo.write_trace({
        "session_id": session_id,
        "user_id": ctx.user_id,
        "role": ctx.role,
        "question": message,
        "answer": envelope["answer"],
        "tools_called": [s.tool for s in turn.steps],
        "doc_ids_cited": [s.get("doc_id") for s in turn.sources if s.get("doc_id")],
        "confidence": verdict.confidence,
        "escalated": escalation_offered,
        "validator_flags": verdict.flags,
        "overrides": [v for v in turn.verdicts if v.get("override_applied")],
        "latency_ms": int((time.perf_counter() - started) * 1000),
    })

    return envelope


def handle_turn_streaming(session_id: str, message: str, ctx: AuthContext):
    """Generator: yields ("step", payload) events live, then one terminal
    ("answer", envelope) event. Runs the turn on a background thread so a step
    can be yielded the moment its tool call finishes, rather than only after
    the whole turn completes.
    """
    import queue
    import threading

    events: "queue.Queue[tuple[str, dict] | None]" = queue.Queue()

    def on_step(step):
        events.put(("step", step.to_dict()))

    def worker():
        started = time.perf_counter()
        snapshot = system_repo.get_snapshot_time()
        history_rows = memory.load_history(session_id, ctx.user_id)
        memory.append_user(session_id, ctx.user_id, message)

        turn = loop.run_turn(
            message=message, ctx=ctx, snapshot_time=snapshot,
            session_id=session_id, history=history_rows,
            account_name=_account_name(ctx), on_step=on_step,
        )

        verdict = validator.validate(
            answer=turn.answer, question=message, sources=turn.sources,
            verdicts=turn.verdicts, conflicts=turn.conflicts,
            steps=turn.steps, account_scope=ctx.account_scope_filter(),
        )
        escalation_offered = (
            verdict.escalation_offered or turn.budget_exhausted
            or any(v.get("outcome") == "undecidable" for v in turn.verdicts)
        )
        envelope = {
            "session_id": session_id,
            "answer": verdict.answer or turn.answer,
            "confidence": verdict.confidence,
            "sources": turn.sources,
            "steps": [s.to_dict() for s in turn.steps],
            "conflicts": turn.conflicts,
            "excluded_sources": turn.excluded_sources,
            "verdicts": turn.verdicts,
            "pending_action": turn.pending_action,
            "escalation_offered": escalation_offered,
            "validator_flags": verdict.flags,
            "prompt_version": prompts.PROMPT_VERSION,
        }
        memory.append_assistant(session_id, ctx.user_id, envelope["answer"], envelope)
        messages_repo.write_trace({
            "session_id": session_id, "user_id": ctx.user_id, "role": ctx.role,
            "question": message, "answer": envelope["answer"],
            "tools_called": [s.tool for s in turn.steps],
            "doc_ids_cited": [s.get("doc_id") for s in turn.sources if s.get("doc_id")],
            "confidence": verdict.confidence, "escalated": escalation_offered,
            "validator_flags": verdict.flags,
            "overrides": [v for v in turn.verdicts if v.get("override_applied")],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
        events.put(("answer", envelope))
        events.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while True:
        item = events.get()
        if item is None:
            break
        yield item


def history(session_id: str, ctx: AuthContext) -> list[dict[str, Any]]:
    rows = memory.transcript(session_id)
    return [{
        "role": r["role"],
        "content": r["content"],
        "envelope": r["envelope"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    } for r in rows]


def demo_users() -> list[dict[str, Any]]:
    return users_repo.list_users()
