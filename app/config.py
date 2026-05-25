from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    wallet_private_key: str = ""
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"

    helius_api_key: str = ""
    helius_webhook_secret: str = ""

    birdeye_api_key: str = ""
    dexscreener_base_url: str = "https://api.dexscreener.com"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/meme"
    redis_url: str = "redis://localhost:6379/0"

    dry_run: bool = True
    strategy: Literal["rule_based", "ppo"] = "rule_based"
    model_path: str = "models/ppo_latest.zip"

    max_position_usd: float = 50.0
    max_open_positions: int = 5
    max_daily_loss_usd: float = 100.0
    slippage_bps: int = 300
    priority_fee_microlamports: int = 50_000

    stop_loss_pct: float = 0.25
    take_profit_pct: float = 2.0
    trailing_stop_pct: float = 0.35

    log_level: str = "INFO"
    port: int = 8000

    jupiter_quote_url: str = "https://quote-api.jup.ag/v6/quote"
    jupiter_swap_url: str = "https://quote-api.jup.ag/v6/swap"
    rugcheck_base_url: str = "https://api.rugcheck.xyz/v1"
    birdeye_base_url: str = "https://public-api.birdeye.so"

    usdc_mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    sol_mint: str = "So11111111111111111111111111111111111111112"

    halt_flag_key: str = "bot:halt"

    blacklist_mints: list[str] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
