"""
Tests for performance metrics - account-level trading statistics.

Values are hand-computed against small deterministic datasets.
"""

from datetime import UTC, datetime, timedelta
from statistics import mean

import pytest

from polysignal.utils.performance_metrics import (
    compute_performance_metrics,
    max_consecutive,
    max_drawdown,
    period_returns,
)

UTC = UTC
BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def curve(values: list[float], step_hours: float = 24.0) -> list[tuple[datetime, float]]:
    return [(BASE + timedelta(hours=step_hours * i), v) for i, v in enumerate(values)]


class TestPeriodReturns:
    def test_simple_returns(self):
        returns = period_returns(curve([100.0, 110.0, 99.0]))
        assert returns[0] == pytest.approx(0.10)
        assert returns[1] == pytest.approx(-0.10)
        assert len(returns) == 2

    def test_nonpositive_previous_equity_guarded(self):
        returns = period_returns(curve([0.0, 50.0]))
        assert returns == [0.0]


class TestDrawdown:
    def test_max_drawdown_peak_to_trough(self):
        dd = max_drawdown(curve([100.0, 110.0, 99.0, 105.0]))
        assert dd == pytest.approx((99.0 - 110.0) / 110.0)

    def test_no_drawdown(self):
        assert max_drawdown(curve([100.0, 120.0, 130.0])) == 0.0

    def test_empty_curve(self):
        assert max_drawdown([]) is None


class TestConsecutive:
    def test_streaks(self):
        assert max_consecutive([1, -1, -1, -1, 2, -1], wins=False) == 3
        assert max_consecutive([1, 1, -1, 2, 2], wins=True) == 2
        assert max_consecutive([0, -1, 0], wins=False) == 1


class TestComputeMetrics:
    def test_empty_inputs(self):
        m = compute_performance_metrics([], [])
        assert m.point_count == 0
        assert m.total_return_pct is None
        assert m.sharpe_ratio is None
        assert m.trade_count == 0
        assert m.win_rate is None

    def test_return_and_drawdown(self):
        m = compute_performance_metrics(curve([100.0, 110.0, 99.0, 105.0]), [])
        assert m.total_return_pct == pytest.approx(5.0)
        assert m.max_drawdown_pct == pytest.approx(-10.0)
        assert m.start_equity_usd == 100.0
        assert m.end_equity_usd == 105.0

    def test_annualized_return_one_year_span(self):
        # 100 -> 200 in exactly 365 days => 100% total, 100% annualized
        values = [(BASE, 100.0), (BASE + timedelta(days=182), 150.0),
                  (BASE + timedelta(days=365), 200.0)]
        m = compute_performance_metrics(values, [])
        assert m.annualized_return_pct == pytest.approx(100.0, rel=1e-3)

    def test_sharpe_sortino_hand_computed(self):
        # Daily equity with returns 10%, -10%, +6.06% (from 100/110/99/105 curve)
        m = compute_performance_metrics(curve([100.0, 110.0, 99.0, 105.0]), [])
        from statistics import mean, pstdev

        returns = [0.10, -0.10, 6.0 / 99.0]
        ppy = 365.0  # daily points
        expected_sharpe = mean(returns) / pstdev(returns) * (ppy**0.5)
        downside = [min(r, 0.0) for r in returns]
        dstd = (mean([d**2 for d in downside])) ** 0.5
        expected_sortino = mean(returns) / dstd * (ppy**0.5)
        assert m.periods_per_year == pytest.approx(365.0)
        assert m.sharpe_ratio == pytest.approx(expected_sharpe)
        assert m.sortino_ratio == pytest.approx(expected_sortino)

    def test_zero_volatility_sharpe_none(self):
        # Perfectly flat equity => zero returns => zero volatility => None
        m = compute_performance_metrics(curve([100.0, 100.0, 100.0, 100.0]), [])
        assert m.sharpe_ratio is None
        assert m.sortino_ratio is None

    def test_trade_statistics(self):
        pnls = [10.0, -5.0, 20.0, -5.0, -5.0, -5.0]
        m = compute_performance_metrics(curve([100.0, 110.0]), pnls)
        assert m.trade_count == 6
        assert m.win_count == 2
        assert m.loss_count == 4
        assert m.win_rate == pytest.approx(2 / 6 * 100.0)
        assert m.total_pnl_usd == pytest.approx(10.0)
        assert m.gross_profit_usd == pytest.approx(30.0)
        assert m.gross_loss_usd == pytest.approx(-20.0)
        assert m.profit_factor == pytest.approx(1.5)
        assert m.payoff_ratio == pytest.approx(3.0)
        assert m.avg_win_usd == pytest.approx(15.0)
        assert m.avg_loss_usd == pytest.approx(-5.0)
        assert m.max_consecutive_losses == 3
        assert m.max_consecutive_wins == 1

    def test_no_losses_profit_factor_none(self):
        m = compute_performance_metrics([], [5.0, 10.0])
        assert m.profit_factor is None
        assert m.payoff_ratio is None

    def test_turnover_and_exposure(self):
        eq = curve([100.0, 200.0, 100.0])
        exposure = [(t, e * 0.5) for t, e in eq]
        m = compute_performance_metrics(eq, [], traded_notional_usd=300.0,
                                        exposure_curve=exposure)
        assert m.turnover_x == pytest.approx(300.0 / (mean([100.0, 200.0, 100.0])))
        assert m.avg_exposure_pct == pytest.approx(50.0)

    def test_naive_timestamps_accepted(self):
        naive_curve = [(t.replace(tzinfo=None), v) for t, v in curve([100.0, 110.0])]
        m = compute_performance_metrics(naive_curve, [])
        assert m.total_return_pct == pytest.approx(10.0)
        assert m.annualized_return_pct is not None
