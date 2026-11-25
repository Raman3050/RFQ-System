"""Concurrent-bidding load test, run against a full stack (through Nginx).

Creates a buyer, N suppliers and M live British Auctions where *every* bid lands inside
the trigger window (so each bid also takes the extension path), then:

- fires paced bids from every supplier on every auction concurrently (pacing keeps each
  supplier under the per-RFQ rate limit, so we measure the engine, not the limiter);
- keeps V WebSocket viewers subscribed and measures push delivery lag;
- afterwards verifies the auction invariants straight from the database.

Usage (inside the prod compose network):  make loadtest  [ARGS="--suppliers 100"]
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import func, select, text
from websockets.asyncio.client import connect

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import create_engine, create_sessionmaker
from app.domain.bidding import Quote, rank
from app.models import AuctionConfig, AuctionEvent, Bid, Rfq, RfqInvitation, RfqStatus, User
from app.models.rfq import TriggerType
from app.models.user import UserRole


@dataclass
class Results:
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter[int] = field(default_factory=Counter)
    ws_messages: Counter[str] = field(default_factory=Counter)
    ws_lag_ms: list[float] = field(default_factory=list)


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


async def setup(args: argparse.Namespace) -> tuple[list[str], list[str], str, str]:
    settings = get_settings()
    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    run = uuid.uuid4().hex[:6]
    password_hash = hash_password("LoadTest123")  # one hash: argon2 is deliberately slow
    async with sm() as s:
        buyer = User(
            email=f"lt-buyer-{run}@loadtest.example.com",
            password_hash=password_hash,
            full_name="Load Test Buyer",
            company_name=f"LoadTest {run}",
            role=UserRole.BUYER,
        )
        suppliers = [
            User(
                email=f"lt-s{i}-{run}@loadtest.example.com",
                password_hash=password_hash,
                full_name=f"Supplier {i}",
                company_name=f"Carrier {i} ({run})",
                role=UserRole.SUPPLIER,
            )
            for i in range(args.suppliers)
        ]
        s.add_all([buyer, *suppliers])
        await s.flush()

        now = (await s.execute(text("SELECT clock_timestamp()"))).scalar_one()
        rfqs = []
        for i in range(args.rfqs):
            rfq = Rfq(
                reference_id=f"LT-{run}-{i:02d}",
                name=f"Load test {run} #{i}",
                buyer_id=buyer.id,
                is_british_auction=True,
                bid_start_at=now - timedelta(minutes=1),
                bid_close_at=now + timedelta(minutes=3),
                current_close_at=now + timedelta(minutes=3),
                forced_close_at=now + timedelta(minutes=args.forced_minutes),
                pickup_date=(now + timedelta(days=3)).date(),
                status=RfqStatus.ACTIVE,
                # X covers the whole run, so every bid is "in the window" and extends.
                config=AuctionConfig(
                    trigger_window_minutes=10,
                    extension_minutes=1,
                    trigger_type=TriggerType.BID_RECEIVED,
                ),
            )
            s.add(rfq)
            rfqs.append(rfq)
        await s.flush()
        for rfq in rfqs:
            for sup in suppliers:
                s.add(
                    RfqInvitation(
                        rfq_id=rfq.id,
                        invitee_email=sup.email,
                        supplier_id=sup.id,
                        invited_by=buyer.id,
                    )
                )
        await s.commit()
    await engine.dispose()

    tokens = [
        create_access_token(settings, user_id=sup.id, role="SUPPLIER")[0] for sup in suppliers
    ]
    buyer_token = create_access_token(settings, user_id=buyer.id, role="BUYER")[0]
    return [str(r.id) for r in rfqs], tokens, buyer_token, run


async def bidder(
    client: httpx.AsyncClient,
    rfq_id: str,
    token: str,
    bids: int,
    validity: str,
    results: Results,
) -> None:
    total = Decimal(random.randint(100_000, 120_000))
    headers = {"Authorization": f"Bearer {token}"}
    await asyncio.sleep(random.uniform(0, 2))  # stagger start
    for _ in range(bids):
        total -= Decimal(random.randint(50, 500))
        body = {
            "carrier_name": "Load Test Carrier",
            "freight_charges": str(total),
            "origin_charges": "0",
            "destination_charges": "0",
            "transit_time_days": 3,
            "quote_validity_until": validity,
        }
        started = time.perf_counter()
        resp = await client.post(
            f"/api/v1/rfqs/{rfq_id}/bids",
            json=body,
            headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
        )
        results.latencies_ms.append((time.perf_counter() - started) * 1000)
        results.statuses[resp.status_code] += 1
        await asyncio.sleep(random.uniform(2.0, 3.0))  # ≤ 30 bids/min per supplier+RFQ


async def viewer(
    ws_url: str, token: str, rfq_ids: list[str], results: Results, stop: asyncio.Event
) -> None:
    async with connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        await ws.send(json.dumps({"type": "subscribe", "rfq_ids": rfq_ids}))
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except TimeoutError:
                continue
            msg = json.loads(raw)
            results.ws_messages[msg["type"]] += 1
            if msg["type"] in ("BID_SUBMITTED", "TIME_EXTENDED") and msg.get("server_time"):
                sent = datetime.fromisoformat(msg["server_time"].replace("Z", "+00:00"))
                results.ws_lag_ms.append((datetime.now(UTC) - sent).total_seconds() * 1000)


async def verify(rfq_ids: list[str]) -> list[str]:
    """Re-check the auction invariants from the database."""
    settings = get_settings()
    engine = create_engine(settings)
    problems: list[str] = []
    async with create_sessionmaker(engine)() as s:
        for rid in rfq_ids:
            rfq = await s.get(Rfq, uuid.UUID(rid))
            assert rfq is not None
            if rfq.current_close_at > rfq.forced_close_at:
                problems.append(f"{rfq.reference_id}: close past forced close")
            extensions = (
                await s.execute(
                    select(func.count()).where(
                        AuctionEvent.rfq_id == rfq.id, AuctionEvent.event_type == "TIME_EXTENDED"
                    )
                )
            ).scalar_one()
            if extensions != rfq.extension_count:
                problems.append(
                    f"{rfq.reference_id}: {extensions} extension events vs "
                    f"extension_count={rfq.extension_count}"
                )
            latest = (
                await s.execute(
                    select(Bid.supplier_id, Bid.id, Bid.total_amount, Bid.created_at)
                    .where(Bid.rfq_id == rfq.id)
                    .order_by(Bid.supplier_id, Bid.created_at.desc())
                )
            ).all()
            seen: dict[uuid.UUID, Quote] = {}
            for sid, bid_id, total, created in latest:
                seen.setdefault(sid, Quote(sid, bid_id, total, created))
            ranked = rank(list(seen.values()))
            if ranked and rfq.current_l1_amount != ranked[0].total:
                problems.append(f"{rfq.reference_id}: stored L1 != true L1")
            bids = (await s.execute(select(func.count()).where(Bid.rfq_id == rfq.id))).scalar_one()
            logged = (
                await s.execute(
                    select(func.count()).where(
                        AuctionEvent.rfq_id == rfq.id, AuctionEvent.event_type == "BID_SUBMITTED"
                    )
                )
            ).scalar_one()
            if bids != logged:
                problems.append(f"{rfq.reference_id}: {bids} bids vs {logged} log entries")
    await engine.dispose()
    return problems


async def main(args: argparse.Namespace) -> int:
    print(
        f"Setting up {args.suppliers} suppliers x {args.rfqs} live auctions "
        f"x {args.bids} bids each, {args.viewers} WebSocket viewers…"
    )
    rfq_ids, tokens, buyer_token, run = await setup(args)
    results = Results()
    validity = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
    ws_url = args.base_url.replace("http", "ws", 1) + "/ws"

    stop = asyncio.Event()
    viewers = [
        asyncio.create_task(viewer(ws_url, buyer_token, rfq_ids, results, stop))
        for _ in range(args.viewers)
    ]
    await asyncio.sleep(1)  # let viewers subscribe

    limits = httpx.Limits(max_connections=args.suppliers * args.rfqs, max_keepalive_connections=100)
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30, limits=limits) as client:
        await asyncio.gather(
            *(
                bidder(client, rid, tok, args.bids, validity, results)
                for rid in rfq_ids
                for tok in tokens
            )
        )
    elapsed = time.perf_counter() - started
    await asyncio.sleep(1)  # drain last pushes
    stop.set()
    await asyncio.gather(*viewers, return_exceptions=True)

    problems = await verify(rfq_ids)
    lat = results.latencies_ms
    summary = {
        "run": run,
        "suppliers": args.suppliers,
        "auctions": args.rfqs,
        "ws_viewers": args.viewers,
        "bids_sent": len(lat),
        "duration_s": round(elapsed, 1),
        "throughput_bids_per_s": round(len(lat) / elapsed, 1),
        "status_codes": dict(results.statuses),
        "latency_ms": {
            "p50": round(pct(lat, 50), 1),
            "p95": round(pct(lat, 95), 1),
            "p99": round(pct(lat, 99), 1),
            "max": round(max(lat), 1) if lat else 0,
            "mean": round(statistics.fmean(lat), 1) if lat else 0,
        },
        "ws_messages_by_type": dict(results.ws_messages),
        "ws_push_lag_ms": {
            "p50": round(pct(results.ws_lag_ms, 50), 1),
            "p95": round(pct(results.ws_lag_ms, 95), 1),
        },
        "invariants": problems if problems else "OK",
    }
    print(json.dumps(summary, indent=2))
    return 0 if not problems and set(results.statuses) == {201} else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8088")
    parser.add_argument("--suppliers", type=int, default=60)
    parser.add_argument("--rfqs", type=int, default=3)
    parser.add_argument("--bids", type=int, default=6, help="bids per supplier per auction")
    parser.add_argument("--viewers", type=int, default=20)
    parser.add_argument("--forced-minutes", type=int, default=30)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
