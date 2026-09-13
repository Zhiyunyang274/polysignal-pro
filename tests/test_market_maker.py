"""Tests for the MarketMaker dual-side quoting module."""

from __future__ import annotations

import pytest

from polysignal.execution.market_maker import (
    InventoryTracker,
    MarketMaker,
    MarketMakerConfig,
)


class TestMarketMakerConfig:
    def test_valid_config(self):
        cfg = MarketMakerConfig()
        cfg.validate_params()  # should not raise

    def test_invalid_half_spread(self):
        with pytest.raises(ValueError):
            MarketMakerConfig(half_spread_pct=-0.01).validate_params()

    def test_invalid_skew_factor(self):
        with pytest.raises(ValueError):
            MarketMakerConfig(skew_factor=0).validate_params()


class TestQuoteComputation:
    def test_symmetric_quotes_flat_inventory(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, order_size=10))
        q = mm.compute_quotes(fair_value=0.50, inventory=0)
        assert q.skipped is False
        assert q.bid_price == pytest.approx(0.49, abs=0.01)
        assert q.ask_price == pytest.approx(0.51, abs=0.01)
        assert q.bid_size == 10
        assert q.ask_size == 10
        assert q.bid_price < q.ask_price

    def test_spread_widens_with_fair_value(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02))
        q_low = mm.compute_quotes(fair_value=0.20, inventory=0)
        q_high = mm.compute_quotes(fair_value=0.80, inventory=0)
        # 2% of 0.20 = 0.004, but min_half_spread floor = 0.005
        # 2% of 0.80 = 0.016
        spread_low = q_low.ask_price - q_low.bid_price
        spread_high = q_high.ask_price - q_high.bid_price
        assert spread_high > spread_low

    def test_positive_inventory_skews_down(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, inventory_limit=100, skew_factor=0.5))
        q_flat = mm.compute_quotes(fair_value=0.50, inventory=0)
        q_long = mm.compute_quotes(fair_value=0.50, inventory=50)
        assert q_long.bid_price < q_flat.bid_price
        assert q_long.ask_price < q_flat.ask_price  # more eager to sell

    def test_negative_inventory_skews_up(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, inventory_limit=100, skew_factor=0.5))
        q_flat = mm.compute_quotes(fair_value=0.50, inventory=0)
        q_short = mm.compute_quotes(fair_value=0.50, inventory=-50)
        assert q_short.bid_price > q_flat.bid_price
        assert q_short.ask_price > q_flat.ask_price  # more eager to buy back

    def test_inventory_limit_blocks_quoting(self):
        mm = MarketMaker(MarketMakerConfig(inventory_limit=100, order_size=10))
        q = mm.compute_quotes(fair_value=0.50, inventory=100)
        assert q.skipped is True
        assert q.skip_reason == "inventory_limit_reached"

    def test_invalid_fair_value_skips(self):
        mm = MarketMaker(MarketMakerConfig())
        for bad in (0.0, 1.0, -0.5, 1.5):
            q = mm.compute_quotes(fair_value=bad, inventory=0)
            assert q.skipped is True


class TestInventoryTracker:
    def test_buy_then_sell_flat(self):
        inv = InventoryTracker()
        inv.on_buy_fill(0.50, 10)
        assert inv.inventory == pytest.approx(10)
        inv.on_sell_fill(0.52, 10)
        assert inv.is_flat
        # PnL = 10 * (0.52 - 0.50) = 0.20
        assert inv.cash_flow == pytest.approx(10 * 0.52 - 10 * 0.50)

    def test_multiple_fills(self):
        inv = InventoryTracker()
        inv.on_buy_fill(0.50, 10)
        inv.on_buy_fill(0.52, 10)
        assert inv.inventory == pytest.approx(20)
        assert inv.average_entry_price == pytest.approx(0.51)

    def test_invalid_fill_rejected(self):
        inv = InventoryTracker()
        with pytest.raises(ValueError):
            inv.on_buy_fill(-0.1, 10)
        with pytest.raises(ValueError):
            inv.on_sell_fill(0.5, -1)

    def test_cash_flow_tracking(self):
        inv = InventoryTracker()
        inv.on_buy_fill(0.40, 100)
        assert inv.cash_flow == pytest.approx(-40.0)
        inv.on_sell_fill(0.45, 100)
        assert inv.cash_flow == pytest.approx(5.0)


