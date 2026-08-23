"""Dependency injection. Builds the AuthContext once per request."""

from __future__ import annotations

from fastapi import Header

from app.auth import resolver
from app.auth.context import AuthContext


def get_auth_context(x_user_id: str | None = Header(default=None)) -> AuthContext:
    """Mocked identity via a header, real resolution against the users table.

    Raises AuthResolutionError for an unknown or missing id; main.py maps that
    to 401. Everything downstream receives this object explicitly.
    """
    return resolver.resolve(x_user_id)
