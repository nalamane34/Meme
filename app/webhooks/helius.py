"""Inbound Helius webhook handler.

Helius sends a JSON array of enhanced transactions per delivery. For each
event we:

  1. Identify which watched wallet was involved.
  2. Parse out the meme mint + side (buy/sell from the *watched* wallet's POV).
  3. Run the safety gate (RugCheck + liquidity).
  4. Build the feature vector.
  5. Ask the policy for a decision.
  6. If the decision is a buy, call the trader.
  7. Persist the signal (with features + decision) for later RL training.

Steps 3–7 happen in a fire-and-forget task so the HTTP request returns
fast — Helius retries delayed responses, which can cause duplicate work.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.birdeye import BirdeyeClient
from app.clients.dexscreener import DexScreenerClient
from app.clients.helius import parse_swap_event
from app.clients.rugcheck import RugCheckClient
from app.config import get_settings
from app.db.models import Signal, SmartWallet, Token
from app.executor.trader import Trader
from app.logging import get_logger
from app.strategy.features import build_features
from app.strategy.policy import ACTION_SKIP, Policy
from app.strategy.safety import assess

log = get_logger(__name__)


def build_router(
    *,
    sessionmaker: async_sessionmaker,
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

        asyncio.create_task(_process_batch(events, sessionmaker, rugcheck, birdeye, dexscreener, policy, trader))
        return {"received": len(events)}

    return router


async def _process_batch(
    events: list[dict[str, Any]],
    sessionmaker: async_sessionmaker,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> None:
    async with sessionmaker() as session:
        watched = {w.address for w in (await session.execute(select(SmartWallet).where(SmartWallet.active == True))).scalars()}  # noqa: E712
        if not watched:
            log.debug("no_watched_wallets")
            return

    for event in events:
        parsed = parse_swap_event(event, watched)
        if parsed is None:
            continue
        try:
            await _process_one(parsed, sessionmaker, rugcheck, birdeye, dexscreener, policy, trader)
        except Exception as e:  # noqa: BLE001
            log.error("process_one_failed", error=str(e), tx=parsed.get("tx_sig"))


async def _process_one(
    parsed: dict[str, Any],
    sessionmaker: async_sessionmaker,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> None:
    mint = parsed["mint"]
    side = parsed["side"]

    async with sessionmaker() as session:
        # Upsert token row
        token = await session.get(Token, mint)
        if token is None:
            token = Token(mint=mint)
            session.add(token)
            await session.commit()

        # Only buys are entry signals. Sells from smart wallets are exit
        # hints we may use later (TODO: mirror-exit logic).
        if side != "buy":
            session.add(Signal(
                source="helius_webhook",
                wallet=parsed["wallet"],
                mint=mint,
                side=side,
                amount_usd=parsed.get("amount_usd"),
                tx_sig=parsed.get("tx_sig"),
                raw=parsed["raw"],
                decision="observe_sell",
                decision_reason="watched_wallet_sold",
            ))
            await session.commit()
            return

        verdict = await assess(mint, rugcheck, dexscreener)
        if not verdict.safe:
            session.add(Signal(
                source="helius_webhook",
                wallet=parsed["wallet"],
                mint=mint,
                side=side,
                amount_usd=parsed.get("amount_usd"),
                tx_sig=parsed.get("tx_sig"),
                raw=parsed["raw"],
                decision="skip",
                decision_reason="unsafe:" + ",".join(verdict.reasons)[:200],
            ))
            token.rugcheck_score = verdict.score
            token.rugcheck_payload = verdict.rugcheck
            token.blacklisted = token.blacklisted or any("critical_risk" in r for r in verdict.reasons)
            await session.commit()
            return

        snapshot = await build_features(
            session=session,
            mint=mint,
            signal_amount_usd=parsed.get("amount_usd"),
            birdeye=birdeye,
            dexscreener=dexscreener,
            rugcheck_score=verdict.score,
        )
        decision = policy.decide(snapshot)

        signal = Signal(
            source="helius_webhook",
            wallet=parsed["wallet"],
            mint=mint,
            side=side,
            amount_usd=parsed.get("amount_usd"),
            tx_sig=parsed.get("tx_sig"),
            raw=parsed["raw"],
            features=snapshot.meta,
            decision=("buy" if decision.action != ACTION_SKIP else "skip"),
            decision_reason=decision.reason,
        )
        session.add(signal)
        token.rugcheck_score = verdict.score
        token.rugcheck_payload = verdict.rugcheck
        await session.commit()

        if decision.action == ACTION_SKIP:
            return

        await trader.buy(
            session=session,
            mint=mint,
            size_multiplier=decision.size_multiplier,
            entry_signal_id=signal.id,
        )
