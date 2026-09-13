"""Tests for the real-time lag detection module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysignal.monitoring.real_time_lag import (
    RealTimeMonitor,
    RealTimeMonitorConfig,
    _norm_cdf,
)


class TestNormCDF:
    def test_extremes(self):
        assert _norm_cdf(-5) == pytest.approx(0.0, abs=0.001)
        assert _norm_cdf(0) == pytest.approx(0.5)
        assert _norm_cdf(5) == pytest.approx(1.0, abs=0.001)

    def test_monotonic(self):
        values = [_norm_cdf(x) for x in range(-3, 4)]
        assert values == sorted(values)


class TestComputeModelProbability:
    def setup_method(self):
        self.monitor = RealTimeMonitor(RealTimeMonitorConfig())

    def test_at_the_money(self):
        prob = self.monitor.compute_model_probability(
            spot=100, threshold=100, barrier_direction="up",
            time_to_expiry_hours=24 * 30, annual_vol=0.60,
        )
        assert prob > 0.5  # ATM one-touch should be high (barrier at current price)

    def test_far_above_barrier_up(self):
        """Spot way above threshold for 'up' barrier → very high probability."""
        prob = self.monitor.compute_model_probability(
            spot=200, threshold=100, barrier_direction="up",
            time_to_expiry_hours=24 * 30, annual_vol=0.60,
        )
        assert prob > 0.9

    def test_far_below_barrier_up(self):
        """Spot way below threshold for 'up' barrier → very low probability."""
        prob = self.monitor.compute_model_probability(
            spot=50, threshold=200, barrier_direction="up",
            time_to_expiry_hours=24 * 30, annual_vol=0.60,
        )
        assert prob < 0.1

    def test_down_barrier_mirrors_up(self):
        """Down barrier with spot far above → low probability (symmetric)."""
        prob = self.monitor.compute_model_probability(
            spot=200, threshold=100, barrier_direction="down",
            time_to_expiry_hours=24 * 30, annual_vol=0.60,
        )
        assert prob < 0.3

    def test_zero_time_returns_half(self):
        prob = self.monitor.compute_model_probability(
            spot=100, threshold=100, barrier_direction="up",
            time_to_expiry_hours=0, annual_vol=0.60,
        )
        assert prob == 0.5


class TestDetectLag:
    def setup_method(self):
        self.monitor = RealTimeMonitor(RealTimeMonitorConfig(edge_threshold_bps=50))
        self.now = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)

    def test_no_lag_when_model_and_market_agree(self):
        obs = self.monitor.detect_lag(
            market_id="m1", asset="BTC", threshold_price=100,
            barrier_direction="up", spot_price=100, spot_source="test",
            market_yes_bid=0.48, market_yes_ask=0.52,
            time_to_expiry_hours=24, annual_vol=0.60, now=self.now,
        )
        # ATM: model prob ~0.85+ (barrier at current price), market mid 0.50
        # edge = ~0.35 = 7000+ bps >> 50 bps threshold -> significant
        assert obs.is_significant is True

    def test_lag_detected_when_model_above_market(self):
        """Spot just below barrier → model says high probability, market low."""
        obs = self.monitor.detect_lag(
            market_id="m1", asset="BTC", threshold_price=102,
            barrier_direction="up", spot_price=100, spot_source="test",
            market_yes_bid=0.10, market_yes_ask=0.12,
            time_to_expiry_hours=24, annual_vol=0.60, now=self.now,
        )
        assert obs.edge > 0
        assert obs.is_significant is True

    def test_observations_accumulate(self):
        for i in range(5):
            self.monitor.detect_lag(
                market_id=f"m{i}", asset="BTC", threshold_price=100,
                barrier_direction="up", spot_price=100, spot_source="test",
                market_yes_bid=0.48, market_yes_ask=0.52,
                time_to_expiry_hours=24, annual_vol=0.60,
                now=datetime(2026, 9, 13, 12, i, 0, tzinfo=UTC),
            )
        assert len(self.monitor.observations) == 5

    def test_significant_observations_filter(self):
        for i in range(3):
            self.monitor.detect_lag(
                market_id=f"m{i}", asset="BTC", threshold_price=100,
                barrier_direction="up", spot_price=100, spot_source="test",
                market_yes_bid=0.48, market_yes_ask=0.52,
                time_to_expiry_hours=24, annual_vol=0.60,
                now=datetime(2026, 9, 13, 12, i, 0, tzinfo=UTC),
            )
        # One with large divergence
        self.monitor.detect_lag(
            market_id="m_big", asset="BTC", threshold_price=105,
            barrier_direction="up", spot_price=100, spot_source="test",
            market_yes_bid=0.10, market_yes_ask=0.12,
            time_to_expiry_hours=24, annual_vol=0.60,
            now=datetime(2026, 9, 13, 12, 5, 0, tzinfo=UTC),
        )
        significant = self.monitor.get_significant_observations()
        assert len(significant) >= 1
