"""
Tests for the regime stress test — production risk chain under hostile
synthetic environments.

Invariants (see scripts/run_regime_stress_test.py docstring):
- I1 equity stays positive in every regime
- I2 exposure never exceeds starting capital
- I3 zero entry fills after a loss breaker has fired
- I4 liquidity_crisis blocks entries via spread/depth hard rejects
- I5 deterministic for a fixed seed
"""

import pytest

from polysignal.ingestion.market_regimes import REGIME_PARAMS, MarketRegime, regime_params
from scripts.run_regime_stress_test import StressConfig, run_regime_stress

ALL_REGIMES = list(MarketRegime)
STRESS_CONFIG = StressConfig(steps=40, markets=6)


@pytest.fixture(scope="module")
def stress_results():
    return {regime: run_regime_stress(regime, STRESS_CONFIG) for regime in ALL_REGIMES}


class TestRegimeParams:
    def test_all_regimes_have_params(self):
        assert set(REGIME_PARAMS) == set(MarketRegime)

    def test_liquidity_crisis_collapses_depth(self):
        params = regime_params(MarketRegime.LIQUIDITY_CRISIS)
        assert params.depth_multiplier < 0.2
        assert params.spread_multiplier > 2.0

    def test_trend_directions(self):
        assert regime_params(MarketRegime.TREND_UP).drift_per_step > 0
        assert regime_params(MarketRegime.TREND_DOWN).drift_per_step < 0
        assert regime_params(MarketRegime.RANGE).mean_reversion > 0


class TestRiskChainInvariants:
    def test_i1_equity_stays_positive(self, stress_results):
        for regime, result in stress_results.items():
            assert result.min_equity_usd > 0, f"{regime}: equity went to {result.min_equity_usd}"
            assert result.final_equity_usd > 0, f"{regime}: final equity {result.final_equity_usd}"

    def test_i2_exposure_within_capital(self, stress_results):
        for regime, result in stress_results.items():
            assert result.max_exposure_usd <= STRESS_CONFIG.starting_capital_usd, (
                f"{regime}: exposure {result.max_exposure_usd} exceeded capital"
            )

    def test_i3_no_fills_while_breaker_active(self, stress_results):
        """The precise invariant: no entry fill may happen in a step where a
        breaker condition is active on the account. (The consecutive-loss
        breaker legitimately resets on a winning close, so 'after first fire'
        would be the wrong assertion — a fill-while-active is a real bypass.)"""
        for regime, result in stress_results.items():
            assert result.entries_filled_while_breaker_active == 0, (
                f"{regime}: {result.entries_filled_while_breaker_active} fills "
                "while a breaker condition was active"
            )

    def test_i4_liquidity_crisis_blocks_entries(self, stress_results):
        result = stress_results[MarketRegime.LIQUIDITY_CRISIS]
        gate_reasons = {"spread_too_wide", "depth_too_thin"}
        assert gate_reasons & set(result.hard_rejects), (
            "liquidity_crisis should trigger spread/depth hard rejects"
        )
        assert result.entries_rejected > 0 or result.hard_rejects

    def test_trend_down_fires_loss_breaker(self, stress_results):
        result = stress_results[MarketRegime.TREND_DOWN]
        breakers = {
            "daily_loss_limit_breached",
            "weekly_loss_limit_breached",
            "consecutive_loss_limit_breached",
        }
        assert breakers & result.breakers_fired, (
            f"trend_down should fire a loss breaker, got {result.breakers_fired}"
        )
        assert result.step_breaker_first_fired is not None
        assert result.step_breaker_first_fired < STRESS_CONFIG.steps

    def test_activity_in_normal_regimes(self, stress_results):
        # The probe must actually trade in benign environments so the chain
        # is exercised (entries filled and positions closed).
        for regime in (MarketRegime.TREND_UP, MarketRegime.RANGE):
            result = stress_results[regime]
            assert result.entries_filled > 0, f"{regime}: no entries filled"
            assert result.exits_filled > 0, f"{regime}: no exits filled"


class TestDeterminism:
    def test_i5_two_runs_identical(self):
        a = run_regime_stress(MarketRegime.TREND_DOWN, STRESS_CONFIG)
        b = run_regime_stress(MarketRegime.TREND_DOWN, STRESS_CONFIG)
        assert a.final_equity_usd == pytest.approx(b.final_equity_usd)
        assert a.breakers_fired == b.breakers_fired
        assert a.entries_filled == b.entries_filled
        assert a.total_pnl_usd == pytest.approx(b.total_pnl_usd)
        assert [(t, round(e, 10)) for t, e in a.equity_curve] == [
            (t, round(e, 10)) for t, e in b.equity_curve
        ]
