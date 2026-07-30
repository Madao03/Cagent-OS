"""Cost tracking HTTP endpoint — shows per-user token usage and budget status."""

from __future__ import annotations

from fastapi import APIRouter, Request

from cagent_os.config.cost_tracker import CostTracker
from cagent_os.interfaces.http.auth_context import resolve_principal_id


def build_cost_router(cost_tracker: CostTracker) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/cost/usage")
    def get_cost_usage(request: Request) -> dict:
        """Return current token usage and budget limits for the authenticated user."""
        principal_id = resolve_principal_id(request)
        usage = cost_tracker.get_usage(principal_id)
        return {"principal_id": principal_id, **usage}

    return router
