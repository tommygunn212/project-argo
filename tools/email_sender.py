"""
ARGO Email Sender

Sends emails via SMTP (Gmail by default).
Requires config.json to have:
  "email": {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "your.email@gmail.com",
    "sender_password": "your-app-password"
  }

For Gmail, use an App Password (not your regular password):
  https://myaccount.google.com/apppasswords
"""

import json
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ARGO.Email")

CONFIG_PATH = Path("config.json")


def _load_email_config() -> dict:
    """Load email config from config.json."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("email", {})
    except Exception as e:
        logger.error(f"[EMAIL] Failed to load config: {e}")
        return {}


def is_email_configured() -> bool:
    """Check if email sending is configured."""
    cfg = _load_email_config()
    return bool(cfg.get("sender_email") and cfg.get("sender_password"))


def send_email(
    to_address: str,
    subject: str,
    body: str,
    html: bool = False,
    from_name: Optional[str] = None,
) -> bool:
    """
    Send an email via SMTP.

    Returns True on success, False on failure.
    """
    cfg = _load_email_config()
    sender_email = cfg.get("sender_email")
    sender_password = cfg.get("sender_password")
    smtp_server = cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = cfg.get("smtp_port", 587)

    if not sender_email or not sender_password:
        logger.error("[EMAIL] Email not configured. Add 'email' section to config.json.")
        return False

    if not to_address or "@" not in to_address:
        logger.error(f"[EMAIL] Invalid recipient address: {to_address}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        display_from = f"{from_name} <{sender_email}>" if from_name else sender_email
        msg["From"] = display_from
        msg["To"] = to_address
        msg["Subject"] = subject

        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender_email, sender_password)
            server.send_message(msg)

        logger.info(f"[EMAIL] Sent to {to_address}: {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("[EMAIL] Authentication failed. Check sender_email and sender_password in config.json.")
        return False
    except Exception as e:
        logger.error(f"[EMAIL] Send failed: {e}")
        return False


def send_draft(draft_path: str, to_address: str) -> bool:
    """
    Send a previously saved email draft.

    Parses the draft file to extract To/Subject/Body fields.
    """
    path = Path(draft_path)
    if not path.exists():
        logger.error(f"[EMAIL] Draft not found: {draft_path}")
        return False

    content = path.read_text(encoding="utf-8")

    # Parse header fields
    subject = ""
    body_lines = []
    in_body = False
    for line in content.split("\n"):
        if in_body:
            body_lines.append(line)
        elif line.strip() == "---":
            in_body = True
        elif line.startswith("Subject:"):
            subject = line[len("Subject:"):].strip()

    body = "\n".join(body_lines).strip()
    return send_email(to_address, subject, body)
