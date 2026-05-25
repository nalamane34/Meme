# Deploy to AWS EC2 (t4g.small + Docker Compose + Caddy)

Target: one `t4g.small` (2 vCPU ARM Graviton, 2 GB RAM, ~$12/mo) running the
whole stack (app + Postgres + Redis + Caddy) on Docker Compose. Caddy
auto-issues a Let's Encrypt cert so the Helius webhook gets a real HTTPS
endpoint.

## 0. Prereqs

- An AWS account.
- A domain (or a free DuckDNS / DynDNS subdomain — see step 4).
- Phantom wallet created, funded, and you have the base58 private key handy.
- `HELIUS_API_KEY` and `BIRDEYE_API_KEY` from your dashboards.

## 1. Launch the EC2 instance

In the AWS Console → EC2 → Launch Instance:

- **Name**: `memebot`
- **AMI**: Ubuntu Server 24.04 LTS (HVM), arm64 architecture
- **Instance type**: `t4g.small`
- **Key pair**: create a fresh one (`ed25519` if offered). Save the `.pem`
  somewhere safe on YOUR machine. Don't share it.
- **Network settings → Edit**:
  - Allow SSH (port 22) — restrict source to *your IP* (not 0.0.0.0/0).
  - Allow HTTP (port 80) from anywhere.
  - Allow HTTPS (port 443) from anywhere.
- **Storage**: 20 GB gp3 (default 8 GB is too small for Postgres).
- Launch.

Once running, allocate an **Elastic IP** and associate it with the instance
so the IP doesn't change on reboot.

## 2. SSH in

```bash
chmod 600 ~/Downloads/memebot.pem
ssh -i ~/Downloads/memebot.pem ubuntu@<elastic-ip>
```

## 3. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git make
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
exec sg docker newgrp `id -gn`   # apply group without re-login
```

## 4. Point a domain at the instance

You need HTTPS — Helius rejects HTTP webhook targets. Two free options:

**Option A: DuckDNS (no domain purchase needed, 5 min setup)**

1. Sign in at https://www.duckdns.org with GitHub/Google.
2. Pick a subdomain, e.g. `memebot42`.
3. Set its IP to the EC2 elastic IP.
4. Your URL is now `memebot42.duckdns.org`.

**Option B: A domain you already own**

Create an `A` record pointing `bot.yourdomain.com` at the elastic IP. Wait
2–5 minutes for DNS to propagate.

Confirm DNS resolves correctly:

```bash
dig +short memebot42.duckdns.org   # should return the EC2 IP
```

## 5. Clone the repo and configure

```bash
git clone <your-fork-or-https-url> memebot
cd memebot
git checkout claude/meme-stock-rl-bot-wXlk5
cp .env.example .env
nano .env
```

Fill in `.env`:

```ini
DOMAIN=memebot42.duckdns.org

WALLET_PRIVATE_KEY=<base58 from Phantom>
HELIUS_API_KEY=<your key>
HELIUS_WEBHOOK_SECRET=<generate one: openssl rand -hex 32>
BIRDEYE_API_KEY=<your key>

POSTGRES_USER=postgres
POSTGRES_PASSWORD=<openssl rand -hex 16>
POSTGRES_DB=meme

DRY_RUN=true
MAX_POSITION_USD=50
MAX_OPEN_POSITIONS=5
MAX_DAILY_LOSS_USD=100
```

Make sure `DRY_RUN=true` for the first run. Verify file perms — only your
user should read it:

```bash
chmod 600 .env
```

## 6. Bring up the stack

```bash
make up
make logs
```

Watch for:
- `[entrypoint] running alembic migrations`
- `Uvicorn running on http://0.0.0.0:8000`
- `discovery_tick` lines starting to appear (the scanners ran for the first time)

Caddy will spend ~30 seconds getting a Let's Encrypt cert the first time.
You'll see Caddy log lines like `certificate obtained successfully`.

From your laptop:

```bash
curl https://memebot42.duckdns.org/healthz
# {"status":"ok"}
```

## 7. Register the Helius webhook

From inside the EC2 box:

```bash
docker compose -f docker-compose.prod.yml exec app \
  python scripts/register_helius_webhook.py --url https://memebot42.duckdns.org/webhooks/helius
```

Save the returned `webhookID` somewhere — you'll need it if you want to
update the wallet list later.

## 8. Optional: seed initial smart wallets

You don't *need* this — discovery works standalone. But if you have a few
known good wallets (from GMGN.ai weekly top traders, Birdeye leaderboard,
etc.), drop them in:

```bash
nano data/smart_wallets.csv      # see data/smart_wallets.example.csv for format
docker compose -f docker-compose.prod.yml exec app \
  python scripts/seed_wallets.py --from data/smart_wallets.csv
```

Then re-run step 7 so Helius starts pushing those wallets' txs to the webhook.

## 9. Verify (paper-trading mode)

Wait an hour, then check:

```bash
make status
# {"halted": false, "dry_run": true, "strategy": "rule_based", "open_positions": 0, ...}

# Decisions so far
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U postgres -d meme -c "select source, decision, count(*) from signals group by 1,2 order by 1,2;"

# Paper positions
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U postgres -d meme -c "select mint, entry_price_usd, exit_price_usd, exit_reason, realized_pnl_usd from positions order by opened_at desc limit 10;"
```

## 10. Going live

After 1–2 weeks of paper trading where the simulated PnL looks reasonable:

```bash
nano .env                # set DRY_RUN=false
make up                  # rebuilds with the new env
```

`make halt` / `make resume` / `make flush` are the kill switches. Bookmark them.

## Maintenance

Pull updates and redeploy:

```bash
make pull                # git pull + rebuild + restart
```

Tail logs:

```bash
make logs
```

Backup the DB before risky changes:

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U postgres meme | gzip > backup-$(date +%F).sql.gz
```

## Hardening notes for later

- Move secrets out of `.env` into AWS Secrets Manager + `chamber` or `sops`.
- Put the admin endpoints behind Cloudflare Access or basic auth (see the
  commented block in `Caddyfile`).
- Switch the DB to RDS or Supabase once the data set matters.
- Set up CloudWatch agent for log shipping if you want alerting.
- Snapshot the EBS volume nightly via AWS Backup.
