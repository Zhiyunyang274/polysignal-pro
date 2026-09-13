"""
Tests for AccountState - paper/simulation account ledger.

Covers:
- initial state and capital accounting
- open/close lifecycle (cash, exposure, attribution)
- consecutive-loss tracking
- daily/weekly realized PnL windows (deterministic via injected timestamps)
- RiskContext field feed
- integration: daily loss limit hard rejection through Risk Governor
"""

from datetime import UTC, datetime, timedelta

import pytest

from polysignal.execution.account_state import AccountState
from polysignal.models.risk import RiskAction, RiskContext
from polysignal.models.signal import Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor

UTC = UTC


def ts(days_ago: int = 0, hours: int = 0) -> datetime:
    """Fixed base timestamp: 2026-09-10 12:00 UTC minus offsets."""
    base = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
    return base - timedelta(days=days_ago, hours=hours)


class TestInitialState:
    def test_starting_capital(self):
        state = AccountState(starting_capital_usd=10000.0)
        assert state.cash_usd == 10000.0
        assert state.realized_pnl_usd == 0.0
        assert state.consecutive_losses == 0
        assert state.total_exposure_usd == 0.0
        assert state.equity_usd == 10000.0
        assert state.get_open_positions() == []
        assert state.get_closed_trades() == []

    def test_invalid_capital_rejected(self):
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                AccountState(starting_capital_usd=bad)


