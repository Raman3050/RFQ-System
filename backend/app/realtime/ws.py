"""WebSocket endpoint: /ws

Protocol (JSON text frames):

    client → {"type": "auth", "token": "<access token>"}          must be first, within 5 s
    server → {"type": "READY", "server_time": "..."}
    client → {"type": "subscribe", "rfq_ids": ["...", ...]}
    server → {"type": "SUBSCRIBED", "rfq_ids": [...], "rejected": [...]}
    server → {"type": "SNAPSHOT", "rfq_id": ..., "seq": ..., "auction": {...}}   per RFQ
    server → {"type": "BID_SUBMITTED" | "TIME_EXTENDED" | "AUCTION_STARTED" |
              "AUCTION_CLOSED" | "AUCTION_FORCE_CLOSED" | "RFQ_UPDATED" |
              "RFQ_CANCELLED", ...}                                  as things happen
    client → {"type": "unsubscribe", "rfq_ids": [...]}
    server → {"type": "PING"} every 25 s (keep-alive)

The token goes in the first message rather than the URL so it never lands in access logs.
The socket is closed with 4401 when the access token expires; the client refreshes its
token and reconnects. Subscriptions are access-checked exactly like GET /rfqs/{id}.
"""

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import InvalidTokenError, decode_access_token
from app.models.user import User
from app.realtime.manager import Connection, ConnectionManager
from app.realtime.messages import auction_message, iso
from app.repositories.event_repo import EventRepository
from app.repositories.rfq_repo import RfqRepository
from app.repositories.user_repo import UserRepository

router = APIRouter()
log = get_logger(__name__)

CLOSE_UNAUTHORIZED = 4401
CLOSE_POLICY = 1008
CLOSE_TRY_AGAIN = 1013


class _RejectError(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _dump(message: dict[str, Any]) -> str:
    return json.dumps(message)


async def _authenticate(
    ws: WebSocket, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> tuple[User, datetime]:
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=settings.ws_auth_timeout_seconds)
    except (TimeoutError, ValueError) as exc:
        raise _RejectError(CLOSE_UNAUTHORIZED, "auth required") from exc
    if not isinstance(first, dict) or first.get("type") != "auth":
        raise _RejectError(CLOSE_UNAUTHORIZED, "auth required")
    try:
        claims = decode_access_token(settings, str(first.get("token", "")))
    except InvalidTokenError as exc:
        raise _RejectError(CLOSE_UNAUTHORIZED, f"token {exc.reason}") from exc
    async with sessionmaker() as session:
        user = await UserRepository(session).get(claims.user_id)
    if user is None or not user.is_active:
        raise _RejectError(CLOSE_UNAUTHORIZED, "account disabled")
    return user, claims.expires_at


async def _subscribe(
    ids: list[Any],
    user: User,
    conn: Connection,
    manager: ConnectionManager,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    accepted: list[str] = []
    rejected: list[str] = []
    snapshots: list[dict[str, Any]] = []
    async with sessionmaker() as session:
        rfqs = RfqRepository(session)
        events = EventRepository(session)
        now = datetime.now(UTC)
        for raw in ids:
            try:
                rfq_id = uuid.UUID(str(raw))
            except ValueError:
                rejected.append(str(raw))
                continue
            key = str(rfq_id)
            if key in conn.rfq_ids:
                accepted.append(key)
                continue
            if len(conn.rfq_ids) >= settings.ws_max_subscriptions:
                rejected.append(key)
                continue
            row = await rfqs.get_visible(rfq_id, user)
            if row is None:
                rejected.append(key)  # not found and not allowed look the same
                continue
            manager.subscribe(conn, key)
            accepted.append(key)
            snapshots.append(
                auction_message("SNAPSHOT", row.rfq, seq=await events.latest_id(rfq_id), now=now)
            )
    conn.offer(_dump({"type": "SUBSCRIBED", "rfq_ids": accepted, "rejected": rejected}))
    for snap in snapshots:
        conn.offer(_dump(snap))


async def _reader(
    ws: WebSocket,
    user: User,
    conn: Connection,
    manager: ConnectionManager,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    while True:
        try:
            msg = await ws.receive_json()
        except WebSocketDisconnect:
            return
        except ValueError:
            conn.offer(_dump({"type": "ERROR", "detail": "invalid JSON"}))
            continue
        kind = msg.get("type") if isinstance(msg, dict) else None
        ids = msg.get("rfq_ids") if isinstance(msg, dict) else None
        if kind == "subscribe" and isinstance(ids, list):
            await _subscribe(ids, user, conn, manager, settings, sessionmaker)
        elif kind == "unsubscribe" and isinstance(ids, list):
            for rfq_id in ids:
                manager.unsubscribe(conn, str(rfq_id))
        elif kind == "ping":
            conn.offer(_dump({"type": "PONG", "server_time": iso(datetime.now(UTC))}))
        else:
            conn.offer(_dump({"type": "ERROR", "detail": "unknown message"}))


async def _writer(ws: WebSocket, conn: Connection, ping_seconds: float) -> None:
    while not conn.overflowed:
        try:
            raw = await asyncio.wait_for(conn.queue.get(), timeout=ping_seconds)
        except TimeoutError:
            raw = _dump({"type": "PING", "server_time": iso(datetime.now(UTC))})
        await ws.send_text(raw)


@router.websocket("/ws")
async def auction_socket(ws: WebSocket) -> None:
    settings: Settings = ws.app.state.settings
    sessionmaker: async_sessionmaker[AsyncSession] = ws.app.state.sessionmaker
    manager: ConnectionManager = ws.app.state.ws_manager

    await ws.accept()
    try:
        user, expires_at = await _authenticate(ws, settings, sessionmaker)
    except _RejectError as reject:
        await ws.close(code=reject.code, reason=reject.reason)
        return
    except WebSocketDisconnect:
        return

    conn = Connection(user.id)
    conn.offer(_dump({"type": "READY", "server_time": iso(datetime.now(UTC))}))
    ttl = max(0.0, (expires_at - datetime.now(UTC)).total_seconds())
    tasks = {
        asyncio.create_task(_reader(ws, user, conn, manager, settings, sessionmaker)),
        asyncio.create_task(_writer(ws, conn, settings.ws_ping_seconds)),
    }
    expiry = asyncio.create_task(asyncio.sleep(ttl))
    try:
        done, _ = await asyncio.wait({*tasks, expiry}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (*tasks, expiry):
            task.cancel()
        manager.remove(conn)

    with contextlib.suppress(Exception):
        if expiry in done:
            await ws.close(code=CLOSE_UNAUTHORIZED, reason="token expired")
        elif conn.overflowed:
            await ws.close(code=CLOSE_TRY_AGAIN, reason="client too slow")
        else:
            await ws.close()
