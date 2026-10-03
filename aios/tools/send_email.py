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
        # SMTP was hardcoded to one consumer host with password="" and
        # username=to, so every send failed auth. The per-tenant settings the
        # dashboard already collects (org_settings.ALLOWED_KEYS) were never read.
        cfg = await self._smtp_config()
        if not cfg.get("host"):
            return {
                "sent": False, "to": to, "subject": subject,
                "error": "SMTP nao configurado para esta org "
                         "(host/user/password em Configuracoes -> Integracoes)",
            }
        sender = cfg.get("from_email") or cfg.get("user") or ""
        if not sender:
            return {
                "sent": False, "to": to, "subject": subject,
                "error": "SMTP sem remetente (smtp_from_email) e sem usuario",
            }
        try:
            from aiosmtplib import send
            from email.mime.text import MIMEText

            msg = MIMEText(body)
            msg["Subject"] = subject
            # From was `to`, so even a successful send came from the recipient.
            msg["From"] = sender
            msg["To"] = to

            await send(
                msg,
                hostname=cfg["host"],
                port=int(cfg.get("port") or 587),
                start_tls=bool(cfg.get("start_tls", True)),
                username=cfg.get("user") or None,
                password=cfg.get("password") or None,
            )
            return {"sent": True, "to": to, "from": sender, "subject": subject}
        except Exception as e:
            logger.exception("Email send failed to %s", to)
            return {"sent": False, "to": to, "subject": subject, "error": str(e)}

    async def _smtp_config(self) -> dict:
        """This org's SMTP settings, falling back to the instance defaults."""
        from aios.config import settings

        cfg = {
            "host": "",
            "port": 587,
            "user": "",
            "password": "",
            "from_email": "",
            "start_tls": True,
        }
        org_id = getattr(self, "_org_id", "") or ""
        if org_id:
            try:
                from aios.core.org_settings import get_org_secret_async

                for key in ("smtp_host", "smtp_user", "smtp_password", "smtp_from_email"):
                    val = await get_org_secret_async(org_id, key)
                    if val:
                        cfg[key.removeprefix("smtp_")] = val
                port = await get_org_secret_async(org_id, "smtp_port")
                if port:
                    try:
                        cfg["port"] = int(port)
                    except (TypeError, ValueError):
                        pass
            except Exception:
                logger.debug("per-org SMTP lookup failed", exc_info=True)
        if not cfg["host"] and settings.smtp_host:
            cfg["host"] = settings.smtp_host
            cfg["user"] = cfg["user"] or settings.smtp_user
            cfg["password"] = cfg["password"] or settings.smtp_password
        return cfg


TOOL_REGISTRY["send_email"] = {
    "code_reference": "aios.tools.send_email.SendEmailTool",
}
