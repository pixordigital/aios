"""Cal.com booking tool — self-hosted scheduling for sales agents.

Actions against the Cal.com API v2 running in this stack (calcom-api
service, pinned v6.2.0): availability slots, create booking, cancel booking,
list event types. Auth is a server-side API key (Settings > Security in the
Cal.com UI); without it every action fails closed with an error, never a
half-booking.

Endpoint versions follow the OpenAPI contract: slots pin cal-api-version
2024-09-04 (required), bookings/event-types use AIOS_CALCOM_API_VERSION.
"""

import logging

import httpx
from pydantic import BaseModel, Field

from aios.config import settings
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

_SLOTS_VERSION = "2024-09-04"  # required by GET /v2/slots per OpenAPI
_TIMEOUT_S = 20.0


class CalBookingInput(BaseModel):
    action: str = Field(description="availability | book | cancel | event_types")
    event_type_id: int = Field(default=0, description="Cal.com event type id (0 = AIOS_CALCOM_EVENT_TYPE_ID)")
    start: str = Field(default="", description="ISO-8601 start (book) ou início da janela (availability)")
    end: str = Field(default="", description="ISO-8601 fim da janela (availability)")
    attendee_name: str = Field(default="", description="Nome do lead (book)")
    attendee_email: str = Field(default="", description="E-mail do lead (book)")
    attendee_timezone: str = Field(default="", description="IANA timezone do lead (book; default AIOS_CALCOM_TIMEZONE)")
    notes: str = Field(default="", description="Observações (book, vai em metadata)")
    booking_uid: str = Field(default="", description="UID da reserva (cancel)")
    cancellation_reason: str = Field(default="", description="Motivo (cancel)")


def _client():
    if not settings.calcom_api_key:
        return None
    return httpx.AsyncClient(
        base_url=settings.calcom_api_url.rstrip("/"),
        timeout=_TIMEOUT_S,
        headers={
            "Authorization": f"Bearer {settings.calcom_api_key}",
            "Content-Type": "application/json",
        },
    )


def _version_for(endpoint: str) -> str:
    if endpoint.startswith("/v2/slots"):
        return _SLOTS_VERSION
    return settings.calcom_api_version or "2024-08-13"


async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    params = {**params, "cal-api-version": _version_for(path)}
    resp = await client.get(path, params=params)
    return {"status": resp.status_code, "data": _safe_json(resp)}


async def _post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    resp = await client.post(
        path, params={"cal-api-version": _version_for(path)}, json=payload
    )
    return {"status": resp.status_code, "data": _safe_json(resp)}


def _safe_json(resp: httpx.Response):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:2000]}


def _ok(res: dict, codes=(200, 201)):
    return res["status"] in codes


class CalBookingTool(BaseTool):
    name = "cal_booking"
    description = (
        "Agendamento via Cal.com self-hosted. availability: horários livres "
        "(event_type_id, start, end ISO). book: agenda (start, attendee_name, "
        "attendee_email). cancel: cancela por booking_uid. event_types: lista "
        "tipos de evento. Sempre confirme data/hora com o lead antes de book."
    )
    input_model = CalBookingInput

    async def run(
        self,
        action: str,
        event_type_id: int = 0,
        start: str = "",
        end: str = "",
        attendee_name: str = "",
        attendee_email: str = "",
        attendee_timezone: str = "",
        notes: str = "",
        booking_uid: str = "",
        cancellation_reason: str = "",
    ) -> dict:
        client = _client()
        if client is None:
            return {"ok": False, "error": "Cal.com não configurado (AIOS_CALCOM_API_KEY). Veja .env.example → Cal.com self-hosted."}
        etype = event_type_id or settings.calcom_event_type_id
        tz = attendee_timezone or settings.calcom_timezone
        try:
            async with client:
                if action == "event_types":
                    res = await _get(client, "/v2/event-types", {})
                    if not _ok(res):
                        return {"ok": False, "error": f"Cal.com {res['status']}", "data": res["data"]}
                    items = res["data"].get("data", res["data"])
                    if isinstance(items, dict):
                        items = items.get("eventTypes", items.get("data", []))
                    return {"ok": True, "event_types": [
                        {"id": e.get("id"), "slug": e.get("slug"), "title": e.get("title"),
                         "length_minutes": e.get("lengthInMinutes")}
                        for e in (items or []) if isinstance(e, dict)
                    ]}

                if action == "availability":
                    if not etype or not start or not end:
                        return {"ok": False, "error": "availability precisa de event_type_id, start e end (ISO-8601)"}
                    res = await _get(client, "/v2/slots", {
                        "eventTypeId": etype, "start": start, "end": end, "timeZone": tz,
                    })
                    if not _ok(res):
                        return {"ok": False, "error": f"Cal.com {res['status']}", "data": res["data"]}
                    return {"ok": True, "slots": res["data"]}

                if action == "book":
                    if not etype or not start or not attendee_name or not attendee_email:
                        return {"ok": False, "error": "book precisa de event_type_id, start, attendee_name e attendee_email"}
                    payload = {
                        "eventTypeId": etype,
                        "start": start,
                        "attendee": {"name": attendee_name, "email": attendee_email, "timeZone": tz},
                        "metadata": {"notes": notes, "source": "aios-sdr"} if notes else {"source": "aios-sdr"},
                    }
                    res = await _post(client, "/v2/bookings", payload)
                    if res["status"] not in (200, 201):
                        return {"ok": False, "error": f"Cal.com {res['status']}", "data": res["data"]}
                    data = res["data"].get("data", res["data"]) if isinstance(res["data"], dict) else {}
                    return {"ok": True, "uid": data.get("uid"),
                            "meeting_url": data.get("meetingUrl") or (data.get("meeting") or {}).get("url") if isinstance(data, dict) else None,
                            "status": data.get("status") if isinstance(data, dict) else None}

                if action == "cancel":
                    if not booking_uid:
                        return {"ok": False, "error": "cancel precisa de booking_uid"}
                    res = await _post(client, f"/v2/bookings/{booking_uid}/cancel",
                                      {"cancellationReason": cancellation_reason or "cancelado pelo SDR"} if cancellation_reason else {})
                    if not _ok(res):
                        return {"ok": False, "error": f"Cal.com {res['status']}", "data": res["data"]}
                    return {"ok": True, "cancelled": booking_uid}

                return {"ok": False, "error": f"ação desconhecida: {action} (availability|book|cancel|event_types)"}
        except Exception as e:
            logger.exception("cal_booking %s failed", action)
            return {"ok": False, "error": f"falha ao falar com Cal.com: {e}"}


TOOL_REGISTRY["cal_booking"] = {
    "code_reference": "aios.tools.cal_booking.CalBookingTool",
}
