"""
aios/tools/calendar.py — CalendarTool (P3 agendamento real)

CalendarTool: name="calendar_create_event"
Inputs: title, datetime_iso (string ISO-8601), attendee_email, description, duration_min

Fluxo em run():
  1) Tenta Google Calendar API se GOOGLE_CALENDAR_CREDENTIALS configurado.
     - GOOGLE_CALENDAR_CREDENTIALS: JSON da service account (conteúdo JSON inline ou path para arquivo)
       via env GOOGLE_CALENDAR_CREDENTIALS / AIOS_GOOGLE_CALENDAR_CREDENTIALS ou settings.google_calendar_credentials
       Opcional: GOOGLE_CALENDAR_ID / AIOS_GOOGLE_CALENDAR_ID (default "primary")
     - Requer libs opcionais: `google-api-python-client` + `google-auth` (import com try; se ausente, cai para próximo)
     - Cria evento via `googleapiclient.discovery.build("calendar","v3", credentials=creds)`
       com summary, description, start/end (ISO), attendees=[attendee_email].
  2) Senão tenta webhook Calendly/Zapier/n8n se CALENDAR_WEBHOOK_URL configurado
     - CALENDAR_WEBHOOK_URL / AIOS_CALENDAR_WEBHOOK_URL ou settings.calendar_webhook_url
     - POST JSON via httpx: {"event":"calendar_create","payload":{title,start_time,end_time,attendee_email,description}}
  3) Fallback mock: persiste em Organization.extra_data["calendar_mock_events"] (últimos 50)
     e também tenta criar Memory(type="calendar_event") se houver Agent/Org.
     Retorna ok + link mock `https://calendar.mock/<uuid>` (ou /mock/calendar/<id>).

Não implementa OAuth flow completo — apenas service account JSON via env e webhook simples.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class CalendarCreateEventInput(BaseModel):
    title: str = Field(description="Título do evento")
    datetime_iso: str = Field(description="Data/hora ISO-8601 ex: 2026-09-15T14:00:00-03:00 ou 2026-09-15T17:00:00Z")
    attendee_email: str = Field(default="", description="Email do convidado/lead")
    description: str = Field(default="", description="Descrição / agenda do evento")
    duration_min: int = Field(default=30, ge=5, le=480, description="Duração em minutos (5-480)")


def _parse_iso(dt_str: str) -> datetime:
    """Parse ISO-8601 robusto; fallback para fromisoformat com Z handling."""
    s = dt_str.strip()
    # normaliza Z -> +00:00
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # tenta dateutil se disponível
        try:
            from dateutil.parser import isoparse  # type: ignore

            dt = isoparse(dt_str)
        except Exception as e:
            raise ValueError(f"datetime_iso inválido: {dt_str}: {e}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class CalendarTool(BaseTool):
    name = "calendar_create_event"
    description = "Cria evento no Google Calendar (service account) ou webhook Calendly; fallback mock em Organization.extra_data"
    input_model = CalendarCreateEventInput

    async def run(
        self,
        title: str,
        datetime_iso: str,
        attendee_email: str = "",
        description: str = "",
        duration_min: int = 30,
    ) -> dict:
        # --- validação e cálculo de start/end ---
        if not title or not title.strip():
            return {"ok": False, "error": "title obrigatório"}
        if not datetime_iso or not datetime_iso.strip():
            return {"ok": False, "error": "datetime_iso obrigatório"}
        try:
            start_dt = _parse_iso(datetime_iso)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        try:
            duration_min = int(duration_min) if duration_min else 30
        except Exception:
            duration_min = 30
        duration_min = max(5, min(480, duration_min))
        end_dt = start_dt + timedelta(minutes=duration_min)

        # normaliza para ISO com offset
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        # --- resolve settings/env ---
        google_creds_raw = ""
        webhook_url = ""
        calendar_id = "primary"
        try:
            from aios.config import settings

            google_creds_raw = getattr(settings, "google_calendar_credentials", "") or ""
            webhook_url = getattr(settings, "calendar_webhook_url", "") or ""
            # calendar_id opcional se alguém adicionar no futuro
            calendar_id = getattr(settings, "google_calendar_id", "") or calendar_id
        except Exception:
            pass

        # env overrides (permite AIOS_ prefix e puro)
        google_creds_raw = (
            os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
            or os.getenv("AIOS_GOOGLE_CALENDAR_CREDENTIALS")
            or google_creds_raw
        ) or ""
        webhook_url = (
            os.getenv("CALENDAR_WEBHOOK_URL")
            or os.getenv("AIOS_CALENDAR_WEBHOOK_URL")
            or webhook_url
        ) or ""
        calendar_id = (
            os.getenv("GOOGLE_CALENDAR_ID")
            or os.getenv("AIOS_GOOGLE_CALENDAR_ID")
            or calendar_id
        ) or "primary"

        # --- 1) Google Calendar via service account ---
        if google_creds_raw and google_creds_raw.strip():
            try:
                # import opcional com fallback
                try:
                    from google.oauth2.service_account import Credentials  # type: ignore
                    from googleapiclient.discovery import build  # type: ignore
                except ImportError as ie:
                    logger.warning("google-api-python-client não instalado, skip Google Calendar: %s", ie)
                    raise ImportError("google libs ausentes") from ie

                # resolve creds: JSON inline ou path
                creds_info: dict | None = None
                raw = google_creds_raw.strip()
                if raw.startswith("{"):
                    creds_info = json.loads(raw)
                elif os.path.isfile(raw):
                    with open(raw, "r", encoding="utf-8") as f:
                        creds_info = json.load(f)
                else:
                    # tenta decodificar mesmo se não começa com { (ex: base64?)
                    try:
                        creds_info = json.loads(raw)
                    except Exception:
                        logger.warning("GOOGLE_CALENDAR_CREDENTIALS não é JSON nem path válido")
                        raise

                if not creds_info:
                    raise ValueError("creds vazias")

                scopes = ["https://www.googleapis.com/auth/calendar"]
                creds = Credentials.from_service_account_info(creds_info, scopes=scopes)

                event_body: dict = {
                    "summary": title.strip(),
                    "description": (description or "")[:2000],
                    "start": {"dateTime": start_iso},
                    "end": {"dateTime": end_iso},
                }
                if attendee_email and "@" in attendee_email:
                    event_body["attendees"] = [{"email": attendee_email.strip()}]

                # googleapiclient é blocking — roda em thread se possível
                import asyncio

                def _insert():
                    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
                    return svc.events().insert(calendarId=calendar_id, body=event_body, sendUpdates="all").execute()

                try:
                    created = await asyncio.to_thread(_insert)
                except TypeError:
                    # fallback se to_thread não disponível (py <3.9) ou sync
                    created = _insert()

                html_link = created.get("htmlLink") or f"https://calendar.google.com/calendar/event?eid={created.get('id','')}"
                return {
                    "ok": True,
                    "provider": "google_calendar",
                    "event_id": created.get("id"),
                    "event_link": html_link,
                    "title": title,
                    "start": start_iso,
                    "end": end_iso,
                    "attendee_email": attendee_email,
                    "calendar_id": calendar_id,
                    "raw": created,
                }
            except ImportError:
                # libs ausentes — cai para webhook/mock sem erro fatal
                pass
            except Exception as e:
                logger.warning("Google Calendar create falhou, tentando webhook/mock: %s", e)
                # se erro foi de creds/libs, tenta próximos; se for erro de API com webhook configurado, ainda tenta webhook
                # não retorna erro ainda — continua

        # --- 2) Webhook Calendly genérico via httpx ---
        if webhook_url and webhook_url.strip():
            payload = {
                "event": "calendar_create",
                "payload": {
                    "title": title.strip(),
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "attendee_email": attendee_email.strip() if attendee_email else "",
                    "description": (description or "")[:2000],
                    "duration_min": duration_min,
                },
            }
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(webhook_url.strip(), json=payload)
                    if r.status_code < 300:
                        try:
                            j = r.json()
                        except Exception:
                            j = None
                        # tenta extrair link do webhook response
                        link = None
                        if isinstance(j, dict):
                            link = j.get("event_link") or j.get("htmlLink") or j.get("url") or j.get("link")
                        return {
                            "ok": True,
                            "provider": "webhook",
                            "status": r.status_code,
                            "event_link": link or f"{webhook_url.strip()}#mock_{uuid.uuid4().hex[:8]}",
                            "title": title,
                            "start": start_iso,
                            "end": end_iso,
                            "attendee_email": attendee_email,
                            "response": j if isinstance(j, dict) else r.text[:2000],
                        }
                    logger.warning("Calendar webhook falhou %s %s", r.status_code, r.text[:500])
                    # se webhook configurado mas falhou, ainda cai para mock em vez de erro duro
            except Exception as e:
                logger.warning("Calendar webhook error %s", e)

        # --- 3) Fallback mock: persiste em Organization.extra_data + Memory ---
        event_id = f"mock_{uuid.uuid4().hex[:12]}"
        event_link = f"https://calendar.mock/{event_id}"
        mock_event = {
            "id": event_id,
            "title": title.strip(),
            "start": start_iso,
            "end": end_iso,
            "attendee_email": attendee_email.strip() if attendee_email else "",
            "description": (description or "")[:2000],
            "duration_min": duration_min,
            "provider": "mock",
            "event_link": event_link,
            "calendar_id": calendar_id,
        }

        # tenta persistir em Organization.extra_data["calendar_mock_events"]
        try:
            from aios.db.engine import async_session
            from sqlalchemy import select
            from aios.db.models import Organization

            async with async_session() as s:
                org = (await s.execute(select(Organization).limit(1))).scalars().first()
                if org is not None:
                    extra = dict(org.extra_data or {})
                    events = list(extra.get("calendar_mock_events") or [])
                    events.append(mock_event)
                    # mantém últimos 50
                    extra["calendar_mock_events"] = events[-50:]
                    org.extra_data = extra
                    await s.commit()
        except Exception as e:
            logger.debug("mock persist Organization falhou (ok, segue): %s", e)

        # tenta também criar Memory se houver Agent (best-effort)
        try:
            from aios.db.engine import async_session as _sess2
            from sqlalchemy import select as _sel
            from aios.db.models import Agent, Memory

            async with _sess2() as s2:
                ag = (await s2.execute(_sel(Agent).limit(1))).scalars().first()
                if ag is not None:
                    mem = Memory(
                        agent_id=ag.id,
                        org_id=ag.org_id,
                        type="calendar_event",
                        content=f"[calendar mock] {title} @ {start_iso} -> {end_iso} attendee={attendee_email}",
                        extra_data=mock_event,
                    )
                    s2.add(mem)
                    await s2.commit()
        except Exception as e:
            logger.debug("mock Memory persist falhou (ok): %s", e)

        return {
            "ok": True,
            "provider": "mock",
            "event_id": event_id,
            "event_link": event_link,
            "title": title,
            "start": start_iso,
            "end": end_iso,
            "attendee_email": attendee_email,
            "duration_min": duration_min,
            "description": description,
            "mock_event": mock_event,
        }


TOOL_REGISTRY["calendar_create_event"] = {"code_reference": "aios.tools.calendar.CalendarTool"}
