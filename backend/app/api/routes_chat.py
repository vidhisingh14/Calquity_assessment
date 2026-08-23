"""Chat controller. HTTP only: parse, delegate once, shape the response.

No business rules here. The controller does not know what a cancellation fee
is, and does not decide whether anything is allowed.

/chat supports both a plain JSON response and, when the client sends
`Accept: text/event-stream`, a live SSE stream of `step` events followed by one
terminal `answer` event carrying the full envelope. The envelope shape is
identical either way -- streaming is an additive delivery mechanism, not a
different contract.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_auth_context
from app.auth.context import AuthContext
from app.services import chat as chat_service

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat")
def post_chat(
    body: ChatRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
):
    wants_stream = "text/event-stream" in (request.headers.get("accept") or "")

    if not wants_stream:
        return chat_service.handle_turn(
            session_id=body.session_id, message=body.message, ctx=ctx
        )

    def generate():
        for event_name, payload in chat_service.handle_turn_streaming(
            session_id=body.session_id, message=body.message, ctx=ctx
        ):
            yield _sse(event_name, payload)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/chat/{session_id}")
def get_history(session_id: str, ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "session_id": session_id,
        "messages": chat_service.history(session_id, ctx),
    }


@router.get("/users")
def list_users() -> dict:
    """Backs the role switcher, which is how access control gets demonstrated."""
    return {"users": chat_service.demo_users()}