class TestRecordOpen:
    def test_open_reduces_cash_and_tracks_exposure(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "yes_no_mispricing", 250.0)

        assert state.cash_usd == 9750.0
        assert state.market_exposure_usd("m1") == 250.0
        assert state.strategy_exposure_usd("yes_no_mispricing") == 250.0
        assert state.total_exposure_usd == 250.0
        assert state.equity_usd == 10000.0

    def test_open_accumulates_same_market(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "yes_no_mispricing", 100.0)
        state.record_open("m1", "yes_no_mispricing", 50.0)

        assert len(state.get_open_positions()) == 1
        assert state.market_exposure_usd("m1") == 150.0
        assert state.cash_usd == 9850.0

    def test_open_second_market_keeps_first_attribution(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "yes_no_mispricing", 100.0)
        state.record_open("m2", "wallet_consensus", 200.0)

        assert state.strategy_exposure_usd("yes_no_mispricing") == 100.0
        assert state.strategy_exposure_usd("wallet_consensus") == 200.0

    def test_open_exceeding_cash_rejected(self):
        state = AccountState(starting_capital_usd=100.0)
        with pytest.raises(ValueError, match="exceeds available cash"):
            state.record_open("m1", "yes_no_mispricing", 100.01)

    def test_open_invalid_inputs_rejected(self):
        state = AccountState(starting_capital_usd=100.0)
        with pytest.raises(ValueError):
            state.record_open("", "yes_no_mispricing", 10.0)
        with pytest.raises(ValueError):
            state.record_open("m1", "", 10.0)
        for bad_notional in (0.0, -5.0, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                state.record_open("m1", "yes_no_mispricing", bad_notional)


class TestRecordClose:
    def test_close_returns_cash_with_profit(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "yes_no_mispricing", 250.0)
        state.record_close("m1", 25.0, now=ts())

        assert state.cash_usd == 10000.0 + 25.0
        assert state.realized_pnl_usd == 25.0
        assert state.market_exposure_usd("m1") == 0.0
        assert state.total_exposure_usd == 0.0
        assert state.consecutive_losses == 0
        assert len(state.get_closed_trades()) == 1

    def test_close_with_loss(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "yes_no_mispricing", 250.0)
        state.record_close("m1", -80.0, now=ts())

        assert state.cash_usd == 10000.0 - 80.0
        assert state.realized_pnl_usd == -80.0
        assert state.consecutive_losses == 1

    def test_close_unknown_market_rejected(self):
        state = AccountState(starting_capital_usd=10000.0)
        with pytest.raises(ValueError, match="No open position"):
            state.record_close("m_missing", 0.0, now=ts())

    def test_close_non_finite_pnl_rejected(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "yes_no_mispricing", 100.0)
        with pytest.raises(ValueError):
            state.record_close("m1", float("nan"), now=ts())


class TestConsecutiveLosses:
    def test_loss_win_loss_sequence(self):
        state = AccountState(starting_capital_usd=10000.0)

        state.record_open("m1", "s", 10.0)
        state.record_close("m1", -5.0, now=ts())
        assert state.consecutive_losses == 1

        state.record_open("m2", "s", 10.0)
        state.record_close("m2", 7.0, now=ts())
        assert state.consecutive_losses == 0

        state.record_open("m3", "s", 10.0)
        state.record_close("m3", -1.0, now=ts())
        assert state.consecutive_losses == 1

    def test_zero_pnl_leaves_streak_unchanged(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "s", 10.0)
        state.record_close("m1", -5.0, now=ts())
        state.record_open("m2", "s", 10.0)
        state.record_close("m2", 0.0, now=ts())
        assert state.consecutive_losses == 1

    def test_multiple_losses_accumulate(self):
        state = AccountState(starting_capital_usd=10000.0)
        for i in range(4):
            market = f"m{i}"
            state.record_open(market, "s", 10.0)
            state.record_close(market, -1.0, now=ts())
        assert state.consecutive_losses == 4


class TestPnlWindows:
    def test_daily_window_excludes_other_days(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "s", 10.0)
        state.record_close("m1", -3.0, now=ts(days_ago=0))  # today (relative to ts())
        state.record_open("m2", "s", 10.0)
        state.record_close("m2", -2.0, now=ts(days_ago=1))  # yesterday

        # "now" is the base instant of ts(): only the first trade is today.
        reference = ts()
        assert state.daily_pnl_usd(now=reference) == -3.0

    def test_daily_window_rolls_over_at_utc_midnight(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "s", 10.0)
        state.record_close("m1", -3.0, now=datetime(2026, 9, 9, 23, 59, tzinfo=UTC))
        state.record_open("m2", "s", 10.0)
        state.record_close("m2", -2.0, now=datetime(2026, 9, 10, 0, 1, tzinfo=UTC))

        assert state.daily_pnl_usd(now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC)) == -2.0

    def test_weekly_window_iso_week(self):
        state = AccountState(starting_capital_usd=10000.0)
        # ISO weeks start on Monday: 2026-09-07 (Mon) and 2026-09-10 (Thu) are
        # week 37; 2026-09-06 (Sun) belongs to week 36.
        state.record_open("m1", "s", 10.0)
        state.record_close("m1", -4.0, now=datetime(2026, 9, 4, 12, 0, tzinfo=UTC))
        state.record_open("m2", "s", 10.0)
        state.record_close("m2", -1.0, now=datetime(2026, 9, 8, 12, 0, tzinfo=UTC))

        assert state.weekly_pnl_usd(now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC)) == -1.0

    def test_naive_timestamp_treated_as_utc(self):
        state = AccountState(starting_capital_usd=10000.0)
        state.record_open("m1", "s", 10.0)
        naive = datetime(2026, 9, 10, 12, 0, 0)  # no tzinfo
        state.record_close("m1", -1.0, now=naive)

        assert state.daily_pnl_usd(now=naive.replace(tzinfo=UTC)) == -1.0


class TestRiskContextFields:
    def test_fields_before_and_after_activity(self):
        state = AccountState(starting_capital_usd=10000.0)
        reference = ts()

        fields = state.risk_context_fields("m1", "yes_no_mispricing", now=reference)
        assert fields == {
            "account_balance_usd": 10000.0,
            "daily_pnl_usd": 0.0,
            "weekly_pnl_usd": 0.0,
            "consecutive_losses": 0,
            "current_market_exposure_usd": 0.0,
            "current_strategy_exposure_usd": 0.0,
        }

        state.record_open("m1", "yes_no_mispricing", 300.0)
        state.record_open("m2", "yes_no_mispricing", 200.0)
        state.record_close("m2", -50.0, now=reference)

        fields = state.risk_context_fields("m1", "yes_no_mispricing", now=reference)
        assert fields["account_balance_usd"] == pytest.approx(10000.0 - 50.0)
        assert fields["daily_pnl_usd"] == -50.0
        assert fields["weekly_pnl_usd"] == -50.0
        assert fields["consecutive_losses"] == 1
        assert fields["current_market_exposure_usd"] == 300.0
        assert fields["current_strategy_exposure_usd"] == 300.0


