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


@router.websocket("/ws/workflows/{run_id}")
async def websocket_workflow(websocket: WebSocket, run_id: str):
    await websocket.accept()
    token = websocket.query_params.get("token", "")
    user = None
    if token:
        import jwt as _jwt

        try:
            payload = _jwt.decode(
                token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            user_id = payload.get("sub")
            if user_id:
                async with db_session() as db:
                    user = await db.get(User, user_id)
        except Exception:
            pass
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
    token = websocket.query_params.get("token", "")
    user = None
    if token:
        import jwt

        try:
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            user_id = payload.get("sub")
            if user_id:
                async with db_session() as db:
                    user = await db.get(User, user_id)
        except jwt.PyJWTError:
            pass

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
