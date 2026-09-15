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
# from app.core.email import send_reset_email
from app.core.config import settings, engine, AsyncSessionLocal
# from app.db.base_class import Base
# from app.db.session import get_db
from app.api import router as api_router
# from app.api.dependencies import get_user_permissions_detailed
# from app.crud.user import authenticate_user, get_user_by_email, get_user_by_username
# from app.core.security import create_access_token, create_password_reset_token, verify_password_reset_token, get_password_hash
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import json
import logging
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
# from app.crud.log_manage import logs, frontend_logs

# # Async DB init function
# async def init_db():
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)



# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Database initialization
#     # await init_db()

#     logger.info("Application startup completed")

#     yield

#     # Shutdown
#     # await engine.dispose()
#     logger.info("Database engine disposed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Home School app started with root_path: %s", settings.root_path)

    yield

    logger.info("Database engine disposed")

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

# App with root_path (auto-prefixes URLs for /soa proxy)
app = FastAPI(
    title="Async FastAPI Auth App",
    lifespan=lifespan,
    root_path=settings.root_path  # NEW: /soa (from .env); empty for local
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods
    allow_headers=["*"],  # Allows all headers
)

os.makedirs("app/static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)


# Mount static files (/soa/static/ with root_path)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include API router (/soa/api/v1/... with root_path)
app.include_router(api_router)


# class AuthMiddleware(BaseHTTPMiddleware):
#     async def dispatch(self, request: Request, call_next):
#         # Only protect routes under /app/
#         if request.url.path.startswith("/app/"):
#             # Get token from cookie (your login sets it in cookie)
#             # token = request.cookies.get("access_token")
#             # if not token:
#             #     return RedirectResponse(url=f"{settings.root_path}/", status_code=302)

#             # # Create fake credentials object expected by the dependency
#             # fake_credentials = HTTPAuthorizationCredentials(
#             #     scheme="bearer",
#             #     credentials=token
#             # )

#             # # Use your existing dependency to get full permissions
#             # try:
#             #     async with AsyncSessionLocal() as db:
#             #         permissions = await get_user_permissions_detailed(
#             #             credentials=fake_credentials,
#             #             db=db  # Will be injected by Depends inside the dependency
#             #         )
#             # except HTTPException:
#             #     # Invalid token or user not found → redirect to login
#             #     return RedirectResponse(url=f"{settings.root_path}/", status_code=302)

#             # # Attach full permissions to request.state.user for templates/middleware
#             # request.state.user = permissions

#         # Continue to next middleware/endpoint
#         response: Response = await call_next(request)
#         return response

# app.add_middleware(AuthMiddleware)

# @app.middleware("http")
# async def allow_iframe(request: Request, call_next):
#     response = await call_next(request)
#     response.headers["Content-Security-Policy"] = (
#         "frame-ancestors https://payable.pixxa.tech:8080/ http://localhost:8007" 
#     )
#     return response

# Startup log
@app.on_event("startup")
async def startup_event():
    logger.info("Home School app started with root_path: %s", settings.root_path)