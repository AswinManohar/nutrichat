from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.nutrients.catalog import public_view

router = APIRouter(prefix="/meta", tags=["meta"])


class AppVersionResponse(BaseModel):
    min_supported_version_code: int
    latest_version_code: int

    model_config = ConfigDict(extra="forbid")


@router.get("/app", response_model=AppVersionResponse)
async def app_version() -> AppVersionResponse:
    """Version gate for the Android client (unauthed).

    A client below min_supported_version_code must block and prompt an
    upgrade; between min and latest it may show a soft nudge.
    """
    return AppVersionResponse(
        min_supported_version_code=int(
            os.environ.get("ANDROID_MIN_VERSION_CODE", "1")
        ),
        latest_version_code=int(
            os.environ.get("ANDROID_LATEST_VERSION_CODE", "1")
        ),
    )


@router.get("/nutrients")
async def nutrient_catalogue() -> JSONResponse:
    """The tracked-nutrient catalogue for clients (unauthed, cacheable).

    The only place clients learn the tracked nutrients, their groups, units,
    daily values and display order (spec 008 FR-015); server-only fields
    (USDA aliases, caps, storage column) are omitted. Contract:
    specs/008-fixed-micronutrients/contracts/nutrients-catalogue.md.
    """
    return JSONResponse(
        public_view(), headers={"Cache-Control": "public, max-age=3600"}
    )
