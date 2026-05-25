"""FastAPI entry point.

Wires together:
  - clients (Jupiter, RugCheck, Birdeye, DexScreener, Helius parser)
  - policy (rule-based or PPO based on settings.strategy)
  - trader + wallet
  - position watcher background task
  - inbound webhook router
  - admin endpoints (halt, resume, status)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis_async
from fastapi import APIRouter, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clients.birdeye import BirdeyeClient
from app.clients.dexscreener import DexScreenerClient
from app.clients.jupiter import JupiterClient
from app.clients.rugcheck import RugCheckClient
from app.config import get_settings
from app.db.models import Position, PositionStatus
from app.discovery.scheduler import discovery_loop
from app.executor.trader import Trader
from app.executor.wallet import Wallet
from app.logging import configure_logging, get_logger
from app.monitors.position_watcher import watch_loop
from app.strategy.policy import load_policy
from app.webhooks.helius import build_router as build_helius_router

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    s = get_settings()

    engine = create_async_engine(s.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    redis = redis_async.from_url(s.redis_url, decode_responses=True)

    jupiter = JupiterClient()
    rugcheck = RugCheckClient()
    birdeye = BirdeyeClient()
    dexscreener = DexScreenerClient()

    wallet: Wallet | None = None
    try:
        wallet = Wallet()
    except Exception as e:  # noqa: BLE001
        log.warning("wallet_disabled", error=str(e))

    trader = Trader(jupiter=jupiter, birdeye=birdeye, wallet=wallet, redis=redis)
    policy = load_policy(s.strategy, s.model_path)

    app.include_router(
        build_helius_router(
            sessionmaker=sessionmaker,
            redis=redis,
            rugcheck=rugcheck,
            birdeye=birdeye,
            dexscreener=dexscreener,
            policy=policy,
            trader=trader,
        )
    )
    app.include_router(_admin_router(sessionmaker=sessionmaker, redis=redis, trader=trader))

    watcher_task = asyncio.create_task(
        watch_loop(sessionmaker=sessionmaker, trader=trader, birdeye=birdeye)
    )
    discovery_task = asyncio.create_task(
        discovery_loop(
            sessionmaker=sessionmaker,
            redis=redis,
            rugcheck=rugcheck,
            birdeye=birdeye,
            dexscreener=dexscreener,
            policy=policy,
            trader=trader,
        )
    )

    log.info("startup", dry_run=s.dry_run, strategy=s.strategy, discovery=s.discovery_enabled)
    try:
        yield
    finally:
        watcher_task.cancel()
        discovery_task.cancel()
        await asyncio.gather(
            jupiter.aclose(), rugcheck.aclose(), birdeye.aclose(), dexscreener.aclose(),
            return_exceptions=True,
        )
        if wallet is not None:
            await wallet.aclose()
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title="meme-rl-bot", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _admin_router(*, sessionmaker, redis, trader: Trader) -> APIRouter:
    s = get_settings()
    r = APIRouter(prefix="/admin", tags=["admin"])

    @r.post("/halt")
    async def halt() -> dict[str, str]:
        await redis.set(s.halt_flag_key, "1")
        return {"status": "halted"}

    @r.post("/resume")
    async def resume() -> dict[str, str]:
        await redis.delete(s.halt_flag_key)
        return {"status": "resumed"}

    @r.post("/flush")
    async def flush() -> dict[str, int]:
        """Force-close every open position. Used as a kill-switch."""
        closed = 0
        async with sessionmaker() as session:
            q = select(Position).where(Position.status == PositionStatus.OPEN.value)
            for p in (await session.execute(q)).scalars().all():
                res = await trader.sell(session=session, position=p, reason="admin_flush")
                if res.ok:
                    closed += 1
        return {"closed": closed}

    @r.get("/status")
    async def status() -> dict:
        halted = (await redis.get(s.halt_flag_key)) is not None
        async with sessionmaker() as session:
            q = select(Position).where(Position.status == PositionStatus.OPEN.value)
            open_positions = (await session.execute(q)).scalars().all()
        return {
            "halted": halted,
            "dry_run": s.dry_run,
            "strategy": s.strategy,
            "open_positions": len(open_positions),
            "open_mints": [p.mint for p in open_positions],
        }

    @r.post("/blacklist/{mint}")
    async def blacklist(mint: str) -> dict[str, str]:
        from app.db.models import Token  # local to avoid cycle

        async with sessionmaker() as session:
            token = await session.get(Token, mint)
            if token is None:
                raise HTTPException(404, "unknown mint")
            token.blacklisted = True
            await session.commit()
        return {"status": "blacklisted", "mint": mint}

    return r
