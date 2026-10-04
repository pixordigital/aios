"""Google Calendar tools: create, availability, list.

All three need the same thing: a service-account JSON with Calendar scope,
via GOOGLE_CALENDAR_CREDENTIALS / AIOS_GOOGLE_CALENDAR_CREDENTIALS
(inline JSON or path) or settings.google_calendar_credentials.

Without it every tool fails closed with "not configured". An earlier version
returned ok:true with a fake calendar.mock link when unconfigured — the agent
told users a meeting was booked and nothing happened. That path is deleted,
including the mock persistence that wrote to whichever org sorted first.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "Google Calendar não configurado: defina GOOGLE_CALENDAR_CREDENTIALS "
    "(service account JSON) e compartilhe o calendário com o email da conta."
)


async def _resolve_google(org_id: str = "") -> tuple[dict | None, str, str]:
    """Return (creds_info, calendar_id, error). Error is "" on success.

    The tenant's credential is stored per-org (org_settings.ALLOWED_KEYS holds
    google_calendar_credentials / google_calendar_id, and the dashboard writes
    them), but this only ever read env and instance settings — so a self-serve
    tenant that completed Calendar setup in the dashboard got
    "not configured" from all three calendar tools, forever.
    """
    raw = ""
    calendar_id = "primary"
    if org_id:
        try:
            from aios.core.org_settings import get_org_secret_async

            raw = (await get_org_secret_async(org_id, "google_calendar_credentials")) or ""
            calendar_id = (await get_org_secret_async(org_id, "google_calendar_id")) or "primary"
        except Exception:
            logger.debug("per-org Google Calendar lookup failed", exc_info=True)
    if not raw:
        raw = (
            os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
            or os.getenv("AIOS_GOOGLE_CALENDAR_CREDENTIALS")
            or ""
        )
    if not calendar_id or calendar_id == "primary":
        calendar_id = (
            os.getenv("GOOGLE_CALENDAR_ID")
            or os.getenv("AIOS_GOOGLE_CALENDAR_ID")
            or "primary"
        )
    if not raw:
        try:
            from aios.config import settings

            raw = getattr(settings, "google_calendar_credentials", "") or ""
            if not calendar_id or calendar_id == "primary":
                calendar_id = getattr(settings, "google_calendar_id", "") or calendar_id
        except Exception:
            pass
    raw = (raw or "").strip()
    if not raw:
        return None, calendar_id, NOT_CONFIGURED
    try:
        info = json.loads(raw) if raw.startswith("{") else None
        if info is None and os.path.isfile(raw):
            with open(raw, "r", encoding="utf-8") as f:
                info = json.load(f)
        if not info or "client_email" not in info:
            return None, calendar_id, "credencial inválida: JSON sem client_email"
        return info, calendar_id, ""
    except Exception as e:
        return None, calendar_id, f"credencial inválida: {e}"


def _service(creds_info: dict):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_info(
        creds_info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_iso(dt_str: str) -> datetime:
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        from dateutil.parser import isoparse  # type: ignore

        dt = isoparse(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class CalendarCreateEventInput(BaseModel):
    title: str = Field(description="Título do evento")
    datetime_iso: str = Field(description="Início ISO-8601 ex: 2026-09-15T14:00:00-03:00")
    attendee_email: str = Field(default="", description="Email do convidado")
    description: str = Field(default="", description="Agenda do evento")
    duration_min: int = Field(default=30, ge=5, le=480, description="Duração em minutos")


class CalendarTool(BaseTool):
    name = "calendar_create_event"
    description = "Cria evento no Google Calendar. Exige credencial configurada."
    input_model = CalendarCreateEventInput

    async def run(
        self,
        title: str,
        datetime_iso: str,
        attendee_email: str = "",
        description: str = "",
        duration_min: int = 30,
    ) -> dict:
        if not (title or "").strip():
            return {"ok": False, "error": "title obrigatório"}
        try:
            start_dt = _parse_iso(datetime_iso)
        except Exception:
            return {"ok": False, "error": f"datetime_iso inválido: {datetime_iso}"}
        duration_min = max(5, min(480, int(duration_min or 30)))
        end_dt = start_dt + timedelta(minutes=duration_min)

        creds_info, calendar_id, err = await _resolve_google(getattr(self, "_org_id", "") or "")
        if err:
            return {"ok": False, "error": err}
        try:
            body: dict = {
                "summary": title.strip(),
                "description": (description or "")[:2000],
                "start": {"dateTime": start_dt.isoformat()},
                "end": {"dateTime": end_dt.isoformat()},
            }
            if attendee_email and "@" in attendee_email:
                body["attendees"] = [{"email": attendee_email.strip()}]

            def _insert():
                return (
                    _service(creds_info)
                    .events()
                    .insert(calendarId=calendar_id, body=body, sendUpdates="all")
                    .execute()
                )

            # A deadline, because to_thread without one parks the worker forever
            # on a hung Google call and the job hits ARQ's timeout instead of
            # failing fast with a message the agent can act on.
            created = await asyncio.wait_for(asyncio.to_thread(_insert), timeout=60)
            return {
                "ok": True,
                "provider": "google_calendar",
                "event_id": created.get("id"),
                "event_link": created.get("htmlLink", ""),
                "title": title.strip(),
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "attendee_email": attendee_email,
            }
        except Exception as e:
            logger.warning("Google Calendar create falhou: %s", e)
            return {"ok": False, "error": f"falha ao criar evento: {e}"}


class CalendarAvailabilityInput(BaseModel):
    date: str = Field(description="Dia YYYY-MM-DD no fuso informado")
    timezone: str = Field(default="America/Sao_Paulo", description="IANA timezone")
    work_start: str = Field(default="08:00", description="Início do expediente HH:MM")
    work_end: str = Field(default="18:00", description="Fim do expediente HH:MM")


class CalendarAvailabilityTool(BaseTool):
    name = "calendar_check_availability"
    description = "Retorna horários ocupados (freebusy) e janelas livres num dia."
    input_model = CalendarAvailabilityInput

    async def run(
        self,
        date: str,
        timezone: str = "America/Sao_Paulo",
        work_start: str = "08:00",
        work_end: str = "18:00",
    ) -> dict:
        creds_info, calendar_id, err = await _resolve_google(getattr(self, "_org_id", "") or "")
        if err:
            return {"ok": False, "error": err}
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(timezone)
            day = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            hs, ms = (work_start or "08:00").split(":")[:2]
            he, me = (work_end or "18:00").split(":")[:2]
            day_start = datetime(day.year, day.month, day.day, int(hs), int(ms), tzinfo=tz)
            day_end = datetime(day.year, day.month, day.day, int(he), int(me), tzinfo=tz)
        except Exception:
            return {"ok": False, "error": f"data/horário inválidos: {date} {work_start}-{work_end}"}
        try:
            def _query():
                return (
                    _service(creds_info)
                    .freebusy()
                    .query(
                        body={
                            "timeMin": day_start.isoformat(),
                            "timeMax": day_end.isoformat(),
                            "timeZone": timezone,
                            "items": [{"id": calendar_id}],
                        }
                    )
                    .execute()
                )

            res = await asyncio.to_thread(_query)
            busy = res.get("calendars", {}).get(calendar_id, {}).get("busy", [])
            slots = [
                {"start": b.get("start", ""), "end": b.get("end", "")} for b in busy
            ]
            # free gaps between busy slots inside the work window
            free = []
            cursor = day_start
            for b in sorted(slots, key=lambda s: s["start"]):
                try:
                    bs = _parse_iso(b["start"])
                    if bs > cursor:
                        free.append({"start": cursor.isoformat(), "end": bs.isoformat()})
                    be = _parse_iso(b["end"])
                    cursor = max(cursor, be)
                except Exception:
                    continue
            if cursor < day_end:
                free.append({"start": cursor.isoformat(), "end": day_end.isoformat()})
            return {"ok": True, "date": date, "busy": slots, "free": free}
        except Exception as e:
            logger.warning("Google Calendar freebusy falhou: %s", e)
            return {"ok": False, "error": f"falha ao consultar disponibilidade: {e}"}


class CalendarListInput(BaseModel):
    time_min: str = Field(default="", description="De (ISO-8601, default agora)")
    time_max: str = Field(default="", description="Até (ISO-8601, default +7 dias)")
    max_results: int = Field(default=20, ge=1, le=100)


class CalendarListTool(BaseTool):
    name = "calendar_list_events"
    description = "Lista eventos do Google Calendar num intervalo."
    input_model = CalendarListInput

    async def run(self, time_min: str = "", time_max: str = "", max_results: int = 20) -> dict:
        creds_info, calendar_id, err = await _resolve_google(getattr(self, "_org_id", "") or "")
        if err:
            return {"ok": False, "error": err}
        try:
            now = datetime.now(timezone.utc)
            tmin = _parse_iso(time_min) if (time_min or "").strip() else now
            tmax = (
                _parse_iso(time_max)
                if (time_max or "").strip()
                else now + timedelta(days=7)
            )
            max_results = max(1, min(100, int(max_results or 20)))
        except Exception:
            return {"ok": False, "error": "intervalo inválido"}
        try:
            def _list():
                return (
                    _service(creds_info)
                    .events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=tmin.isoformat(),
                        timeMax=tmax.isoformat(),
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

            res = await asyncio.to_thread(_list)
            events = [
                {
                    "id": e.get("id", ""),
                    "title": e.get("summary", ""),
                    "start": (e.get("start") or {}).get("dateTime", ""),
                    "end": (e.get("end") or {}).get("dateTime", ""),
                    "link": e.get("htmlLink", ""),
                    "attendees": [a.get("email", "") for a in e.get("attendees", [])],
                }
                for e in res.get("items", [])
            ]
            return {"ok": True, "events": events, "count": len(events)}
        except Exception as e:
            logger.warning("Google Calendar list falhou: %s", e)
            return {"ok": False, "error": f"falha ao listar eventos: {e}"}


TOOL_REGISTRY["calendar_create_event"] = {"code_reference": "aios.tools.calendar.CalendarTool"}
TOOL_REGISTRY["calendar_check_availability"] = {
    "code_reference": "aios.tools.calendar.CalendarAvailabilityTool"
}
TOOL_REGISTRY["calendar_list_events"] = {"code_reference": "aios.tools.calendar.CalendarListTool"}
