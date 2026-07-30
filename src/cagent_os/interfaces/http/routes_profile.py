"""Profile endpoint — stores user's investment focus (free text, skippable).

Stored as JSON files under data/profiles/{user_id}.json.
Separate from usage table and agent memory (cold/hot).
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from cagent_os.interfaces.http.auth_context import resolve_principal_id

logger = logging.getLogger(__name__)


def build_profile_router(profiles_dir: Path) -> APIRouter:
    router = APIRouter()
    profiles_dir.mkdir(parents=True, exist_ok=True)

    @router.post("/api/v1/profile")
    async def save_profile(request: Request) -> dict:
        principal_id = resolve_principal_id(request)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

        raw_input = str(body.get("raw_input", "")).strip()
        if not raw_input:
            return JSONResponse(status_code=400, content={"detail": "raw_input is required"})

        profile_path = profiles_dir / f"{principal_id}.json"
        try:
            existing = {}
            if profile_path.exists():
                existing = _json.loads(profile_path.read_text(encoding="utf-8"))
            existing["raw_input"] = raw_input
            existing["updated_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()
            profile_path.write_text(_json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Profile saved for %s (%d chars)", principal_id, len(raw_input))
            return {"success": True}
        except Exception as exc:
            logger.error("Failed to save profile for %s: %s", principal_id, exc)
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    return router
