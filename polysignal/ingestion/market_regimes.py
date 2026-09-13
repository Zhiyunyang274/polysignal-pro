"""

Market Regimes - Parameterized synthetic market environments for stress testing

IMPORTANT:
- Research/testing only. Regime parameters shape synthetic data; they make no
  claim about any real market's current or future behaviour.
- Consumers must stay deterministic: a regime path is a pure function of the
  seed and the step index, so stress runs are repeatable and comparable.

Regimes (user phase 6 requirement):
- trend_up / trend_down: persistent drift, moderate spread
- range: mean reversion around a anchor price
- high_vol: large per-step jumps and wide spreads
- liquidity_crisis: collapsed depth and wide spreads (books fail depth gates)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MarketRegime(str, Enum):
    """Synthetic market environment for stress testing."""

    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    LIQUIDITY_CRISIS = "liquidity_crisis"


@dataclass(frozen=True)
class MarketRegimeParams:
    """Deterministic shaping parameters for one regime.

    Attributes:
        drift_per_step: additive drift applied to the YES mid each step.
        vol_per_step: scale of the per-step random innovation.
        mean_reversion: pull strength toward the anchor (0 = pure random walk).
        spread_multiplier: multiplier on the base 0.01-0.05 spread range.
        depth_multiplier: multiplier on the base 50-500 USD depth range.
    """

    drift_per_step: float = 0.0
    vol_per_step: float = 0.02
    mean_reversion: float = 0.0
    spread_multiplier: float = 1.0
    depth_multiplier: float = 1.0


REGIME_PARAMS: dict[MarketRegime, MarketRegimeParams] = {
    MarketRegime.TREND_UP: MarketRegimeParams(
        drift_per_step=0.006,
        vol_per_step=0.012,
    ),
    MarketRegime.TREND_DOWN: MarketRegimeParams(
        drift_per_step=-0.006,
        vol_per_step=0.012,
    ),
    MarketRegime.RANGE: MarketRegimeParams(
        drift_per_step=0.0,
        vol_per_step=0.02,
        mean_reversion=0.15,
    ),
    MarketRegime.HIGH_VOL: MarketRegimeParams(
        drift_per_step=0.0,
        vol_per_step=0.08,
        spread_multiplier=2.5,
    ),
    MarketRegime.LIQUIDITY_CRISIS: MarketRegimeParams(
        drift_per_step=-0.004,
        vol_per_step=0.05,
        spread_multiplier=3.0,
        depth_multiplier=0.1,
    ),
}


def regime_params(regime: MarketRegime) -> MarketRegimeParams:
    """Look up the shaping parameters for a regime."""
    return REGIME_PARAMS[regime]
