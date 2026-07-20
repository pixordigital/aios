"""Email channel — IMAP IDLE + SMTP with real sending."""
import asyncio
import email
import logging
from email.mime.text import MIMEText

from aios.channels.base import Channel, InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)


class EmailChannel(Channel):
    channel_type = "email"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._poll_task: asyncio.Task | None = None
        self._running = False

    async def send(self, message: OutboundMessage) -> str | None:
        smtp_server = self._config.get("smtp_server", "")
        email_addr = self._config.get("email", "")
        password = self._config.get("password", "")
        if not smtp_server or not email_addr:
            logger.warning("Email SMTP not configured")
            return None

        try:
            import aiosmtplib
            msg = MIMEText(message.text)
            msg["Subject"] = f"Re: {message.conversation_id[:12]}"
            msg["From"] = email_addr
            to = self._config.get("last_from", "") or email_addr
            msg["To"] = to

            await aiosmtplib.send(
                msg,
                hostname=smtp_server,
                port=587,
                start_tls=True,
                username=email_addr,
                password=password,
            )
            logger.info("Email sent to %s", to)
            return message.conversation_id
        except Exception as e:
            logger.error("Email send failed: %s", e)
            return None

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Email poller started")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

    async def _poll_loop(self):
        """Poll IMAP inbox every 30s for new messages."""
        imap_server = self._config.get("imap_server", "")
        email_addr = self._config.get("email", "")
        password = self._config.get("password", "")
        if not imap_server or not email_addr:
            logger.warning("Email IMAP not configured, poller disabled")
            return

        seen_uids: set[str] = set()
        while self._running:
            try:
                from aiosmtplib import SMTP
                import imaplib
                import time

                mail = imaplib.IMAP4_SSL(imap_server)
                mail.login(email_addr, password)
                mail.select("INBOX")

                _, data = mail.search(None, "UNSEEN")
                uids = data[0].split() if data[0] else []
                new_ids = []
                for uid in uids:
                    uid_str = uid.decode()
                    if uid_str not in seen_uids:
                        new_ids.append(uid)
                        seen_uids.add(uid_str)

                for uid in new_ids:
                    _, msg_data = mail.fetch(uid, "(RFC822)")
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    subject = msg.get("Subject", "")
                    from_addr = msg.get("From", "")
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="replace")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode(errors="replace")

                    logger.info("Email from %s: %s", from_addr, subject[:60])
                    # route to agent
                    if self.agent_or_team:
                        try:
                            if hasattr(self.agent_or_team, "agents"):  # Team
                                from aios.core.orchestrator import TeamOrchestrator
                                orch = TeamOrchestrator(self.agent_or_team, list(self.agent_or_team.agents))
                                reply = await orch.handle_message("email_" + uid_str, body)
                            else:  # single Agent
                                from aios.core.agent import AgentRuntime
                                runtime = AgentRuntime(self.agent_or_team)
                                reply = await runtime.run("email_" + uid_str, body)

                            if reply:
                                outbound = OutboundMessage(
                                    conversation_id="email_" + uid_str,
                                    text=reply,
                                    channel_connection_id=self.connection.id if self.connection else "",
                                )
                                await self.send(outbound)
                        except Exception:
                            logger.exception("Email routing failed")

                mail.logout()
            except Exception:
                logger.debug("Email poll error (normal if IMAP unavailable)", exc_info=True)

            await asyncio.sleep(30)
