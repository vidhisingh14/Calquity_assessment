"""The AuthContext.

Built once per request in api/deps.py and passed down EXPLICITLY. It is never
read from a global and never reconstructed inside a tool -- a tool that can
build its own context can build one with the wrong scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["customer", "support_agent", "ops_lead"]


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    role: Role
    account_id: str | None          # None for internal staff
    display_name: str = ""

    @property
    def is_internal(self) -> bool:
        return self.role in ("support_agent", "ops_lead")

    def account_scope_filter(self) -> str | None:
        """None means unrestricted; a string restricts to that account.

        Derived from the ROLE, never from anything the model supplied. A
        customer always gets their own account id here regardless of what a
        tool call asked for.
        """
        return self.account_id if self.role == "customer" else None
