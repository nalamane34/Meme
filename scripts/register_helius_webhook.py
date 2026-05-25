"""Register/update a Helius webhook for all active smart wallets.

Helius API: https://docs.helius.dev/webhooks-and-websockets/api-reference/edit-webhook

Usage:
    python scripts/register_helius_webhook.py --url https://your-host/webhooks/helius
"""

from __future__ import annotations

import argparse
import asyncio
import os

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import SmartWallet


async def run(webhook_url: str, webhook_id: str | None) -> None:
    s = get_settings()
    if not s.helius_api_key:
        raise SystemExit("HELIUS_API_KEY not set")

    engine = create_async_engine(s.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        wallets = (await session.execute(select(SmartWallet).where(SmartWallet.active == True))).scalars().all()  # noqa: E712
    addresses = [w.address for w in wallets]
    print(f"registering {len(addresses)} addresses")

    body = {
        "webhookURL": webhook_url,
        "transactionTypes": ["SWAP", "TOKEN_MINT", "TRANSFER"],
        "accountAddresses": addresses,
        "webhookType": "enhanced",
        "authHeader": s.helius_webhook_secret or "",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        if webhook_id:
            r = await client.put(
                f"https://api.helius.xyz/v0/webhooks/{webhook_id}",
                params={"api-key": s.helius_api_key},
                json=body,
            )
        else:
            r = await client.post(
                "https://api.helius.xyz/v0/webhooks",
                params={"api-key": s.helius_api_key},
                json=body,
            )
        r.raise_for_status()
        print(r.json())
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--webhook-id", default=os.environ.get("HELIUS_WEBHOOK_ID"))
    args = p.parse_args()
    asyncio.run(run(args.url, args.webhook_id))
