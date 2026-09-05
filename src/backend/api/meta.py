from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

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
