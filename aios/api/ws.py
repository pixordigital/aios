"""WebSocket endpoint for real-time web chat.

Handles incoming messages from web clients → dispatches to ARQ worker.
Outbound replies pushed back via WebSocket.
"""

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import Agent, ChannelConnection, Conversation, Message, Team, User
from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def _auth_ws(websocket: WebSocket):
    """Resolve the user from the ``?token=`` query param, or None.

    WebSockets cannot rely on the ``aios_token`` cookie the dashboard uses, so
    the dashboard page injects a short-lived JWT into the connect URL.
    """
    token = websocket.query_params.get("token", "")
    if not token:
        return None
    import jwt as _jwt

    try:
        payload = _jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        user_id = payload.get("sub")
        if not user_id:
            return None
        async with db_session() as db:
            return await db.get(User, user_id)
    except Exception:
        return None


@router.websocket("/ws/agents")
async def websocket_agents(websocket: WebSocket):
    """Live agent-activity feed for the canvas.

    Read-only: the canvas never sends commands, it only receives events. The
    org is fixed at connect time and every event is filtered against it in
    WSManager._deliver_local, so one tenant's canvas can never observe
    another's agent output.
    """
    # Module-path import, not `from aios.core import ...`: aios/core has no
    # __init__.py, so it is a namespace package and the latter form only
    # resolves when something else already imported the submodule.
    import aios.core.agent_events as agent_events
    from aios.core.ws_manager import ws_manager

    await websocket.accept()

    user = await _auth_ws(websocket)
    if not user:
        await websocket.send_json({"type": "error", "error": "Not authenticated"})
        await websocket.close()
        return

    org_id = user.org_id
    ws_manager.register(websocket, org_id)
    try:
        # cross_process tells the canvas whether runs raised in the ARQ worker
        # (channel webhooks, cron, workflows) can be seen at all. When false the
        # UI says so rather than showing a quietly incomplete picture.
        await websocket.send_json(
            {
                "type": "hello",
                "org_id": org_id,
                "cross_process": bool(agent_events.CROSS_PROCESS),
            }
        )
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        logger.debug("Agent canvas disconnected (org %s)", org_id)
    except Exception as e:
        logger.exception("Agent canvas socket error")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        ws_manager.unregister(websocket, org_id)


@router.websocket("/ws/workflows/{run_id}")
async def websocket_workflow(websocket: WebSocket, run_id: str):
    await websocket.accept()
    user = await _auth_ws(websocket)
    if not user:
        await websocket.send_json({"type": "error", "error": "Not authenticated"})
        await websocket.close()
        return
    from aios.db.models import WorkflowRun

    try:
        while True:
            async with db_session() as db:
                run = await db.get(WorkflowRun, run_id)
                if not run or run.org_id != user.org_id:
                    await websocket.send_json(
                        {"type": "error", "error": "run not found"}
                    )
                    break
                await websocket.send_json(
                    {
                        "type": "progress",
                        "run_id": run.id,
                        "status": run.status,
                        "node_status": run.node_status,
                        "outputs": run.outputs,
                        "error": run.error,
                    }
                )
                if run.status in ("done", "failed"):
                    break
            await __import__("asyncio").sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/{channel_connection_id}")
async def websocket_chat(websocket: WebSocket, channel_connection_id: str):
    """WebSocket endpoint for web channel chat.

    Client connects, sends messages, receives agent replies in real-time.
    """
    await websocket.accept()

    # authenticate via query param token
    user = await _auth_ws(websocket)

    if not user:
        await websocket.send_json({"type": "error", "error": "Not authenticated"})
        await websocket.close()
        return

    # find channel connection
    async with db_session() as db:
        conn = await db.get(ChannelConnection, channel_connection_id)
        if not conn or conn.org_id != user.org_id:
            await websocket.send_json({"type": "error", "error": "Channel not found"})
            await websocket.close()
            return

        # find or create conversation for this user
        conv = (
            (
                await db.execute(
                    select(Conversation)
                    .where(
                        Conversation.channel == "web",
                        Conversation.channel_connection_id == channel_connection_id,
                        Conversation.org_id == user.org_id,
                    )
                    .order_by(Conversation.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

        if not conv:
            conv = Conversation(
                org_id=user.org_id,
                channel="web",
                channel_connection_id=channel_connection_id,
                agent_id=conn.agent_id,
                team_id=conn.team_id,
                extra_data={"user_id": user.id},
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)

    await websocket.send_json({"type": "connected", "conversation_id": conv.id})

    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "").strip()
            if not text:
                continue

            # save inbound message
            async with db_session() as db:
                msg = Message(
                    conversation_id=conv.id,
                    org_id=user.org_id,
                    role="user",
                    content=text,
                    extra_data={"user_id": user.id},
                )
                db.add(msg)
                await db.commit()

            # dispatch to ARQ worker for async processing
            from aios.core.dispatch import dispatch_inbound

            await dispatch_inbound(
                channel_type="web",
                channel_connection_id=channel_connection_id,
                conversation_id=conv.id,
                text=text,
                user_id=user.id,
                extra_data={"user_id": user.id, "source": "websocket"},
            )

            await websocket.send_json({"type": "ack", "conversation_id": conv.id})

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for conversation %s", conv.id)
    except Exception as e:
        logger.exception("WebSocket error for conversation %s", conv.id)
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
