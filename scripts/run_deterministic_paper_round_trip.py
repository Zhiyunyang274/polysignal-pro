#!/usr/bin/env python3
"""Run one deterministic, mock-only paper buy and sell round trip.

The harness exercises the production RiskGovernor and PaperTrader without
network access, credentials, signing, or live execution. Its normalized JSON
omits generated identifiers and wall-clock timestamps so identical inputs
produce identical output bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from polysignal.execution.paper_trader import PaperTrader
from polysignal.models.market import Market, MarketCategory
from polysignal.models.orderbook import OrderBookSide, OrderBookSnapshot, PriceLevel
from polysignal.models.risk import RiskContext
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor

SCHEMA_VERSION = "deterministic_paper_round_trip_v1"
MARKET_ID = "deterministic-paper-round-trip"
NOTIONAL_USD = 1.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic mock-only paper buy/sell round trip"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def _book_side(levels: list[tuple[float, float]]) -> OrderBookSide:
    return OrderBookSide.model_validate(
        {
            "levels": [
                PriceLevel(price=price, size=size, total_usd=price * size) for price, size in levels
            ]
        }
    )


def _orderbook(yes_bid: float, yes_ask: float, no_bid: float, no_ask: float) -> OrderBookSnapshot:
    depth_shares = 100.0
    return OrderBookSnapshot.model_validate(
        {
            "market_id": MARKET_ID,
            "yes_bids": _book_side([(yes_bid, depth_shares)]),
            "yes_asks": _book_side([(yes_ask, depth_shares)]),
            "no_bids": _book_side([(no_bid, depth_shares)]),
            "no_asks": _book_side([(no_ask, depth_shares)]),
            "source": "deterministic_mock",
            "is_stale": False,
        }
    )


def run_round_trip() -> dict[str, Any]:
    """Return a normalized deterministic paper round-trip result."""

    market = Market.model_validate(
        {
            "market_id": MARKET_ID,
            "title": "Deterministic paper round trip",
            "category": MarketCategory.CRYPTO,
            "total_volume_usd": 250_000.0,
            "volume_24h_usd": 100_000.0,
        }
    )
    scores = ComponentScores(
        microstructure_score=95.0,
        liquidity_score=95.0,
        event_score=95.0,
        wallet_score=95.0,
        lifecycle_score=95.0,
    )
    context = RiskContext.model_validate(
        {
            "live_trading_enabled": False,
            "allow_auto_execution": False,
            "api_healthy": True,
            "websocket_healthy": True,
        }
    )
    governor = RiskGovernor(
        live_trading_enabled=False,
        allow_auto_execution=False,
        paper_trading_enabled=True,
    )
    trader = PaperTrader(
        default_order_size_usd=NOTIONAL_USD,
        slippage_assumption_pct=0.0,
        partial_fill_probability=0.0,
    )

    entry_book = _orderbook(yes_bid=0.49, yes_ask=0.50, no_bid=0.49, no_ask=0.50)
    entry_signal = Signal.model_validate(
        {
            "signal_id": "deterministic-entry",
            "market_id": MARKET_ID,
            "market_title": market.title,
            "market_category": market.category.value,
            "strategy_name": "deterministic_paper_round_trip",
            "side": SignalSide.YES,
            "price": 0.50,
            "component_scores": scores,
            "raw_score": 95.0,
            "path_type": "research",
            "data_source": "deterministic_mock",
        }
    )
    entry_decision = governor.evaluate(entry_signal, context, entry_book, market)
    entry_order, position, entry_message = trader.execute(
        entry_signal,
        entry_decision,
        entry_book,
        size_usd=NOTIONAL_USD,
    )
    if entry_order is None or position is None:
        raise RuntimeError(f"deterministic paper entry failed: {entry_message}")

    exit_book = _orderbook(yes_bid=0.60, yes_ask=0.61, no_bid=0.39, no_ask=0.40)
    exit_signal = entry_signal.model_copy(update={"signal_id": "deterministic-exit", "price": 0.61})
    exit_decision = governor.evaluate(exit_signal, context, exit_book, market)
    exit_book.calculate_metrics()
    close_price = exit_book.yes_bids.best_price
    if close_price is None:
        raise RuntimeError("deterministic exit book has no YES bid")
    close_order, realized_pnl = trader.close_position(
        MARKET_ID,
        close_price,
        risk_decision=exit_decision,
    )
    if close_order is None:
        raise RuntimeError("deterministic paper exit failed")

    live_allowed = entry_decision.allows_live_execute() or exit_decision.allows_live_execute()
    if live_allowed:
        raise RuntimeError("mock paper harness unexpectedly allowed live execution")
    if not entry_decision.allows_paper_trade() or not exit_decision.allows_paper_trade():
        raise RuntimeError("Risk Governor did not approve both paper actions")

    filled_notional = float(entry_order.filled_price or 0.0) * entry_order.filled_size
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "deterministic_mock_paper",
        "safety": {
            "allow_auto_execution": False,
            "authenticated_endpoints": False,
            "live_execution_allowed": live_allowed,
            "live_trading_enabled": False,
            "network_calls": False,
            "private_key_handling": False,
        },
        "entry": {
            "allowed_actions": sorted(action.value for action in entry_decision.allowed_actions),
            "filled_notional_usd": round(filled_notional, 10),
            "filled_price": entry_order.filled_price,
            "filled_shares": entry_order.filled_size,
            "order_side": entry_order.side.value,
            "risk_action": entry_decision.action.value,
            "risk_score": entry_decision.trade_score,
        },
        "exit": {
            "allowed_actions": sorted(action.value for action in exit_decision.allowed_actions),
            "filled_price": close_order.filled_price,
            "filled_shares": close_order.filled_size,
            "order_side": close_order.side.value,
            "risk_action": exit_decision.action.value,
            "risk_score": exit_decision.trade_score,
        },
        "result": {
            "gross_realized_pnl_usd": round(realized_pnl, 10),
            "gross_return_on_notional": round(realized_pnl / NOTIONAL_USD, 10),
            "orders_recorded": len(trader.get_all_orders()),
            "position_size_after_exit": position.size,
        },
        "assumptions": {
            "fees_included": False,
            "orderbooks": "fixed_visible_depth_mock",
            "slippage_assumption_pct": 0.0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_round_trip()
    rendered = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.dry_run:
        print("DRY RUN: deterministic mock paper round trip")
        print(rendered, end="")
        return 0
    if args.output is not None:
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite existing artifact: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
        print(args.output)
        return 0
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
