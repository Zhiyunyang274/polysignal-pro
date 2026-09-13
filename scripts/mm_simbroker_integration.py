"""MarketMaker + SimBroker integration: dual-side quoting with real execution costs.

Read-only research: MarketMaker generates quotes around the fair value and
SimBroker simulates fills with L2 depth, fees, and latency. This tests whether
spread capture survives realistic execution costs.

ADR-030: shift from directional trading to market making.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from polysignal.execution.account_state import AccountState
from polysignal.execution.market_maker import InventoryTracker, MarketMaker, MarketMakerConfig
from polysignal.execution.sim_broker import SimBroker, SimOrderStatus
from polysignal.ingestion.market_regimes import MarketRegime, regime_params
from polysignal.shadow.execution_cost import L2Level

BASE_TIME = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


@dataclass
class MMIntegrationConfig:
    steps: int = 120
    fair_start: float = 0.50
    half_spread_pct: float = 0.03
    inventory_limit: float = 100.0
    skew_factor: float = 0.5
    order_size: float = 10.0
    fee_bps: float = 10.0
    seed: int = 42


@dataclass
class MMIntegrationResult:
    regime: MarketRegime
    steps: int
    quotes_generated: int = 0
    fills_bid: int = 0
    fills_ask: int = 0
    total_fills: int = 0
    final_inventory: float = 0.0
    max_abs_inventory: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    final_equity: float = 0.0
    skipped: int = 0
    equity_curve: list[float] = field(default_factory=list)


def _make_l2_levels(price: float, size: float) -> list[L2Level]:
    """Single-level L2 book at the given price."""
    return [L2Level(price=max(0.01, min(0.99, price)), size=max(1.0, size))]


def run_mm_integration(regime: MarketRegime, config: MMIntegrationConfig) -> MMIntegrationResult:
    """Simulate market making in one regime with SimBroker fills."""
    result = MMIntegrationResult(regime=regime, steps=config.steps)
    params = regime_params(regime)

    seed = hash(regime.value) & 0x7FFFFFFF
    state = seed

    def next_rand() -> float:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF

    account = AccountState(starting_capital_usd=1000.0)
    broker = SimBroker(account, fee_bps=config.fee_bps,
                       submission_latency_seconds=0.5, max_quote_age_seconds=120)
    mm = MarketMaker(MarketMakerConfig(
        half_spread_pct=config.half_spread_pct,
        inventory_limit=config.inventory_limit,
        skew_factor=config.skew_factor,
        order_size=config.order_size,
        max_inventory_skew=0.05,
    ))
    tracker = InventoryTracker()

    fair = config.fair_start
    total_fees = 0.0

    for step in range(config.steps):
        now = BASE_TIME + timedelta(minutes=step)
        innovation = (next_rand() - 0.5) * 2 * params.vol_per_step
        fair = max(0.05, min(0.95, fair + params.drift_per_step + innovation +
                             params.mean_reversion * (config.fair_start - fair)))
        market_price = max(0.01, min(0.99, fair + (next_rand() - 0.5) * params.vol_per_step))

        # Volatility for dynamic spread (higher in volatile regimes)
        vol = params.vol_per_step
        quotes = mm.compute_quotes(fair_value=fair, inventory=tracker.inventory, volatility=vol)
        result.quotes_generated += 1

        if quotes.skipped:
            result.skipped += 1
            result.equity_curve.append(account.equity_usd)
            continue

        # Simulate market sell hitting our bid → we buy YES
        if market_price <= quotes.bid_price:
            bid_book = _make_l2_levels(quotes.bid_price, 500)
            order = broker.submit_buy(
                market_id="mm_test", strategy_name="mm_stress",
                asks=bid_book,
                notional_usd=config.order_size * quotes.bid_price,
                limit_price=quotes.bid_price, now=now, quote_timestamp=now,
            )
            if order.status != SimOrderStatus.REJECTED:
                tracker.on_buy_fill(quotes.bid_price, order.filled_shares)
                result.fills_bid += 1
                total_fees += order.fee_usd

        # Simulate market buy lifting our ask → we sell YES
        if market_price >= quotes.ask_price and tracker.inventory >= config.order_size:
            ask_book = _make_l2_levels(quotes.ask_price, 500)
            order = broker.submit_sell(
                market_id="mm_test", bids=ask_book,
                shares=tracker.inventory, limit_price=quotes.ask_price,
                now=now, quote_timestamp=now,
            )
            if order.status != SimOrderStatus.REJECTED:
                tracker.on_sell_fill(quotes.ask_price, order.filled_shares)
                result.fills_ask += 1
                total_fees += order.fee_usd

        result.total_fills = result.fills_bid + result.fills_ask
        result.final_inventory = tracker.inventory
        result.max_abs_inventory = max(result.max_abs_inventory, abs(tracker.inventory))
        result.realized_pnl = tracker.cash_flow
        result.total_fees = total_fees
        result.final_equity = account.equity_usd
        result.equity_curve.append(account.equity_usd)

    return result


def run_all_mm(config: MMIntegrationConfig) -> dict[str, MMIntegrationResult]:
    return {regime: run_mm_integration(regime, config) for regime in MarketRegime}


if __name__ == "__main__":
    config = MMIntegrationConfig()
    results = run_all_mm(config)
    print(f"{'Regime':22s} {'Quotes':>7s} {'Fills':>6s} {'Buy':>5s} {'Sell':>5s} "
          f"{'Inv':>8s} {'MaxInv':>8s} {'PnL':>9s} {'Fees':>6s} {'Equity':>9s}")
    print("-" * 100)
    for regime, r in results.items():
        print(f"{regime.value:22s} {r.quotes_generated:7d} {r.total_fills:6d} "
              f"{r.fills_bid:5d} {r.fills_ask:5d} {r.final_inventory:8.1f} "
              f"{r.max_abs_inventory:8.1f} {r.realized_pnl:9.2f} "
              f"{r.total_fees:6.2f} {r.final_equity:9.2f}")
    total_fees = sum(r.total_fees for r in results.values())
    total_pnl = sum(r.realized_pnl for r in results.values())
    print(f"\nTotal fees: {total_fees:.2f}")
    print(f"Total PnL: {total_pnl:.2f}")
    print(f"Net after fees: {total_pnl - total_fees:.2f}")
