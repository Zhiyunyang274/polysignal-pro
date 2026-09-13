"""
Tests for the A/B comparison framework.

Verdict rules are tested with synthetic per-regime rows (deterministic by
construction); one end-to-end smoke run checks the harness wiring. The rules
implement the house rule: no obvious advantage -> no merge.
"""

import pytest

from polysignal.ingestion.market_regimes import MarketRegime
from scripts.run_ab_comparison import (
    ABResult,
    StrategyVariant,
    _apply_verdict_rules,
    run_ab_comparison,
)
from scripts.run_regime_stress_test import StressConfig


def row(regime: str, *, base_pnl: float, cand_pnl: float, base_dd: float = -5.0,
        cand_dd: float = -5.0, cand_breaker_bypass: bool = False) -> dict:
    """Minimal per-regime row matching summarize()'s shape."""

    def side(pnl: float, dd: float, bypass: bool = False) -> dict:
        return {
            "entries_filled": 5,
            "total_pnl_usd": pnl,
            "max_drawdown_pct": dd,
            "final_equity_usd": 1000.0 + pnl,
            "breakers_fired": [],
            "entries_filled_while_breaker_active": 1 if bypass else 0,
        }

    return {
        "regime": regime,
        "baseline": side(base_pnl, base_dd),
        "candidate": side(cand_pnl, cand_dd, cand_breaker_bypass),
    }


def make_result(rows: list[dict]) -> ABResult:
    result = ABResult(baseline_name="base", candidate_name="cand")
    result.per_regime = rows
    result.baseline_total_pnl = sum(r["baseline"]["total_pnl_usd"] for r in rows)
    result.candidate_total_pnl = sum(r["candidate"]["total_pnl_usd"] for r in rows)
    _apply_verdict_rules(result)
    return result


class TestVerdictRules:
    def test_identical_variants_rejected_no_advantage(self):
        result = make_result(
            [row("trend_up", base_pnl=10.0, cand_pnl=10.0)]
        )
        assert result.verdict == "REJECT"
        assert result.rules["R1_aggregate_return"] is False

    def test_candidate_better_everywhere_kept(self):
        result = make_result(
            [
                row("trend_up", base_pnl=10.0, cand_pnl=20.0),
                row("range", base_pnl=-5.0, cand_pnl=-1.0),
                row("trend_down", base_pnl=-30.0, cand_pnl=-15.0),
            ]
        )
        assert result.verdict == "KEEP_ELIGIBLE"
        assert all(
            ok for name, ok in result.rules.items() if name != "R3_detail"
        )

    def test_candidate_worse_in_most_regimes_rejected(self):
        # Aggregate can still be positive via one big regime, but R3 generalization fails.
        result = make_result(
            [
                row("trend_up", base_pnl=10.0, cand_pnl=100.0),
                row("range", base_pnl=-5.0, cand_pnl=-50.0),
                row("trend_down", base_pnl=-20.0, cand_pnl=-90.0),
                row("high_vol", base_pnl=-5.0, cand_pnl=-40.0),
            ]
        )
        assert result.verdict == "REJECT"
        assert result.rules["R3_generalization"] is False

    def test_drawdown_degradation_rejects(self):
        result = make_result(
            [
                row("trend_up", base_pnl=10.0, cand_pnl=30.0, base_dd=-5.0, cand_dd=-7.0),
                row("range", base_pnl=10.0, cand_pnl=30.0, base_dd=-10.0, cand_dd=-30.0),
            ]
        )
        assert result.verdict == "REJECT"
        assert result.rules["R2_drawdown_not_worse"] is False

    def test_breaker_bypass_rejects(self):
        result = make_result(
            [
                row("trend_up", base_pnl=10.0, cand_pnl=30.0, cand_breaker_bypass=True),
            ]
        )
        assert result.verdict == "REJECT"
        assert result.rules["R4_no_breaker_bypass"] is False

    def test_small_advantage_below_threshold_rejected(self):
        # +4% relative aggregate: within the noise band -> R5 rejects it even
        # though R1 (strict) and R3 (generalization) pass.
        result = make_result(
            [
                row("trend_up", base_pnl=100.0, cand_pnl=104.0),
                row("range", base_pnl=50.0, cand_pnl=52.0),
            ]
        )
        assert result.rules["R3_generalization"] is True
        assert result.rules["R1_aggregate_return"] is True
        assert result.rules["R5_obvious_advantage"] is False
        assert result.verdict == "REJECT"


class TestEndToEnd:
    def test_tiny_run_completes_and_deterministic(self):
        config = StressConfig(steps=8, markets=3)
        baseline = StrategyVariant(name="b", stop_loss_pct=0.15, take_profit_pct=0.25,
                                   max_holding_steps=5)
        candidate = StrategyVariant(name="c", stop_loss_pct=0.10, take_profit_pct=0.30,
                                    max_holding_steps=5)

        first = run_ab_comparison(
            baseline, candidate, config, regimes=[MarketRegime.TREND_UP, MarketRegime.RANGE]
        )
        second = run_ab_comparison(
            baseline, candidate, config, regimes=[MarketRegime.TREND_UP, MarketRegime.RANGE]
        )

        assert first.verdict in {"KEEP_ELIGIBLE", "REJECT"}
        assert len(first.per_regime) == 2
        assert first.candidate_total_pnl == pytest.approx(second.candidate_total_pnl)
        assert first.baseline_total_pnl == pytest.approx(second.baseline_total_pnl)
        assert first.rules == second.rules
        # determinism: identical verdicts on identical windows
        assert first.verdict == second.verdict
