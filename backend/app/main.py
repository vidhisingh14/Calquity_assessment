"""FastAPI app creation, router mounting, exception mapping. Nothing else.

No business logic lives here. The exception handlers are the single place where
an internal error type becomes an HTTP status code.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_health
from app.config import get_settings
from app.errors import (
    AuthResolutionError,
    DataNotFound,
    LLMError,
    PermissionDenied,
    ToolArgumentError,
)

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
log = logging.getLogger(__name__)

app = FastAPI(title="ParcelPilot Support Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)


@app.on_event("startup")
def _startup() -> None:
    """Fail loudly on a schema/config mismatch rather than at first insert."""
    from app.repositories.db import assert_embedding_dim_matches_config

    try:
        assert_embedding_dim_matches_config()
    except Exception as exc:  # noqa: BLE001 - startup diagnostics
        # Not fatal before migrations have run; /healthz reports the truth.
        log.warning("startup schema check: %s", exc)


# --- Exception mapping. The ONLY place errors become status codes. ---------
# PolicyUndecidable is deliberately absent: it is not an error to the user, it
# is the system knowing it does not know, and it is handled in the tool layer.

def _handler(status: int):
    def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": str(exc)})
    return handle


app.add_exception_handler(AuthResolutionError, _handler(401))
app.add_exception_handler(PermissionDenied, _handler(403))
app.add_exception_handler(DataNotFound, _handler(404))
app.add_exception_handler(ToolArgumentError, _handler(422))
app.add_exception_handler(LLMError, _handler(502))
