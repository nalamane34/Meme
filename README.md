# meme-rl-bot

Reinforcement-learning-assisted Solana meme-coin trading bot.

## What it does

1. **Watches** a curated set of "smart-money" wallets via Helius webhooks.
2. **Filters** every candidate token through safety checks (RugCheck score, LP
   burn, holder distribution, mint authority, freeze authority).
3. **Scores** survivors with a feature vector (price/volume velocity, holder
   growth, smart-wallet concentration, time since launch, social signal).
4. **Decides** with a policy — rule-based baseline today, PPO trained offline
   on logged trajectories once enough data exists.
5. **Executes** through the Jupiter Ultra API with slippage caps and
   (optionally) Jito bundles for MEV protection.
6. **Manages risk** outside the policy: hard stop-loss, trailing TP, max
   position size, daily loss circuit-breaker.

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

## Layout

```
app/
  main.py                  FastAPI: webhook + admin API
  config.py                Pydantic settings
  webhooks/helius.py       Parses enhanced-tx webhook events
  clients/                 Jupiter, Helius, RugCheck, Birdeye, DexScreener
  strategy/
    features.py            Builds the RL state vector
    safety.py              Pre-trade safety gate
    policy.py              Rule-based + RL policy interface
  rl/
    env.py                 Gymnasium env for offline training
    train.py               PPO/CQL trainer
    shadow.py              Shadow evaluator vs. baseline
  executor/
    trader.py              Buy/sell + position management
    wallet.py              Solana Keypair handling
  monitors/
    position_watcher.py    Stop-loss / take-profit loop
  db/models.py             SQLAlchemy models
scripts/                   Ops scripts
tests/                     Pytest suite
```
