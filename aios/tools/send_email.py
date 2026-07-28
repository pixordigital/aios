"""Send email tool — real SMTP via aiosmtplib."""

import logging

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class SendEmailInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body text")


class SendEmailTool(BaseTool):
    name = "send_email"
    description = "Send an email to a recipient"
    input_model = SendEmailInput

    async def run(self, to: str, subject: str, body: str) -> dict:
        try:
            from aiosmtplib import send
            from email.mime.text import MIMEText

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = to
            msg["To"] = to

            await send(
                msg,
                hostname="smtp.gmail.com",  # override via channel config in production
                port=587,
                start_tls=True,
                username=to,
                password="",  # use app password
            )
            return {"sent": True, "to": to, "subject": subject}
        except Exception as e:
            logger.exception("Email send failed to %s", to)
            return {"sent": False, "to": to, "subject": subject, "error": str(e)}


TOOL_REGISTRY["send_email"] = {
    "code_reference": "aios.tools.send_email.SendEmailTool",
}
