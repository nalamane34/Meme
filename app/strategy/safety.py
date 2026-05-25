"""Pre-trade safety gate.

Runs *before* the policy ever sees the token. Anything that fails here
is hard-rejected — the RL agent doesn't get a vote on rugpulls.
"""

from dataclasses import dataclass
from typing import Any

from app.clients.dexscreener import DexScreenerClient
from app.clients.rugcheck import RugCheckClient
from app.config import get_settings


@dataclass(frozen=True)
class SafetyVerdict:
    safe: bool
    score: int | None
    reasons: list[str]
    liquidity_usd: float | None
    rugcheck: dict[str, Any] | None


# Defaults tuned for "don't lose money to obvious rugs" — tweak liberally.
MIN_RUGCHECK_SCORE = 60          # 0 = clean, 100 = certain rug in RugCheck's scoring (LOWER is safer)
MIN_LIQUIDITY_USD = 15_000
MAX_TOP10_HOLDER_PCT = 0.35      # 35% of supply in top 10 = too concentrated


async def assess(mint: str, rugcheck: RugCheckClient, dexscreener: DexScreenerClient) -> SafetyVerdict:
    s = get_settings()
    if mint in (s.blacklist_mints or []):
        return SafetyVerdict(False, None, ["blacklisted"], None, None)

    reasons: list[str] = []
    score: int | None = None
    rc_payload: dict[str, Any] | None = None
    liquidity_usd: float | None = None

    rc_payload = await rugcheck.summary(mint)
    if rc_payload is None:
        reasons.append("rugcheck_unavailable")
    else:
        # RugCheck's `score` field: higher = riskier. Inversion is intentional.
        score = rc_payload.get("score")
        if isinstance(score, int) and score > MIN_RUGCHECK_SCORE:
            reasons.append(f"rugcheck_score_{score}>limit_{MIN_RUGCHECK_SCORE}")

        risks = rc_payload.get("risks") or []
        for r in risks:
            name = (r.get("name") or "").lower()
            level = (r.get("level") or "").lower()
            if level in ("danger", "high"):
                # Hard-fail on critical issues regardless of score.
                if any(k in name for k in ("mint authority", "freeze authority", "honeypot")):
                    reasons.append(f"critical_risk:{name}")

    pair = await dexscreener.best_pair(mint)
    if pair is None:
        reasons.append("no_dex_pair")
    else:
        liquidity_usd = float((pair.get("liquidity") or {}).get("usd") or 0)
        if liquidity_usd < MIN_LIQUIDITY_USD:
            reasons.append(f"liquidity_${liquidity_usd:.0f}<min_${MIN_LIQUIDITY_USD}")

    return SafetyVerdict(
        safe=not reasons,
        score=score,
        reasons=reasons,
        liquidity_usd=liquidity_usd,
        rugcheck=rc_payload,
    )
