import numpy as np

from app.strategy.features import FEATURE_DIM, FeatureSnapshot
from app.strategy.policy import (
    ACTION_BUY_FULL,
    ACTION_BUY_SMALL,
    ACTION_SKIP,
    RuleBasedPolicy,
)


def _snapshot(**overrides) -> FeatureSnapshot:
    meta = {
        "age_min": 30,
        "liquidity_usd": 50_000,
        "fdv_usd": 1_000_000,
        "vol_5m_usd": 10_000,
        "vol_1h_usd": 100_000,
        "price_change_5m": 0.1,
        "price_change_1h": 0.3,
        "buy_ratio": 0.7,
        "smart_wallets_1h": 3,
        "smart_buy_pressure_usd": 5_000,
        "rugcheck_score": 20,
        "holders": 500,
        "signal_amount_usd": 200,
    }
    meta.update(overrides)
    return FeatureSnapshot(vector=np.zeros(FEATURE_DIM, dtype=np.float32), meta=meta)


def test_buy_full_on_strong_signal():
    p = RuleBasedPolicy()
    d = p.decide(_snapshot())
    assert d.action == ACTION_BUY_FULL


def test_skip_on_low_liquidity():
    p = RuleBasedPolicy()
    d = p.decide(_snapshot(liquidity_usd=5_000))
    assert d.action == ACTION_SKIP
    assert "liquidity" in d.reason


def test_skip_when_too_new():
    p = RuleBasedPolicy()
    d = p.decide(_snapshot(age_min=1))
    assert d.action == ACTION_SKIP


def test_buy_small_on_moderate_signal():
    p = RuleBasedPolicy()
    # 3 of 6 bullish: price_change_5m, buy_ratio, vol_5m. The others miss.
    d = p.decide(_snapshot(
        price_change_5m=0.08,
        price_change_1h=0.05,
        buy_ratio=0.65,
        smart_wallets_1h=1,
        smart_buy_pressure_usd=-100,
        vol_5m_usd=6_000,
    ))
    assert d.action == ACTION_BUY_SMALL
