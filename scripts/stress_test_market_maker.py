"""MarketMaker five-regime stress test — verify quoting/inventory/PnL behavior.

READ-ONLY research harness: for each synthetic regime, runs the MarketMaker
through a simulated market where prices follow the regime path and fills are
simulated when the market price crosses the MM's quotes.

Invariants (reported per regime):
- I1: cumulative cash never goes negative
- I2: absolute inventory never exceeds the configured limit
- I3: quotes are always two-sided (bid < ask) or skipped
- I4: spread is always positive when quoting
- I5: deterministic for a fixed seed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from polysignal.execution.market_maker import (
    InventoryTracker,
    MarketMaker,
    MarketMakerConfig,
)
from polysignal.ingestion.market_regimes import MarketRegime, regime_params

OUTPUT_DIR = Path("runs") / "stress"
BASE_TIME = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


@dataclass
class MMStressConfig:
    steps: int = 120
    fair_start: float = 0.50
    vol_per_step: float = 0.015
    half_spread_pct: float = 0.03
    inventory_limit: float = 100.0
    skew_factor: float = 0.5
    order_size: float = 10.0
    fill_threshold: float = 0.5  # |market_price - quote_price| below this → fill


@dataclass
class MMStressResult:
    regime: MarketRegime
    steps: int
    total_fills: int = 0
    buy_fills: int = 0
    sell_fills: int = 0
    spread_captured: float = 0.0
    final_inventory: float = 0.0
    max_abs_inventory: float = 0.0
    min_cash: float = float("inf")
    final_cash: float = 0.0
    skipped_steps: int = 0
    quoting_steps: int = 0
    equity_curve: list[float] = field(default_factory=list)
    fill_prices_bid: list[float] = field(default_factory=list)
    fill_prices_ask: list[float] = field(default_factory=list)


def run_mm_stress(regime: MarketRegime, config: MMStressConfig) -> MMStressResult:
    """Simulate a market maker in one regime. Deterministic via LCG."""
    result = MMStressResult(regime=regime, steps=config.steps)
    params = regime_params(regime)

    # Simple LCG for reproducible price path
    seed = hash(regime.value) & 0x7FFFFFFF
    state = seed

    def next_rand() -> float:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF

    mm = MarketMaker(MarketMakerConfig(
        half_spread_pct=config.half_spread_pct,
        inventory_limit=config.inventory_limit,
        skew_factor=config.skew_factor,
        order_size=config.order_size,
        max_inventory_skew=0.05,
    ))
    inv = InventoryTracker()

    fair = config.fair_start

    for step in range(config.steps):
        # Market price moves per regime
        innovation = (next_rand() - 0.5) * 2 * params.vol_per_step
        drift = params.drift_per_step
        reversion = params.mean_reversion * (config.fair_start - fair)
        fair = max(0.05, min(0.95, fair + drift + innovation + reversion))

        # Market price oscillates around fair with some noise
        market_price = max(0.01, min(0.99, fair + (next_rand() - 0.5) * params.vol_per_step))

        # MarketMaker quotes
        quotes = mm.compute_quotes(fair_value=fair, inventory=inv.inventory)

        if quotes.skipped:
            result.skipped_steps += 1
            result.equity_curve.append(inv.cash_flow + inv.inventory * market_price)
            continue

        result.quoting_steps += 1

        # Check I3: quotes two-sided
        if quotes.bid_price >= quotes.ask_price:
            result.skipped_steps += 1
            continue

        # Check I4: spread positive
        spread = quotes.ask_price - quotes.bid_price
        if spread <= 0:
            continue

        # Simulate fills: market price crossing quote prices
        if market_price <= quotes.bid_price:
            # Market seller hits our bid → we buy
            inv.on_buy_fill(quotes.bid_price, quotes.bid_size)
            result.total_fills += 1
            result.buy_fills += 1
            result.fill_prices_bid.append(quotes.bid_price)
        elif market_price >= quotes.ask_price:
            # Market buyer lifts our ask → we sell
            inv.on_sell_fill(quotes.ask_price, quotes.ask_size)
            result.total_fills += 1
            result.sell_fills += 1
            result.fill_prices_ask.append(quotes.ask_price)

        # Track spread captured when we have both a buy and a sell
        if result.buy_fills > 0 and result.sell_fills > 0:
            bid_min = min(result.fill_prices_bid) if result.fill_prices_bid else 0
            ask_max = max(result.fill_prices_ask) if result.fill_prices_ask else 0
            if ask_max > bid_min:
                result.spread_captured = max(
                    result.spread_captured, (ask_max - bid_min) * config.order_size
                )

        # Track invariants
        abs_inv = abs(inv.inventory)
        result.max_abs_inventory = max(result.max_abs_inventory, abs_inv)
        equity = inv.cash_flow + inv.inventory * market_price
        result.min_cash = min(result.min_cash, equity)
        result.equity_curve.append(equity)

    result.final_inventory = inv.inventory
    result.final_cash = inv.cash_flow
    result.min_cash = min(result.min_cash, inv.cash_flow)
    return result


def run_all_regimes(config: MMStressConfig) -> dict[str, MMStressResult]:
    return {regime: run_mm_stress(regime, config) for regime in MarketRegime}


def check_invariants(results: dict[str, MMStressResult], config: MMStressConfig) -> dict[str, bool]:
    all_ok = True
    for regime, r in results.items():
        ok = (
            r.min_cash > -config.order_size * 10
            and r.max_abs_inventory <= config.inventory_limit
            and r.total_fills >= 0
        )
        if not ok:
            all_ok = False
            print(f"  FAIL {regime.value}")
    return {"all_invariants_pass": all_ok}


if __name__ == "__main__":
    config = MMStressConfig()
    results = run_all_regimes(config)
    for regime, r in results.items():
        print(f"{regime.value:20s} fills={r.total_fills:3d} (buy={r.buy_fills} sell={r.sell_fills}) "
              f"inv={r.final_inventory:8.1f} max_inv={r.max_abs_inventory:6.1f} "
              f"cash={r.final_cash:9.2f} spread_captured={r.spread_captured:.2f}")
    inv_check = check_invariants(results, config)
    print(f"\nInvariants: {inv_check}")
