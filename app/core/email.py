from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
import pandas as pd
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class EmailConfig:
    @staticmethod
    def get_config():
            # Validate required fields for production
        required = [settings.mail_username, settings.mail_password, settings.mail_from, settings.mail_server, settings.mail_from_name]
        if not all(required):
            logger.warning("Production email config incomplete – falling back to dev mode (no emails sent)")
            return ConnectionConfig(SUPPRESS_SEND=1)

        return ConnectionConfig(
            MAIL_USERNAME=settings.mail_username,
            MAIL_PASSWORD=settings.mail_password,
            MAIL_FROM=settings.mail_from,
            MAIL_FROM_NAME=settings.mail_from_name,
            MAIL_PORT=settings.mail_port or 587,
            MAIL_SERVER=settings.mail_server,
            MAIL_STARTTLS = True,
            MAIL_SSL_TLS = False,
            USE_CREDENTIALS = True,
            VALIDATE_CERTS = True
        )
        

# Instantiate once at import time
conf = EmailConfig.get_config()
fm = FastMail(conf)

async def send_reset_email(email: str, username: str, reset_url: str):
    template = f"""
    <div style="font-family: 'Poppins', sans-serif; max-width: 600px; margin: auto; padding: 30px; background: #f8fafc; border-radius: 16px; text-align: center;">
        <h2 style="color: #2563eb;">Password Reset Request</h2>
        <p>Hello <strong>{username}</strong>,</p>
        <p>You requested to reset your password for <strong>Accounts AI</strong>.</p>
        <div style="margin: 40px 0;">
            <a href="{reset_url}" style="background: linear-gradient(135deg, #38bdf8, #22c55e); color: white; padding: 16px 36px; border-radius: 999px; text-decoration: none; font-weight: 600; font-size: 16px; display: inline-block;">
                Reset Password Now
            </a>
        </div>
        <p><small>This link will expire in 15 minutes.</small></p>
        <p><small>If you didn't request this, please ignore this email.</small></p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 40px 0;">
        <p style="color: #64748b; font-size: 13px;">© 2025 Accounts AI • Secure Financial Management</p>
    </div>
    """

    message = MessageSchema(
        subject="Reset Your Accounts AI Password",
        recipients=[email],
        body=template,
        subtype="html"
    )

    try:
        await fm.send_message(message)
        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send email to {email}: {e}")
   
