import os
from pydantic_settings import BaseSettings
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import EmailStr

class Settings(BaseSettings):
    mysql_host_name: str = os.getenv("MYSQL_HOST_NAME", "localhost")
    mysql_user_name: str = os.getenv("MYSQL_USER_NAME", "root")
    mysql_password: Optional[str] = os.getenv("MYSQL_PASSWORD")
    mysql_database_name: str = os.getenv("MYSQL_DATABASE_NAME", "payable")
    autocommit: bool = True
    root_path: str = os.getenv("ROOT_PATH", "")
    personal_password: str = os.getenv("PASSWORD", "")

    verify_token: str = os.getenv("VERIFY_TOKEN", "")
    whatsapp_token: str = os.getenv("WHATSAPP_TOKEN", "")
    phone_number_id: str = os.getenv("PHONE_NUMBER_ID", "")

    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_key: str = os.getenv("TWILIO_AUTH_KEY", "")

    gps_key: str = os.getenv("GPS_KEY", "")
    gps_base_url: str = os.getenv("GPS_BASE_URL", "")

    tcard_base_url: str = os.getenv("TCARD_BASE_URL", "")
    # admin_api_key: str = os.getenv("admin_api_key", "")

    # secret_key: str
    # algorithm: str = "HS256"
    # access_token_expire_minutes: int = 30

    # mail_username: Optional[str] = os.getenv("MAIL_USERNAME")
    # mail_password: Optional[str] = os.getenv("MAIL_PASSWORD")
    # mail_from: Optional[EmailStr] = os.getenv("MAIL_FROM")
    # mail_server: Optional[str] = os.getenv("MAIL_SERVER")
    # mail_port: Optional[int] = os.getenv("MAIL_PORT")
    # mail_from_name: Optional[str] = os.getenv("MAIL_FROM_NAME")

    # #scheduler
    # scheduler_reminder_url: str= os.getenv("SCHEDULER_REMINDER_URL")
    # scheduler_timezone: str= os.getenv("SCHEDULER_TIMEZONE")
    # scheduler_hour: int= os.getenv("SCHEDULER_HOUR")
    # scheduler_minute: int= os.getenv("SCHEDULER_MINUTE")
    # # python_worker_index: int= os.getenv("PYTHON_WORKER_INDEX")

    @property
    def database_url(self) -> str:
        password_part = f":{self.mysql_password}" if self.mysql_password else ""
        return f"mysql+aiomysql://{self.mysql_user_name}{password_part}@{self.mysql_host_name}:3306/{self.mysql_database_name}"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()


# Async engine with pool tweaks: Recycle every 1 hour (before MySQL's 8h timeout)
engine = create_async_engine(
    settings.database_url,
    echo=False,  # Set to False in prod; helps debug connection issues
    pool_pre_ping=False,  # Avoids uvloop transport errors during validation
    pool_recycle=3600,    # Refresh idle connections every 1 hour
    pool_size=100,         # Max pooled connections (adjust based on load)
    max_overflow=20,      # Allow temporary extras
    future=True           # Enables SQLAlchemy 2.0+ async features
)

# Async session factory (already bound to engine)
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False  # Reduces unnecessary flushes
)