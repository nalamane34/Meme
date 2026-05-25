"""Helius enhanced-tx parser.

Helius "enhanced" webhook payloads have already decoded common DEX swaps
into a structured `tokenTransfers` list. We don't need to re-parse raw
instructions — we just need to figure out, for each event:

  - the watched wallet
  - the meme-coin mint involved
  - whether the watched wallet was a buyer or seller
  - approximate USD size (using SOL or USDC counterleg)

For the spec we trust the `tokenTransfers` list and the `events.swap` block
when present.
"""

from typing import Any

from app.config import get_settings

_SETTINGS = get_settings()
_STABLE_OR_SOL = {_SETTINGS.usdc_mint, _SETTINGS.sol_mint}


def parse_swap_event(event: dict[str, Any], watched_wallets: set[str]) -> dict[str, Any] | None:
    """Return a normalized signal dict, or None if nothing actionable.

    Output schema:
        {
            "wallet":      str,   # the watched wallet
            "mint":        str,   # the meme-coin mint
            "side":        "buy" | "sell",  # what the watched wallet did
            "amount_usd":  float | None,
            "tx_sig":      str,
            "raw":         dict,
        }
    """
    transfers = event.get("tokenTransfers") or []
    if not transfers:
        return None

    # Find which watched wallet appears
    wallet: str | None = None
    for t in transfers:
        for key in ("fromUserAccount", "toUserAccount"):
            addr = t.get(key)
            if addr and addr in watched_wallets:
                wallet = addr
                break
        if wallet:
            break
    if wallet is None:
        return None

    # Figure out the meme mint: the non-stable/SOL token touching the watched wallet
    meme_in: str | None = None  # mint the wallet received
    meme_out: str | None = None  # mint the wallet sent
    counter_usd: float | None = None

    for t in transfers:
        mint = t.get("mint")
        if mint is None:
            continue
        amt = t.get("tokenAmount") or 0
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            amt = 0.0
        is_stable_leg = mint in _STABLE_OR_SOL
        sends_from_wallet = t.get("fromUserAccount") == wallet
        sends_to_wallet = t.get("toUserAccount") == wallet

        if is_stable_leg and (sends_from_wallet or sends_to_wallet):
            # Crude USD: 1 USDC = $1, 1 SOL ~ price unknown here; we'll fill it in later.
            if mint == _SETTINGS.usdc_mint:
                counter_usd = amt
        else:
            if sends_to_wallet:
                meme_in = mint
            elif sends_from_wallet:
                meme_out = mint

    if meme_in:
        side = "buy"
        mint = meme_in
    elif meme_out:
        side = "sell"
        mint = meme_out
    else:
        return None

    return {
        "wallet": wallet,
        "mint": mint,
        "side": side,
        "amount_usd": counter_usd,
        "tx_sig": event.get("signature"),
        "raw": event,
    }