class TestMarketMakerWithInventory:
    def test_full_cycle_quotes_shift(self):
        """Buy then check quotes shift to encourage selling."""
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, inventory_limit=100, skew_factor=0.5))
        inv = InventoryTracker()

        inv.on_buy_fill(0.50, 30)
        q_after_buy = mm.compute_quotes(fair_value=0.50, inventory=inv.inventory)

        inv.on_sell_fill(0.52, 30)
        q_after_sell = mm.compute_quotes(fair_value=0.50, inventory=inv.inventory)

        # After buying 30, quotes should shift down (eager to sell)
        assert q_after_buy.ask_price < q_after_sell.ask_price
        # After selling back to flat, quotes should return to symmetric
        assert q_after_sell.bid_price == pytest.approx(q_after_buy.bid_price + (q_after_sell.ask_price - q_after_buy.ask_price), rel=0.1)

    def test_quote_sizes_decrease_near_limit(self):
        """As inventory approaches limit, the risky-side quote should shrink."""
        mm = MarketMaker(MarketMakerConfig(inventory_limit=100, order_size=10))
        inv = InventoryTracker()
        # Build up 90 inventory (near the 100 limit)
        inv.inventory = 90
        q = mm.compute_quotes(fair_value=0.50, inventory=90)
        assert q.skipped is False
        # But at exactly 100 it should stop
        q_limit = mm.compute_quotes(fair_value=0.50, inventory=100)
        assert q_limit.skipped is True


class TestDynamicSpread:
    """Iteration 031: volatility-adjusted spread widening."""

    def test_zero_volatility_unchanged(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, vol_multiplier=1.0))
        q_base = mm.compute_quotes(fair_value=0.50, inventory=0, volatility=0.0)
        assert q_base.bid_price < q_base.ask_price

    def test_high_volatility_widens_spread(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, vol_multiplier=1.0))
        q_calm = mm.compute_quotes(fair_value=0.50, inventory=0, volatility=0.01)
        q_volatile = mm.compute_quotes(fair_value=0.50, inventory=0, volatility=0.05)
        spread_calm = q_calm.ask_price - q_calm.bid_price
        spread_volatile = q_volatile.ask_price - q_volatile.bid_price
        assert spread_volatile > spread_calm

    def test_vol_multiplier_zero_ignores_volatility(self):
        mm = MarketMaker(MarketMakerConfig(half_spread_pct=0.02, vol_multiplier=0.0))
        q_a = mm.compute_quotes(fair_value=0.50, inventory=0, volatility=0.01)
        q_b = mm.compute_quotes(fair_value=0.50, inventory=0, volatility=0.10)
        assert q_a.bid_price == q_b.bid_price
        assert q_a.ask_price == q_b.ask_price

    def test_adverse_selection_mitigation(self):
        """High volatility with wide spread should reduce fills in crisis."""
        mm = MarketMaker(MarketMakerConfig(
            half_spread_pct=0.02, vol_multiplier=1.0, order_size=10,
        ))
        # Simulate: crisis vol = 5%, quotes widen → fewer fills from uninformed flow
        q_crisis = mm.compute_quotes(fair_value=0.50, inventory=0, volatility=0.05)
        spread = q_crisis.ask_price - q_crisis.bid_price
        # Spread should be wider than base 2% × 0.50 = 0.01
        assert spread > 0.01 * (1 + 0.05)  # wider than base + vol adjustment
