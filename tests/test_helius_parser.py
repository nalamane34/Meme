from app.clients.helius import parse_swap_event
from app.config import get_settings


def _usdc_swap_event(wallet: str, meme_mint: str, side: str) -> dict:
    """Synthesize a minimal Helius enhanced-tx payload for a USDC<->meme swap."""
    s = get_settings()
    if side == "buy":
        transfers = [
            {"mint": s.usdc_mint, "tokenAmount": 100, "fromUserAccount": wallet, "toUserAccount": "amm"},
            {"mint": meme_mint, "tokenAmount": 12345, "fromUserAccount": "amm", "toUserAccount": wallet},
        ]
    else:
        transfers = [
            {"mint": meme_mint, "tokenAmount": 12345, "fromUserAccount": wallet, "toUserAccount": "amm"},
            {"mint": s.usdc_mint, "tokenAmount": 110, "fromUserAccount": "amm", "toUserAccount": wallet},
        ]
    return {"signature": "sig1", "tokenTransfers": transfers}


def test_parse_buy():
    wallet = "SmartW"
    meme = "MemeMintXYZ"
    event = _usdc_swap_event(wallet, meme, "buy")
    parsed = parse_swap_event(event, {wallet})
    assert parsed is not None
    assert parsed["wallet"] == wallet
    assert parsed["mint"] == meme
    assert parsed["side"] == "buy"
    assert parsed["amount_usd"] == 100


def test_parse_sell():
    wallet = "SmartW"
    meme = "MemeMintXYZ"
    event = _usdc_swap_event(wallet, meme, "sell")
    parsed = parse_swap_event(event, {wallet})
    assert parsed is not None
    assert parsed["side"] == "sell"
    assert parsed["mint"] == meme
    assert parsed["amount_usd"] == 110


def test_unwatched_wallet_returns_none():
    event = _usdc_swap_event("RandoW", "MemeMintXYZ", "buy")
    parsed = parse_swap_event(event, {"SmartW"})
    assert parsed is None


def test_no_meme_in_transfers_returns_none():
    s = get_settings()
    event = {
        "signature": "sig2",
        "tokenTransfers": [
            {"mint": s.usdc_mint, "tokenAmount": 10, "fromUserAccount": "SmartW", "toUserAccount": "x"}
        ],
    }
    assert parse_swap_event(event, {"SmartW"}) is None
