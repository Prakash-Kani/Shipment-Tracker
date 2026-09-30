# ========== Standalone Health Check / Keep-Alive Module ==========
#
# Completely separate from auto_distance_update.py. Mount this router in your
# FastAPI app to:
#   1. Expose GET /health so your hosting platform / load balancer / uptime
#      monitor can confirm the process is alive.
#   2. Run a background loop that pings that same /health endpoint every
#      30 minutes, so platforms that spin down idle instances (Render free
#      tier, Railway, similar "serverless"/idle-timeout hosts) never see the
#      app go quiet long enough to shut it down.
#
# This does NOT touch distance-tracking state and imports nothing from
# auto_distance_update.py.

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional
from app.core.config import settings
import httpx
from fastapi import APIRouter

router = APIRouter()

START_TIME = datetime.now(timezone.utc)

# How often to self-ping. 30 minutes, as requested.
PING_INTERVAL_SECONDS = 30 * 60

# The full URL of THIS app's own /health endpoint, e.g.
#   https://your-service.onrender.com/health
# Set this as an environment variable at deploy time. If it's not set, the
# keep-alive loop logs a warning and does nothing (the /health endpoint
# itself still works for platform health checks either way).
SELF_HEALTH_URL: Optional[str] = settings.self_health_url

_keepalive_task: Optional[asyncio.Task] = None


@router.get("/health")
async def health():
    """Plain liveness endpoint. Always returns 200 while the process is up."""
    now = datetime.now(timezone.utc)
    return {
        "status": "ok",
        "server_time": now.isoformat(),
        "uptime_seconds": (now - START_TIME).total_seconds(),
    }


async def _keepalive_loop():
    if not SELF_HEALTH_URL:
        print(
            "[health] SELF_HEALTH_URL is not set - self-ping keep-alive loop "
            "is disabled. Set it to this app's own /health URL to enable it."
        )
        return

    print(f"[health] keep-alive loop started, pinging {SELF_HEALTH_URL} every {PING_INTERVAL_SECONDS}s")
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(SELF_HEALTH_URL)
                print(f"[health] self-ping -> {response.status_code}")
            except Exception as exc:
                # A failed ping must never crash the loop or the app.
                print(f"[health] self-ping failed: {exc}")
            await asyncio.sleep(PING_INTERVAL_SECONDS)


def start_keepalive():
    """Call once from your app's startup hook."""
    global _keepalive_task
    if _keepalive_task is None or _keepalive_task.done():
        _keepalive_task = asyncio.create_task(_keepalive_loop())


async def stop_keepalive():
    """Call once from your app's shutdown hook."""
    global _keepalive_task
    if _keepalive_task:
        _keepalive_task.cancel()
        _keepalive_task = None