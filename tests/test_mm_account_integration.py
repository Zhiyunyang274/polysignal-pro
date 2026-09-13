"""MarketMaker + AccountState + Risk Governor integration test.

Verifies that the three-tier risk limits (market, strategy, account) fire
correctly in a market-making context, using real AccountState ledger data
fed through RiskContext to the Risk Governor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from polysignal.execution.account_state import AccountState
from polysignal.models.risk import RiskAction, RiskContext
from polysignal.models.signal import Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor

UTC = UTC


class TestMMAccountIntegration:
    """Verify AccountState three-tier limits fire in a market-making context."""

    @staticmethod
    def _signal() -> Signal:
        return Signal(
            market_id="mm_1",
            market_title="MM test market",
            market_category="crypto",
            strategy_name="market_maker",
            side=SignalSide.YES,
            price=0.50,
        )

    def test_market_exposure_limit_fires(self):
        state = AccountState(starting_capital_usd=1000.0)
        state.record_open("mm_1", "market_maker", 35.0)  # > 3% of 1000 = 30
        governor = RiskGovernor(max_account_capital_usd=1000.0)
        context = RiskContext(
            **state.risk_context_fields("mm_1", "market_maker")
        )
        decision = governor.evaluate(self._signal(), context)
        assert "market_exposure_limit" in decision.hard_reject_reasons

    def test_strategy_exposure_limit_fires(self):
        state = AccountState(starting_capital_usd=1000.0)
        state.record_open("mm_1", "market_maker", 85.0)  # > 8% of 1000 = 80
        governor = RiskGovernor(max_account_capital_usd=1000.0)
        context = RiskContext(
            **state.risk_context_fields("mm_1", "market_maker")
        )
        decision = governor.evaluate(self._signal(), context)
        assert "strategy_exposure_limit" in decision.hard_reject_reasons

    def test_zero_exposure_passes(self):
        state = AccountState(starting_capital_usd=1000.0)
        governor = RiskGovernor(max_account_capital_usd=1000.0)
        context = RiskContext(
            **state.risk_context_fields("mm_1", "market_maker")
        )
        decision = governor.evaluate(self._signal(), context)
        assert "market_exposure_limit" not in decision.hard_reject_reasons
        assert "strategy_exposure_limit" not in decision.hard_reject_reasons

    def test_consecutive_losses_after_mm_cycle(self):
        """Simulate a MM cycle: buy → sell at loss ×3 → consecutive loss breaker fires."""
        state = AccountState(starting_capital_usd=1000.0)
        governor = RiskGovernor(max_account_capital_usd=1000.0, max_consecutive_losses=3)
        now = datetime.now(timezone.utc)

        for i in range(3):
            state.record_open(f"mm_{i}", "market_maker", 50.0)
            state.record_close(f"mm_{i}", -5.0, now=now)

        context = RiskContext(
            **state.risk_context_fields("mm_1", "market_maker", now=now)
        )
        decision = governor.evaluate(self._signal(), context)
        assert decision.action == RiskAction.HARD_REJECT
        assert "consecutive_loss_limit_breached" in decision.hard_reject_reasons
