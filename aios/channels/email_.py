"""Email channel — IMAP IDLE + SMTP with real sending."""
import asyncio
import email
import logging
import uuid
from email.mime.text import MIMEText

from aios.channels.base import Channel, OutboundMessage

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
        # Redis key currently holding this mailbox's poll lease.
        self._lock_key = ""

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
            # Reply to the sender recorded on the conversation, not to
            # `last_from` (written nowhere in the repo) and never to ourselves:
            # the old fallback addressed every reply to the agent's own mailbox,
            # so the customer never received it.
            extra = message.extra_data or {}
            to = (
                extra.get("from_email")
                or extra.get("from")
                or self._config.get("last_from")
                or ""
            )
            if not to:
                logger.warning("Email reply has no recipient in extra_data")
                return None
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
            logger.exception("Email send failed to %s", to)
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

    async def test(self) -> dict:
        import imaplib
        import smtplib

        imap_server = self._config.get("imap_server", "")
        smtp_server = self._config.get("smtp_server", "")
        email_addr = self._config.get("email", "")
        password = self._config.get("password", "")
        smtp_port = int(self._config.get("smtp_port", 587))

        results = {}

        # Test IMAP
        if imap_server and email_addr:
            try:
                mail = imaplib.IMAP4_SSL(imap_server, timeout=10)
                mail.login(email_addr, password)
                mail.logout()
                results["imap"] = {"ok": True, "message": f"IMAP login successful ({email_addr})"}
            except Exception as e:
                logger.exception("IMAP test failed")
                results["imap"] = {"ok": False, "message": str(e)}
        else:
            results["imap"] = {"ok": False, "message": "Missing IMAP server or email"}

        # Test SMTP
        if smtp_server and email_addr:
            try:
                with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(email_addr, password)
                results["smtp"] = {"ok": True, "message": f"SMTP login successful ({email_addr})"}
            except Exception as e:
                logger.exception("SMTP test failed")
                results["smtp"] = {"ok": False, "message": str(e)}
        else:
            results["smtp"] = {"ok": False, "message": "Missing SMTP server or email"}

        overall_ok = all(r.get("ok", False) for r in results.values())
        return {"ok": overall_ok, "message": "Email channel test", "details": results}

    async def _claim_mailbox(self, lock_key: str) -> bool:
        """Take a short-TTL Redis lock on this mailbox. True when we may poll.

        ponytail: SET NX EX, refreshed every cycle. Fine while the loop is one
        poller per process; a Redis-native lease (or moving the poller into the
        ARQ worker) is the upgrade if the TTL ever has to span a restart.
        """
        try:
            from aios.tasks.queue import get_redis_pool

            pool = await get_redis_pool()
            key = f"{lock_key}:{uuid.uuid4().hex[:8]}"
            # 60s > the 30s poll interval, so a healthy holder never expires
            # between cycles and a dead process loses the mailbox in a minute.
            won = await pool.set(key, 1, nx=True, ex=60)
            if won:
                self._lock_key = key
                return True
            return False
        except Exception:
            # Redis down: the platform cannot run agents anyway, and blocking
            # here would silently stop email. Let this process poll alone
            # rather than trading a rare duplicate for guaranteed silence.
            logger.warning("IMAP lock unavailable; polling without it", exc_info=True)
            return True

    async def _poll_loop(self):
        """Poll IMAP inbox every 30s for new messages."""
        imap_server = self._config.get("imap_server", "")
        email_addr = self._config.get("email", "")
        password = self._config.get("password", "")
        if not imap_server or not email_addr:
            logger.warning("Email IMAP not configured, poller disabled")
            return

        seen_uids: set[str] = set()
        # One poller per mailbox, not per process. `main.py` starts every active
        # channel inside the FastAPI lifespan and gunicorn runs --workers 2, so
        # each worker spawned its own IMAP loop. `seen_uids` is in-process, both
        # loops SEARCH UNSEEN and saw the same UID, and the customer got two
        # agent replies and two rounds of LLM spend for one inbound email.
        # Redis is already required, so claim the mailbox with a short TTL lock.
        lock_key = f"aios:imap-poll:{email_addr}"
        while self._running:
            try:
                if not await self._claim_mailbox(lock_key):
                    await asyncio.sleep(30)
                    continue
            except Exception:
                logger.debug("IMAP lock check failed", exc_info=True)
            try:
                import imaplib

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
                    # Route through dispatch_inbound like every other channel.
                    # This used to call AgentRuntime inline with
                    # "email_<uid>" as the conversation id: no Conversation row,
                    # no Message rows, no check_org_limits, no delivery retry
                    # and no DLQ — a failed reply vanished into a log line, and
                    # the agent's answers were invisible to the inbox.
                    from aios.core.dispatch import dispatch_inbound

                    await dispatch_inbound(
                        channel_type="email",
                        channel_connection_id=(
                            self.connection.id if self.connection else ""
                        ),
                        conversation_id="",
                        text=body,
                        user_id=from_addr,
                        extra_data={
                            "source": "imap",
                            "subject": subject,
                            "from_email": from_addr,
                            # IMAP UID is this provider's stable message id, so
                            # it is also the inbound dedup key.
                            "msg_id": f"imap:{self._config.get('email','')}:{uid_str}",
                        },
                    )

                mail.logout()
            except Exception:
                logger.debug("Email poll error (normal if IMAP unavailable)", exc_info=True)

            await asyncio.sleep(30)
