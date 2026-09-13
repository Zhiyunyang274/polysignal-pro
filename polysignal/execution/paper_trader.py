"""

Paper Trader - Simulate trading for strategy validation

IMPORTANT: Paper Trader is the MVP core module.
- MVP only supports LIMIT orders
- Paper Trader is deterministic for testing
- All orders must pass through Risk Governor first
"""

from datetime import timedelta
from math import isfinite
from typing import Any

from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.paper_trade import (
    OrderSide,
    OrderStatus,
    PaperOrder,
    PaperPosition,
    PaperTradeStats,
)
from polysignal.models.risk import RiskDecision
from polysignal.models.signal import Signal, SignalSide
from polysignal.utils.time import utc_now


class FillSimulation:
    """Result of fill simulation"""

    def __init__(
        self,
        requested_size: float,
        requested_price: float,
        filled_size: float,
        filled_price: float,
        slippage: float,
        partial_fill: bool,
        reason: str,
    ):
        self.requested_size = requested_size
        self.requested_price = requested_price
        self.filled_size = filled_size
        self.filled_price = filled_price
        self.slippage = slippage
        self.partial_fill = partial_fill
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_size": self.requested_size,
            "requested_price": self.requested_price,
            "filled_size": self.filled_size,
            "filled_price": self.filled_price,
            "slippage": self.slippage,
            "partial_fill": self.partial_fill,
            "reason": self.reason,
        }


