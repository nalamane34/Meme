"""Policy: maps a feature vector to a discrete action.

Action space:
    0 SKIP
    1 BUY_SMALL   (0.5x position size)
    2 BUY_FULL    (1.0x position size)

Sell decisions don't live here — they're driven by the position watcher
(stop-loss / take-profit / trailing stop). Keeping buy and sell on
separate control loops is intentional: it makes the RL credit-assignment
problem much easier.

Two implementations:
  - RuleBasedPolicy: handwritten thresholds, used during phase 1
  - PPOPolicy:       loads a stable_baselines3 model trained offline
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.strategy.features import FeatureSnapshot

ACTION_SKIP = 0
ACTION_BUY_SMALL = 1
ACTION_BUY_FULL = 2

ACTION_SIZES = {
    ACTION_SKIP: 0.0,
    ACTION_BUY_SMALL: 0.5,
    ACTION_BUY_FULL: 1.0,
}


@dataclass
class Decision:
    action: int
    size_multiplier: float
    reason: str


class Policy(Protocol):
    def decide(self, snapshot: FeatureSnapshot) -> Decision: ...


class RuleBasedPolicy:
    """Conservative defaults — tuned to *not* trade on garbage.

    A trade has to clear several thresholds simultaneously. This is the
    baseline the RL agent has to beat in shadow before we promote it.
    """

    def decide(self, snapshot: FeatureSnapshot) -> Decision:
        m = snapshot.meta

        if m["liquidity_usd"] < 25_000:
            return Decision(ACTION_SKIP, 0.0, "liquidity_too_low")
        if m["age_min"] < 3:
            return Decision(ACTION_SKIP, 0.0, "too_new_unverified")
        if m["age_min"] > 60 * 24 * 14:
            return Decision(ACTION_SKIP, 0.0, "too_old_no_edge")

        bullish_signals = 0
        bullish_signals += int(m["price_change_5m"] > 0.05)
        bullish_signals += int(m["price_change_1h"] > 0.15)
        bullish_signals += int(m["buy_ratio"] > 0.6)
        bullish_signals += int(m["smart_wallets_1h"] >= 2)
        bullish_signals += int(m["smart_buy_pressure_usd"] > 0)
        bullish_signals += int(m["vol_5m_usd"] > 5_000)

        if bullish_signals >= 5:
            return Decision(ACTION_BUY_FULL, 1.0, f"bullish_{bullish_signals}/6")
        if bullish_signals >= 3:
            return Decision(ACTION_BUY_SMALL, 0.5, f"bullish_{bullish_signals}/6")
        return Decision(ACTION_SKIP, 0.0, f"weak_signal_{bullish_signals}/6")


class PPOPolicy:
    """Wraps a stable_baselines3 model trained by rl/train.py."""

    def __init__(self, model_path: str):
        # Imported lazily so the runtime image doesn't need torch unless RL is on.
        from stable_baselines3 import PPO  # type: ignore

        self._model = PPO.load(model_path)

    def decide(self, snapshot: FeatureSnapshot) -> Decision:
        action, _ = self._model.predict(snapshot.vector, deterministic=True)
        a = int(np.asarray(action).item())
        return Decision(a, ACTION_SIZES[a], f"ppo_action_{a}")


def load_policy(strategy: str, model_path: str) -> Policy:
    if strategy == "ppo":
        return PPOPolicy(model_path)
    return RuleBasedPolicy()
