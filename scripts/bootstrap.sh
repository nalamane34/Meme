#!/usr/bin/env bash
# One-shot bootstrap: installs Docker, clones the repo, copies .env.example
# to .env. Intended to be run on a fresh Ubuntu/Debian EC2 instance.
#
# After this finishes you still need to:
#   1) Edit ~/memebot/.env and paste your secrets
#   2) Run `make up` from ~/memebot
set -euo pipefail

BRANCH="${BRANCH:-claude/meme-stock-rl-bot-wXlk5}"
REPO="${REPO:-https://github.com/nalamane34/Meme.git}"
DIR="${DIR:-$HOME/memebot}"

echo "==> Installing prerequisites"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg git make nano

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODENAME stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "==> Docker installed. You may need to log out + back in for group changes."
else
  echo "==> Docker already installed"
fi

if [ ! -d "$DIR/.git" ]; then
  echo "==> Cloning repo to $DIR"
  git clone "$REPO" "$DIR"
fi

cd "$DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
  chmod 600 .env
fi

cat <<'EOF'

==> Bootstrap complete.

Next steps (still on this EC2 box):

  1) Edit ~/memebot/.env and paste your secrets:
         nano ~/memebot/.env

     Required fields:
       WALLET_PRIVATE_KEY     <-- base58 from Phantom
       HELIUS_API_KEY         <-- helius.dev dashboard
       HELIUS_WEBHOOK_SECRET  <-- generate: openssl rand -hex 32
       BIRDEYE_API_KEY        <-- bds.birdeye.so dashboard
       DOMAIN                 <-- e.g. memebot42.duckdns.org (skip for now if dry-run only)
       POSTGRES_PASSWORD      <-- generate: openssl rand -hex 16
       DRY_RUN=true           <-- keep true until you've shadowed for 1-2 weeks

  2) Boot the stack:
         cd ~/memebot
         make up
         make logs

  3) Verify:
         make status

EOF
