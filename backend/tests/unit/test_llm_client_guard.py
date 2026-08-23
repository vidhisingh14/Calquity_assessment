"""Blocking gate: tools and response_format must never be combined.

Providers handle the combination inconsistently and the failure is silent in
the worst case, so this is enforced by an assertion in the client rather than
by a convention. This test is what stops the guard being removed later by
someone who finds it inconvenient.
"""

from __future__ import annotations

import pytest

from app.llm.client import MutuallyExclusiveRequestError, _guard

TOOLS = [{"type": "function", "function": {"name": "lookup_records", "parameters": {}}}]
SCHEMA = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}


def test_tools_alone_is_fine():
    _guard(TOOLS, None)


def test_response_format_alone_is_fine():
    _guard(None, SCHEMA)


def test_neither_is_fine():
    _guard(None, None)


def test_both_together_raises():
    with pytest.raises(MutuallyExclusiveRequestError) as exc:
        _guard(TOOLS, SCHEMA)
    assert "same request" in str(exc.value)


def test_guard_is_called_by_every_client_implementation():
    """A new provider that forgets the guard reintroduces the bug, so the
    presence of the call is asserted rather than assumed."""
    import inspect

    from app.llm.client import CerebrasChatClient, GeminiChatClient

    for client in (CerebrasChatClient, GeminiChatClient):
        source = inspect.getsource(client.complete)
        assert "_guard(tools, response_format)" in source, (
            f"{client.__name__}.complete must call _guard"
        )
