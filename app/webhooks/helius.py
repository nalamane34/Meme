"""Inbound Helius webhook handler.

Parses Helius enhanced-tx events into Candidates and hands them to the
shared strategy pipeline. The pipeline does dedupe, safety, features,
policy, and execution — same path discovery uses.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Any

import redis.asyncio as redis_async
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.birdeye import BirdeyeClient
from app.clients.dexscreener import DexScreenerClient
from app.clients.helius import parse_swap_event
from app.clients.rugcheck import RugCheckClient
from app.config import get_settings
from app.db.models import SmartWallet
from app.executor.trader import Trader
from app.logging import get_logger
from app.strategy.pipeline import Candidate, process_candidate
from app.strategy.policy import Policy

log = get_logger(__name__)


def build_router(
    *,
    sessionmaker: async_sessionmaker,
    redis: redis_async.Redis,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> APIRouter:
    router = APIRouter(prefix="/webhooks", tags=["webhooks"])

    @router.post("/helius", status_code=status.HTTP_202_ACCEPTED)
    async def helius_webhook(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        s = get_settings()
        if s.helius_webhook_secret:
            if not authorization or not hmac.compare_digest(authorization, s.helius_webhook_secret):
                raise HTTPException(status_code=401, detail="bad webhook secret")

        events = await request.json()
        if not isinstance(events, list):
            events = [events]

        asyncio.create_task(_process_batch(
            events, sessionmaker, redis, rugcheck, birdeye, dexscreener, policy, trader,
        ))
        return {"received": len(events)}

    return router


async def _process_batch(
    events: list[dict[str, Any]],
    sessionmaker: async_sessionmaker,
    redis: redis_async.Redis,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> None:
    async with sessionmaker() as session:
        watched = {
            w.address
            for w in (await session.execute(
                select(SmartWallet).where(SmartWallet.active == True)  # noqa: E712
            )).scalars()
        }
    if not watched:
        return

    for event in events:
        parsed = parse_swap_event(event, watched)
        if parsed is None:
            continue
        candidate = Candidate(
            source="helius_webhook",
            mint=parsed["mint"],
            side=parsed["side"],
            wallet=parsed["wallet"],
            amount_usd=parsed.get("amount_usd"),
            tx_sig=parsed.get("tx_sig"),
            raw=parsed["raw"],
        )
        try:
            await process_candidate(
                candidate,
                sessionmaker=sessionmaker,
                redis=redis,
                rugcheck=rugcheck,
                birdeye=birdeye,
                dexscreener=dexscreener,
                policy=policy,
                trader=trader,
            )
        except Exception as e:  # noqa: BLE001
            log.error("webhook_process_failed", error=str(e), tx=candidate.tx_sig)
