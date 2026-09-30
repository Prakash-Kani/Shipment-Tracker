import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, status, HTTPException, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
import httpx
import json
import logging
from pathlib import Path

from app.core.config import settings, engine, AsyncSessionLocal
from app.api import router as api_router
from app.health_check import router as health_router, start_keepalive, stop_keepalive   # <-- moved to top
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from fastapi.middleware.cors import CORSMiddleware

# Logging setup
log_dir = Path("app/logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    logger.info("Shipment-Tracker app started with root_path: %s", settings.root_path)
    start_keepalive()          # <-- correct place: before yield

    yield

    # ---- shutdown ----
    await stop_keepalive()     # <-- correct place: after yield
    logger.info("Database engine disposed")


app = FastAPI(
    title="Async FastAPI Auth App",
    lifespan=lifespan,
    root_path=settings.root_path
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("app/static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(api_router)
app.include_router(health_router)

# No @app.on_event("startup")/"shutdown") needed anymore — lifespan handles both.