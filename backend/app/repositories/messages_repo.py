"""Session message history and turn traces."""

from __future__ import annotations

import json
from typing import Any

from app.repositories.db import connection


def insert(
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    envelope: dict[str, Any] | None,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO session_messages (session_id, user_id, role, content, envelope)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, user_id, role, content,
             json.dumps(envelope) if envelope else None),
        )
        conn.commit()


def recent(session_id: str, limit: int = 12) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM session_messages
            WHERE session_id = %s
            ORDER BY message_id DESC LIMIT %s
            """,
            (session_id, limit),
        ).fetchall()
    return list(reversed(rows))


def all_for_session(session_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT message_id, role, content, envelope, created_at
            FROM session_messages WHERE session_id = %s
            ORDER BY message_id
            """,
            (session_id,),
        ).fetchall()


def write_trace(trace: dict[str, Any]) -> int:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO traces (session_id, user_id, role, question, answer,
                tools_called, doc_ids_cited, confidence, escalated,
                validator_flags, overrides, latency_ms)
            VALUES (%(session_id)s, %(user_id)s, %(role)s, %(question)s, %(answer)s,
                %(tools_called)s, %(doc_ids_cited)s, %(confidence)s, %(escalated)s,
                %(validator_flags)s, %(overrides)s, %(latency_ms)s)
            RETURNING trace_id
            """,
            {
                **trace,
                "tools_called": json.dumps(trace.get("tools_called") or []),
                "doc_ids_cited": json.dumps(trace.get("doc_ids_cited") or []),
                "validator_flags": json.dumps(trace.get("validator_flags") or []),
                "overrides": json.dumps(trace.get("overrides") or []),
            },
        ).fetchone()
        conn.commit()
    return int(row["trace_id"])
