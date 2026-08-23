"""One exception per layer, so the type tells you where the bug lives.

Mapping to HTTP happens in exactly one place (app/main.py). No layer below the
API knows what a status code is.
"""

from __future__ import annotations


class ParcelPilotError(Exception):
    """Base for everything this codebase raises deliberately."""


class AuthResolutionError(ParcelPilotError):
    """auth: the claimed identity could not be resolved. -> 401"""


class PermissionDenied(ParcelPilotError):
    """auth: identity resolved, action not allowed. -> 403"""


class ToolArgumentError(ParcelPilotError):
    """tools: the model's arguments failed validation.

    Surfaced back to the model as a retryable tool error rather than crashing
    the turn, so it can correct itself.
    """


class DataNotFound(ParcelPilotError):
    """repositories: no row. Becomes an empty tool result, never a hint that
    the record exists on another account."""


class PolicyUndecidable(ParcelPilotError):
    """services: the rules cannot reach a confident verdict.

    This is NOT an error to the user. It is the system knowing it does not
    know, and it routes to escalation. It is deliberately absent from the HTTP
    error map for that reason.
    """

    def __init__(self, reason: str, *, rule: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rule = rule


class LLMError(ParcelPilotError):
    """llm: provider failure. -> 502"""


class StepBudgetExceeded(ParcelPilotError):
    """agent: the loop hit its step budget.

    A signal, not a crash: return what is known, say the chain was cut short,
    offer escalation.
    """


class IngestionError(ParcelPilotError):
    """ingestion: an assertion failed. Always fails loudly and early -- a
    silent ingestion bug poisons every answer downstream while sounding
    perfectly confident."""
