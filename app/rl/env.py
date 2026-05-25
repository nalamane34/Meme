"""Offline Gymnasium env that replays logged signals.

Each episode = one signal from the `signals` table that the rule-based
policy saw during phase 1. The agent picks an action (skip / buy_small /
buy_full), and the reward is the realized PnL we would have earned if we
took that action and exited via the standard stop-loss / take-profit
rules N minutes later.

Why offline-only:
    Live PPO needs millions of steps. Memes don't give you millions of
    cheap, safe trials. Offline learning from real, already-observed
    trajectories is the only practical approach until shadow PnL is
    convincingly positive.
"""

from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.strategy.features import FEATURE_DIM
from app.strategy.policy import ACTION_BUY_FULL, ACTION_BUY_SMALL, ACTION_SKIP


@dataclass
class ReplayStep:
    """A row from the replay dataset.

    `features` is the state vector at decision time.
    `outcome_pct` is the % PnL we would have realized given the standard
    stop-loss / take-profit logic, computed offline from historical price
    data (see scripts/build_replay.py — TODO).
    """

    features: np.ndarray
    outcome_pct: float
    mint: str


class MemeReplayEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, dataset: list[ReplayStep], position_size_usd: float = 50.0):
        super().__init__()
        if not dataset:
            raise ValueError("MemeReplayEnv needs at least one replay step")
        self._dataset = dataset
        self._position_size_usd = position_size_usd
        self._idx = 0

        self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(FEATURE_DIM,), dtype=np.float32
        )

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        self._idx = int(self.np_random.integers(0, len(self._dataset)))
        return self._dataset[self._idx].features, {}

    def step(self, action: int):
        step = self._dataset[self._idx]
        reward = self._reward(action, step.outcome_pct)
        terminated = True
        truncated = False
        return step.features, reward, terminated, truncated, {"mint": step.mint}

    def _reward(self, action: int, outcome_pct: float) -> float:
        """Reward = realized PnL in USD given the chosen size, minus a
        small holding penalty for taking risk on a bad trade."""
        if action == ACTION_SKIP:
            # Counterfactual penalty: small cost for skipping winners,
            # small reward for skipping losers. Keeps the agent honest.
            return float(-0.1 * outcome_pct * self._position_size_usd)
        size_mult = 0.5 if action == ACTION_BUY_SMALL else 1.0
        return float(size_mult * outcome_pct * self._position_size_usd)
