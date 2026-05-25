"""Seed the smart_wallets table from a CSV.

CSV columns:
    address,label,tier,win_rate,pnl_30d_usd

Usage:
    python scripts/seed_wallets.py --from data/smart_wallets.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import SmartWallet


async def run(path: str) -> None:
    s = get_settings()
    engine = create_async_engine(s.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    added = 0
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        async with Session() as session:
            for row in reader:
                existing = await session.get(SmartWallet, row["address"])
                if existing:
                    continue
                session.add(SmartWallet(
                    address=row["address"],
                    label=row.get("label") or None,
                    tier=int(row.get("tier") or 1),
                    win_rate=float(row["win_rate"]) if row.get("win_rate") else None,
                    pnl_30d_usd=float(row["pnl_30d_usd"]) if row.get("pnl_30d_usd") else None,
                ))
                added += 1
            await session.commit()
    print(f"added {added} wallets")
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="path", required=True)
    args = p.parse_args()
    asyncio.run(run(args.path))
