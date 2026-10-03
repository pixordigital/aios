"""WebSocket endpoint for real-time web chat.

Handles incoming messages from web clients → dispatches to ARQ worker.
Outbound replies pushed back via WebSocket.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import ChannelConnection, Conversation, Message, User

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
    # Route through the shared verifier, not a direct decode: the direct
    # HS256-only decode ignored EdDSA-signed cookies entirely AND never
    # checked the token type, so a stolen refresh token (30-day lifetime)
    # authenticated a socket exactly like a 60-minute access token.
    from aios.api.auth import _is_login_allowed, _verify_jwt_token

    try:
        payload = _verify_jwt_token(token)
        if not payload or payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        async with db_session() as db:
            user = await db.get(User, user_id)
            if not user or not _is_login_allowed(user.email):
                return None
            return user
    except Exception:
        return None


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """Web-chat channel socket.

    Nothing registered into `WebChannel._connections` and nothing called its
    `handle_incoming`, so the web channel had no live transport at all: inbound
    never reached an agent and outbound had nowhere to go.

    `?conversation=<id>` pins the thread. Registered in BOTH the channel's own
    map (so a same-process send can target this socket directly) and the shared
    ws_manager (so a reply produced in the ARQ worker reaches this process over
    the agent-events Redis bridge).
    """
    await websocket.accept()

    user = await _auth_ws(websocket)
    if not user:
        await websocket.send_json({"type": "error", "error": "Not authenticated"})
        await websocket.close()
        return

    from aios.channels.web import WebChannel
    from aios.core.ws_manager import ws_manager

    conversation_id = websocket.query_params.get("conversation", "") or ""
    connection_id = websocket.query_params.get("connection", "") or ""
    if not conversation_id:
        await websocket.send_json({"type": "error", "error": "missing conversation"})
        await websocket.close()
        return

    org_id = user.org_id
    ws_manager.register(websocket, org_id)
    WebChannel.attach(websocket, conversation_id)
    try:
        await websocket.send_json({"type": "ready", "conversation_id": conversation_id})
        while True:
            raw = await websocket.receive()
            if raw.get("type") == "websocket.disconnect":
                break
            if raw.get("type") == "websocket.receive":
                try:
                    data = raw.get("json") or {}
                except Exception:
                    data = {}
                text = (data.get("text") or "").strip()
                if text:
                    await WebChannel.handle_incoming(
                        websocket, conversation_id, text, connection_id
                    )
    except WebSocketDisconnect:
        logger.debug("web chat disconnected (conversation %s)", conversation_id)
    except Exception:
        logger.exception("web chat socket error")
        try:
            await websocket.send_json({"type": "error", "error": "internal"})
        except Exception:
            pass
    finally:
        WebChannel.detach(websocket, conversation_id)
        ws_manager.unregister(websocket, org_id)


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
async def websocket_channel_chat(websocket: WebSocket, channel_connection_id: str):
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
