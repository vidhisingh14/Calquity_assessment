"""Health and ingestion sanity. Deliberately unauthenticated.

This endpoint is the answer to the build spec's last debug-map row, "works
locally, wrong in production -- ingestion never ran on the deployed database".
It reports row counts, the snapshot time, and the verified/unverified term
split, so a deployed instance can be checked in one request.

The controller stays thin: it calls one service entry point and shapes the
response. It does not reach the data layer.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services import health

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    return health.health_report()
