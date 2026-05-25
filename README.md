# meme-rl-bot

Reinforcement-learning-assisted Solana meme-coin trading bot.

## What it does

1. **Discovers** candidates autonomously from DexScreener boosts/profiles,
   Birdeye trending + new listings, and pump.fun (near-graduation +
   just-graduated). Also **watches** any curated smart-money wallets via
   Helius webhooks.
2. **Filters** every candidate through safety checks (RugCheck score, LP
   burn, holder distribution, mint authority, freeze authority).
3. **Scores** survivors with a feature vector (price/volume velocity, holder
   growth, smart-wallet concentration, time since launch).
4. **Decides** with a policy — rule-based baseline today, PPO trained
   offline on logged trajectories once enough data exists.
5. **Executes** through the Jupiter Ultra API with slippage caps and
   (optionally) Jito bundles for MEV protection.
6. **Manages risk** outside the policy: hard stop-loss, trailing TP, max
   position size, daily loss circuit-breaker.
7. **Self-grows** the smart-wallet list: when a position closes
   profitably, auto-promotes the wallets that bought it early and prunes
   wallets that don't deliver wins.

## Two-phase RL plan

Online PPO on real money is a great way to lose real money. Instead:

| Phase | Policy           | Data                              | Goal                          |
|-------|------------------|-----------------------------------|-------------------------------|
| 1     | Rule-based       | Logs every (state, action, reward)| Collect a clean dataset       |
| 2     | Offline PPO/CQL  | Phase-1 logs + replay buffer      | Beat the baseline in shadow   |
| 3     | PPO live (small) | Live, capped position size        | Promote if shadow ≥ baseline  |

The `rl/` module ships the env, the offline trainer, and a shadow evaluator.
The default `STRATEGY=rule_based` runs phase 1 out of the box.

## Free-tier stack (matches your research)

| Layer       | Service                                    | Free tier              |
|-------------|--------------------------------------------|------------------------|
| Webhooks    | Helius                                     | 100k credits/mo        |
| Price/data  | Birdeye, DexScreener                       | Free                   |
| Safety      | RugCheck                                   | Free                   |
| Execution   | Jupiter Ultra                              | Free (gas only)        |
| Postgres    | Supabase                                   | 500MB                  |
| Redis       | Upstash                                    | 10k cmds/day           |
| Host        | Fly.io / Oracle ARM                        | Free                   |

Estimated cost: $0/mo + gas (~$0.05/swap).

## Quickstart

```bash
cp .env.example .env             # fill in HELIUS_API_KEY, etc.
uv sync                          # or: pip install -e .
docker compose up -d postgres redis
alembic upgrade head
uvicorn app.main:app --reload    # webhook receiver + API
```

Then point a Helius webhook at `https://<host>/webhooks/helius` and seed
smart wallets:

```bash
python scripts/seed_wallets.py --from data/smart_wallets.csv
```

By default `DRY_RUN=true` — no real swaps. Flip it only after you've watched
the logs for a week and the simulated PnL looks sane.

## Safety

- Private keys live in `WALLET_PRIVATE_KEY` env var only. Never commit `.env`.
- `MAX_POSITION_USD`, `MAX_DAILY_LOSS_USD`, and `MAX_OPEN_POSITIONS` are
  enforced before the policy is even consulted.
- A kill-switch endpoint (`POST /admin/halt`) flushes all positions to
  stables and disables new entries until manually re-armed.

## Autonomous discovery

The bot doesn't need a seeded smart-wallet list to start trading — every
scanner runs independently on its own cadence:

| Scanner                       | Source                              | Cadence  |
|-------------------------------|-------------------------------------|----------|
| DexScreener latest boosts     | `/token-boosts/latest/v1`           | 3 min    |
| DexScreener latest profiles   | `/token-profiles/latest/v1`         | 5 min    |
| Birdeye trending              | `/defi/token_trending`              | 10 min   |
| Birdeye new listings          | `/defi/v2/tokens/new_listing`       | 10 min   |
| pump.fun near-graduation      | `frontend-api.pump.fun /coins`      | 2 min    |
| pump.fun just-graduated       | `frontend-api.pump.fun /coins`      | 2 min    |
| Smart-wallet auto-promotion   | Birdeye top traders of our winners  | 1 hr     |

Every candidate funnels into the same pipeline as the Helius webhook
signals — same safety gate, same feature vector, same policy. Toggle off
with `DISCOVERY_ENABLED=false` if you ever want pure copy-trading mode.

## Layout

```
app/
  main.py                  FastAPI: webhook + admin API + lifespan
  config.py                Pydantic settings
  webhooks/helius.py       Parses enhanced-tx webhook events → pipeline
  discovery/
    scheduler.py           Runs every scanner on its own cadence
    dexscreener.py         Boosts + profiles
    birdeye.py             Trending + new listings
    pumpfun.py             Near-graduation + just-graduated
    wallet_finder.py       Auto-promote smart wallets from winners
  clients/                 Jupiter, Helius parser, RugCheck, Birdeye, DexScreener
  strategy/
    pipeline.py            Shared candidate → trade flow
    features.py            Builds the RL state vector
    safety.py              Pre-trade safety gate
    policy.py              Rule-based + RL policy interface
  rl/
    env.py                 Gymnasium env for offline training
    train.py               PPO trainer
  executor/
    trader.py              Buy/sell + position management
    wallet.py              Solana Keypair handling
  monitors/
    position_watcher.py    Stop-loss / take-profit loop
  db/models.py             SQLAlchemy models
scripts/                   Ops scripts
tests/                     Pytest suite
```