class TestRiskGovernorIntegration:
    """The point of AccountState: loss-limit hard rejections must actually fire."""

    @staticmethod
    def _make_signal() -> Signal:
        return Signal(
            market_id="m1",
            market_title="Test market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.YES,
            price=0.55,
        )

    def _make_governor(self) -> RiskGovernor:
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
            max_account_capital_usd=100.0,
            daily_max_loss_pct=0.03,   # daily limit = 3.0 USD
            weekly_max_loss_pct=0.08,  # weekly limit = 8.0 USD
            max_consecutive_losses=3,
        )

    def _build_context(self, state: AccountState, now: datetime | None = None) -> RiskContext:
        return RiskContext(
            live_trading_enabled=False,
            allow_auto_execution=False,
            api_healthy=True,
            websocket_healthy=True,
            **state.risk_context_fields("m1", "yes_no_mispricing", now=now),
        )

    def test_breach_fires_after_daily_losses(self):
        state = AccountState(starting_capital_usd=100.0)
        governor = self._make_governor()
        reference = ts()

        # Fresh account: signal passes the loss-limit checks.
        decision = governor.evaluate(self._make_signal(), self._build_context(state, reference))
        assert "daily_loss_limit_breached" not in decision.hard_reject_reasons

        # Two losing days inside today's window beyond the 3.0 daily limit.
        state.record_open("m2", "s", 10.0)
        state.record_close("m2", -2.0, now=reference)
        state.record_open("m3", "s", 10.0)
        state.record_close("m3", -2.0, now=reference)

        decision = governor.evaluate(self._make_signal(), self._build_context(state, reference))
        assert decision.action == RiskAction.HARD_REJECT
        assert "daily_loss_limit_breached" in decision.hard_reject_reasons

    def test_consecutive_losses_breach_fires(self):
        state = AccountState(starting_capital_usd=10000.0)
        governor = self._make_governor()
        reference = ts()

        for i in range(3):
            state.record_open(f"m{i}", "s", 10.0)
            state.record_close(f"m{i}", -1.0, now=reference)

        decision = governor.evaluate(self._make_signal(), self._build_context(state, reference))
        assert decision.action == RiskAction.HARD_REJECT
        assert "consecutive_loss_limit_breached" in decision.hard_reject_reasons

    def test_weekly_breach_fires(self):
        state = AccountState(starting_capital_usd=100.0)
        governor = self._make_governor()
        reference = ts()

        # 10.0 total loss this week, two per UTC day so every daily window
        # stays under the 3.0 daily limit while the week breaches 8.0.
        # (Mon 09-07 .. Fri 09-11 are all ISO week 37.)
        day_losses = {
            datetime(2026, 9, 7, 12, 0, tzinfo=UTC): -2.0,
            datetime(2026, 9, 8, 12, 0, tzinfo=UTC): -2.0,
            datetime(2026, 9, 9, 12, 0, tzinfo=UTC): -2.0,
            datetime(2026, 9, 10, 12, 0, tzinfo=UTC): -2.0,
            datetime(2026, 9, 11, 12, 0, tzinfo=UTC): -2.0,
        }
        for i, (close_time, pnl) in enumerate(sorted(day_losses.items())):
            market = f"m{i}"
            state.record_open(market, "s", 10.0)
            state.record_close(market, pnl, now=close_time)

        decision = governor.evaluate(self._make_signal(), self._build_context(state, reference))
        assert decision.action == RiskAction.HARD_REJECT
        assert "daily_loss_limit_breached" not in decision.hard_reject_reasons
        assert "weekly_loss_limit_breached" in decision.hard_reject_reasons