class PaperTrader:
    """
    Paper Trader - Simulates trading for strategy validation.

    This module:
    - Receives Signal + RiskDecision
    - Simulates order execution
    - Tracks positions
    - Calculates PnL

    IMPORTANT:
    - MVP only supports LIMIT orders
    - Paper Trader is deterministic
    - All orders must pass Risk Governor
    """

    def __init__(
        self,
        default_order_size_usd: float = 1.0,
        slippage_assumption_pct: float = 0.01,
        order_timeout_seconds: int = 20,
        partial_fill_probability: float = 0.1,
    ):
        """
        Initialize Paper Trader.

        Args:
            default_order_size_usd: Default order size in USD
            slippage_assumption_pct: Default slippage assumption
            order_timeout_seconds: Order timeout in seconds
            partial_fill_probability: Deprecated compatibility setting. Partial
                fills are determined only by visible depth so results remain
                deterministic.
        """
        if not isfinite(default_order_size_usd) or default_order_size_usd <= 0:
            raise ValueError("default_order_size_usd must be finite and positive")
        if not isfinite(slippage_assumption_pct) or not 0 <= slippage_assumption_pct < 1:
            raise ValueError("slippage_assumption_pct must be finite and in [0, 1)")
        if order_timeout_seconds <= 0:
            raise ValueError("order_timeout_seconds must be positive")
        if not isfinite(partial_fill_probability) or not 0 <= partial_fill_probability <= 1:
            raise ValueError("partial_fill_probability must be finite and in [0, 1]")

        self.default_order_size_usd = default_order_size_usd
        self.slippage_assumption_pct = slippage_assumption_pct
        self.order_timeout_seconds = order_timeout_seconds
        self.partial_fill_probability = partial_fill_probability

        # State
        self._orders: dict[str, PaperOrder] = {}
        self._positions: dict[str, PaperPosition] = {}  # market_id -> position
        self._stats = PaperTradeStats()

    def execute(
        self,
        signal: Signal,
        risk_decision: RiskDecision,
        orderbook: OrderBookSnapshot,
        size_usd: float | None = None,
    ) -> tuple[PaperOrder | None, PaperPosition | None, str]:
        """
        Execute a paper trade.

        Args:
            signal: Signal to execute
            risk_decision: Risk Governor decision
            orderbook: Current orderbook
            size_usd: Order size in USD (optional)

        Returns:
            Tuple of (order, position, message)
        """
        # Step 1: Check Risk Governor allows paper trade
        if risk_decision.is_hard_rejected() or not risk_decision.allows_paper_trade():
            return None, None, "Risk Governor does not allow paper trade"

        if risk_decision.signal_id != signal.signal_id:
            return None, None, "Risk decision does not match signal"

        if orderbook.market_id != signal.market_id:
            return None, None, "Orderbook does not match signal market"

        if orderbook.is_stale:
            return None, None, "Orderbook is stale"

        # The current return model can persist only one order and one outcome
        # position. Treating BOTH as BUY_YES silently invents a paired fill, so
        # fail closed until a typed two-leg execution result is wired end to end.
        if signal.side == SignalSide.BOTH:
            return (
                None,
                None,
                "Paired YES/NO execution is not supported by the single-leg paper trader",
            )

        # Step 2: Determine order details
        size_usd = self.default_order_size_usd if size_usd is None else size_usd
        if not isfinite(size_usd) or size_usd <= 0:
            return None, None, "Order size must be finite and positive"
        order_side = self._get_order_side(signal.side)
        existing_position = self._positions.get(signal.market_id)
        if existing_position is not None and existing_position.side != order_side:
            return None, None, "Existing position belongs to a different outcome token"

        # Step 3: Simulate fill
        fill = self._simulate_fill(signal, orderbook, size_usd)

        if fill.filled_size <= 0:
            return None, None, f"No fill: {fill.reason}"

        # Step 4: Create order
        order = PaperOrder(
            signal_id=signal.signal_id,
            risk_decision_id=risk_decision.decision_id,
            market_id=signal.market_id,
            market_title=signal.market_title,
            side=order_side,
            price=fill.filled_price,
            size=fill.filled_size,
            filled_size=fill.filled_size,
            filled_price=fill.filled_price,
            slippage=fill.slippage,
            status=OrderStatus.FILLED if not fill.partial_fill else OrderStatus.PARTIALLY_FILLED,
            expires_at=utc_now() + timedelta(seconds=self.order_timeout_seconds),
            strategy_name=signal.strategy_name,
        )

        # Step 5: Update position
        position = self._update_position(order, fill.filled_price)

        # Step 6: Store order
        self._orders[order.order_id] = order

        return order, position, f"Order filled: {fill.filled_size:.2f} @ {fill.filled_price:.4f}"

    def _get_order_side(self, signal_side: SignalSide) -> OrderSide:
        """Convert signal side to order side"""
        if signal_side == SignalSide.YES:
            return OrderSide.BUY_YES
        if signal_side == SignalSide.NO:
            return OrderSide.BUY_NO
        raise ValueError("Paired signals require a two-leg execution model")

    def _simulate_fill(
        self,
        signal: Signal,
        orderbook: OrderBookSnapshot,
        size_usd: float,
    ) -> FillSimulation:
        """
        Simulate order fill.

        Walk visible asks in price order and apply the configured adverse-price
        stress to each level, capped at the signal's hard limit. Raw levels
        above the limit are never consumed. Partial fills depend only on visible
        depth.
        """
        # Ensure metrics calculated
        orderbook.calculate_metrics()

        target_price = signal.price
        if signal.side == SignalSide.YES:
            asks = orderbook.yes_asks.levels
            best_bid = orderbook.yes_bids.best_price
        else:
            asks = orderbook.no_asks.levels
            best_bid = orderbook.no_bids.best_price

        levels = sorted(
            (level for level in asks if level.price > 0 and level.size > 0),
            key=lambda level: level.price,
        )
        best_ask = levels[0].price if levels else None

        if best_ask is None:
            return FillSimulation(
                requested_size=size_usd,
                requested_price=target_price,
                filled_size=0,
                filled_price=0,
                slippage=0,
                partial_fill=False,
                reason="No liquidity on ask side",
            )

        if best_bid is not None and best_bid >= best_ask:
            return FillSimulation(
                requested_size=size_usd,
                requested_price=target_price,
                filled_size=0,
                filled_price=0,
                slippage=0,
                partial_fill=False,
                reason="Crossed orderbook",
            )

        remaining_usd = size_usd
        filled_notional = 0.0
        filled_size = 0.0
        tolerance = max(1e-12, size_usd * 1e-12)

        for level in levels:
            if level.price > target_price + 1e-12:
                break
            stressed_price = level.price * (1 + self.slippage_assumption_pct)
            execution_price = min(target_price, stressed_price)

            executable_notional = execution_price * level.size
            consumed_notional = min(remaining_usd, executable_notional)
            filled_notional += consumed_notional
            filled_size += consumed_notional / execution_price
            remaining_usd -= consumed_notional
            if remaining_usd <= tolerance:
                remaining_usd = 0.0
                break

        if filled_size <= 0 or filled_notional <= 0:
            return FillSimulation(
                requested_size=size_usd,
                requested_price=target_price,
                filled_size=0,
                filled_price=0,
                slippage=0,
                partial_fill=False,
                reason="No ask liquidity within limit price",
            )

        filled_price = filled_notional / filled_size
        partial_fill = remaining_usd > tolerance
        slippage = max(0.0, (filled_price - best_ask) / best_ask)

        return FillSimulation(
            requested_size=size_usd,
            requested_price=target_price,
            filled_size=filled_size,
            filled_price=filled_price,
            slippage=slippage,
            partial_fill=partial_fill,
            reason="Visible-depth partial fill" if partial_fill else "Visible-depth fill",
        )

    def _update_position(self, order: PaperOrder, current_price: float) -> PaperPosition:
        """Update position after order fill"""
        market_id = order.market_id

        if market_id not in self._positions:
            # Create new position
            position = PaperPosition(
                market_id=market_id,
                market_title=order.market_title,
                side=order.side,
                size=order.filled_size,
                avg_entry_price=order.filled_price or order.price,
                current_price=current_price,
            )
            self._positions[market_id] = position
        else:
            # Update existing position
            position = self._positions[market_id]
            total_size = position.size + order.filled_size
            if total_size > 0:
                fill_price = order.filled_price or order.price
                position.avg_entry_price = (
                    position.avg_entry_price * position.size
                    + fill_price * order.filled_size
                ) / total_size
            position.size = total_size
            position.updated_at = utc_now()

        # Update unrealized PnL
        position.update_price(current_price)

        return position

    def mark_to_market(self, market_id: str, current_price: float) -> PaperPosition | None:
        """Mark position to market"""
        if not isfinite(current_price) or not 0 <= current_price <= 1:
            return None

        if market_id not in self._positions:
            return None

        position = self._positions[market_id]
        position.update_price(current_price)
        return position

    def close_position(
        self,
        market_id: str,
        close_price: float,
        risk_decision: RiskDecision | None = None,
    ) -> tuple[PaperOrder | None, float]:
        """Close a position"""
        if (
            risk_decision is None
            or risk_decision.is_hard_rejected()
            or not risk_decision.allows_paper_trade()
        ):
            return None, 0.0

        if not isfinite(close_price) or not 0 <= close_price <= 1:
            return None, 0.0

        if market_id not in self._positions:
            return None, 0.0

        position = self._positions[market_id]
        size_to_close = position.size
        if size_to_close <= 0:
            return None, 0.0

        # Calculate realized PnL
        if position.side in {OrderSide.BUY_YES, OrderSide.BUY_NO}:
            pnl = size_to_close * (close_price - position.avg_entry_price)
        else:
            pnl = size_to_close * (position.avg_entry_price - close_price)

        position.realized_pnl_usd += pnl
        position.size = 0
        position.current_price = close_price
        position.unrealized_pnl_usd = 0.0
        position.updated_at = utc_now()

        # Create close order
        close_side = {
            OrderSide.BUY_YES: OrderSide.SELL_YES,
            OrderSide.BUY_NO: OrderSide.SELL_NO,
            OrderSide.SELL_YES: OrderSide.BUY_YES,
            OrderSide.SELL_NO: OrderSide.BUY_NO,
        }[position.side]
        close_order = PaperOrder(
            signal_id=risk_decision.signal_id,
            risk_decision_id=risk_decision.decision_id,
            market_id=market_id,
            market_title=position.market_title,
            side=close_side,
            price=close_price,
            size=size_to_close,
            filled_size=size_to_close,
            filled_price=close_price,
            status=OrderStatus.FILLED,
            realized_pnl_usd=pnl,
        )

        self._orders[close_order.order_id] = close_order

        return close_order, pnl

    def get_order(self, order_id: str) -> PaperOrder | None:
        """Get order by ID"""
        return self._orders.get(order_id)

    def get_position(self, market_id: str) -> PaperPosition | None:
        """Get position by market ID"""
        return self._positions.get(market_id)

    def get_all_positions(self) -> list[PaperPosition]:
        """Get all positions"""
        return list(self._positions.values())

    def get_all_orders(self) -> list[PaperOrder]:
        """Get all orders"""
        return list(self._orders.values())

    def get_stats(self) -> PaperTradeStats:
        """Get trading statistics"""
        self._stats.update_from_trades(self.get_all_orders())
        return self._stats

    def get_total_pnl_usd(self) -> float:
        """Get total PnL"""
        return sum(p.get_total_pnl_usd() for p in self._positions.values())
