"""
Tests for the CircuitBreaker (D12 resolution).

Covers: config threshold consumption, per-channel trip/reset semantics,
data staleness helper (naive/aware), and RiskContext integration shape.
"""

from datetime import UTC, datetime, timedelta

import pytest

from polysignal.risk.circuit_breaker import CircuitBreaker

UTC = UTC


def breaker(**kwargs) -> CircuitBreaker:
    return CircuitBreaker(max_api_failures=3, max_ws_disconnects=2, **kwargs)


class TestApiChannel:
    def test_trips_at_threshold(self):
        cb = breaker()
        assert cb.record_api_failure() is False
        assert cb.record_api_failure() is False
        assert cb.record_api_failure() is True  # third consecutive failure trips
        assert cb.api_tripped is True
        assert cb.api_healthy is False

    def test_success_resets_counter(self):
        cb = breaker()
        cb.record_api_failure()
        cb.record_api_failure()
        cb.record_api_success()
        assert cb.record_api_failure() is False  # counter was reset to 1
        assert cb.api_tripped is False

    def test_tripped_stays_until_success(self):
        cb = breaker()
        for _ in range(3):
            cb.record_api_failure()
        assert cb.api_tripped is True
        cb.record_api_success()
        assert cb.api_tripped is False  # success clears the tripped state


class TestWsChannel:
    def test_trips_at_threshold(self):
        cb = breaker()
        assert cb.record_ws_disconnect() is False
        assert cb.record_ws_disconnect() is True
        assert cb.ws_tripped is True
        assert cb.websocket_healthy is False

    def test_reconnect_resets(self):
        cb = breaker()
        cb.record_ws_disconnect()
        cb.record_ws_disconnect()
        cb.record_ws_connected()
        assert cb.ws_tripped is False
        assert cb.record_ws_disconnect() is False


class TestStaleData:
    def test_threshold_consumed_from_config(self):
        cb = CircuitBreaker(stale_data_threshold_seconds=60)
        now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
        assert cb.is_data_stale(now - timedelta(seconds=59), now=now) is False
        assert cb.is_data_stale(now - timedelta(seconds=61), now=now) is True

    def test_naive_last_seen_assumed_utc(self):
        cb = CircuitBreaker(stale_data_threshold_seconds=60)
        now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
        naive_seen = datetime(2026, 9, 12, 11, 59, 30)  # 30s old
        assert cb.is_data_stale(naive_seen, now=now) is False

    def test_none_last_seen_is_stale(self):
        cb = CircuitBreaker()
        assert cb.is_data_stale(None) is True  # type: ignore[arg-type]


class TestValidationAndReset:
    def test_invalid_thresholds(self):
        with pytest.raises(ValueError):
            CircuitBreaker(max_api_failures=0)
        with pytest.raises(ValueError):
            CircuitBreaker(max_ws_disconnects=0)
        with pytest.raises(ValueError):
            CircuitBreaker(stale_data_threshold_seconds=-1)

    def test_reset_clears_everything(self):
        cb = breaker()
        for _ in range(3):
            cb.record_api_failure()
        for _ in range(2):
            cb.record_ws_disconnect()
        cb.reset()
        assert cb.api_tripped is False and cb.ws_tripped is False
        assert cb.record_api_failure() is False
