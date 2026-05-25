"""Discovery scheduler.

Runs each scanner on its own cadence and feeds candidates through the
shared pipeline. Heavy on the cheap free endpoints, light on the rate-
limited ones (Birdeye trending is hourly, DexScreener boosts is every
few minutes).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

import redis.asyncio as redis_async
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.birdeye import BirdeyeClient
from app.clients.dexscreener import DexScreenerClient
from app.clients.rugcheck import RugCheckClient
from app.config import get_settings
from app.discovery.birdeye import BirdeyeDiscovery
from app.discovery.dexscreener import DexScreenerDiscovery
from app.discovery.pumpfun import PumpFunDiscovery
from app.discovery.wallet_finder import WalletFinder, prune_inactive
from app.executor.trader import Trader
from app.logging import get_logger
from app.strategy.pipeline import Candidate, process_candidate
from app.strategy.policy import Policy

log = get_logger(__name__)


@dataclass
class _Job:
    name: str
    interval_sec: float
    fn: Callable[[], Awaitable[list[Candidate]]]


async def discovery_loop(
    *,
    sessionmaker: async_sessionmaker,
    redis: redis_async.Redis,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> None:
    s = get_settings()
    if not s.discovery_enabled:
        log.info("discovery_disabled")
        return

    dex_disc = DexScreenerDiscovery()
    bird_disc = BirdeyeDiscovery(client=birdeye)
    pump_disc = PumpFunDiscovery()
    finder = WalletFinder(birdeye=birdeye)

    jobs: list[_Job] = [
        _Job("dex_boosts_latest", s.discovery_dex_boosts_interval_sec, dex_disc.latest_boosts),
        _Job("dex_profiles_latest", s.discovery_dex_profiles_interval_sec, dex_disc.latest_profiles),
        _Job("birdeye_trending", s.discovery_birdeye_interval_sec, bird_disc.trending),
        _Job("birdeye_new", s.discovery_birdeye_interval_sec, bird_disc.new_listings),
        _Job("pumpfun_near_grad", s.discovery_pumpfun_interval_sec, pump_disc.near_graduation),
        _Job("pumpfun_graduated", s.discovery_pumpfun_interval_sec, pump_disc.just_graduated),
    ]

    tasks = [
        asyncio.create_task(_run_job(j, sessionmaker, redis, rugcheck, birdeye, dexscreener, policy, trader))
        for j in jobs
    ]
    tasks.append(asyncio.create_task(_wallet_finder_loop(finder, sessionmaker, s.discovery_wallet_finder_interval_sec)))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise
    finally:
        await asyncio.gather(dex_disc.aclose(), pump_disc.aclose(), return_exceptions=True)


async def _run_job(
    job: _Job,
    sessionmaker: async_sessionmaker,
    redis: redis_async.Redis,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> None:
    while True:
        try:
            candidates = await job.fn()
            log.info("discovery_tick", job=job.name, candidates=len(candidates))
            for c in candidates:
                try:
                    await process_candidate(
                        c,
                        sessionmaker=sessionmaker,
                        redis=redis,
                        rugcheck=rugcheck,
                        birdeye=birdeye,
                        dexscreener=dexscreener,
                        policy=policy,
                        trader=trader,
                    )
                except Exception as e:  # noqa: BLE001
                    log.error("discovery_candidate_failed", job=job.name, mint=c.mint, error=str(e))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("discovery_job_failed", job=job.name, error=str(e))
        await asyncio.sleep(job.interval_sec)


async def _wallet_finder_loop(
    finder: WalletFinder, sessionmaker: async_sessionmaker, interval_sec: float
) -> None:
    while True:
        try:
            await finder.run(sessionmaker)
            await prune_inactive(sessionmaker)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("wallet_finder_failed", error=str(e))
        await asyncio.sleep(interval_sec)
