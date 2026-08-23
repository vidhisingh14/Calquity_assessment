"""Claimed identity -> resolved AuthContext.

Identity is mocked (an X-User-Id header). Resolution is not: the id is looked
up in the users table and an unknown id fails closed with AuthResolutionError.
The account_id on the context comes from the DATABASE, never from the request,
so a caller cannot claim an account by asserting it.
"""

from __future__ import annotations

from app.auth.context import AuthContext
from app.errors import AuthResolutionError
from app.repositories import users_repo


def resolve(claimed_user_id: str | None) -> AuthContext:
    if not claimed_user_id:
        raise AuthResolutionError("Missing X-User-Id header")

    row = users_repo.get_user(claimed_user_id)
    if row is None:
        # Deliberately does not distinguish "no such user" from anything else.
        raise AuthResolutionError("Unknown user")

    return AuthContext(
        user_id=row["user_id"],
        role=row["role"],
        account_id=row["account_id"],
        display_name=row["display_name"],
    )
