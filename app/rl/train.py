"""Offline PPO trainer.

Usage:
    python -m app.rl.train --dataset data/replay.parquet --out models/ppo_latest.zip

The dataset is built by scripts/build_replay.py from the `signals` table
plus historical price data. Each row contributes one ReplayStep.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from app.rl.env import MemeReplayEnv, ReplayStep
from app.strategy.features import FEATURE_DIM


def load_dataset(path: str) -> list[ReplayStep]:
    df = pd.read_parquet(path)
    feature_cols = [c for c in df.columns if c.startswith("f")]
    assert len(feature_cols) == FEATURE_DIM, (
        f"expected {FEATURE_DIM} feature cols, got {len(feature_cols)}"
    )
    steps: list[ReplayStep] = []
    for _, row in df.iterrows():
        steps.append(
            ReplayStep(
                features=np.array([row[c] for c in feature_cols], dtype=np.float32),
                outcome_pct=float(row["outcome_pct"]),
                mint=str(row["mint"]),
            )
        )
    return steps


def main() -> None:
    from stable_baselines3 import PPO

    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", default="models/ppo_latest.zip")
    p.add_argument("--steps", type=int, default=200_000)
    p.add_argument("--position-size-usd", type=float, default=50.0)
    args = p.parse_args()

    dataset = load_dataset(args.dataset)
    env = MemeReplayEnv(dataset, position_size_usd=args.position_size_usd)

    model = PPO("MlpPolicy", env, verbose=1, n_steps=512, batch_size=128, gamma=0.0)
    # gamma=0 because each episode is one decision — no future to discount.
    model.learn(total_timesteps=args.steps)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
