from fastapi import APIRouter

 # Export deps for use elsewhere
from .v1 import api_router  # Now this should work

router = APIRouter()
router.include_router(api_router, prefix="/v1")  # Mount V1 under /api

__all__ = ["router", "require_role"]