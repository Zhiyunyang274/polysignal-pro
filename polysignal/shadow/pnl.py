"""PnL and performance calculations for shadow paper trading."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any

from polysignal.shadow.models import ShadowSide, ShadowTrade, ShadowTradeStatus


def calculate_return_pct(
    entry_price: float,
    exit_price: float,
    side: ShadowSide,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> float:
    if entry_price <= 0:
        return 0.0
    raw = (exit_price - entry_price) / entry_price
    cost = (fee_bps + slippage_bps) / 10000.0
    return raw - cost


def calculate_pnl(
    entry_price: float,
    exit_price: float,
    side: ShadowSide,
    notional: float = 1.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> tuple[float, float]:
    ret = calculate_return_pct(entry_price, exit_price, side, fee_bps, slippage_bps)
    return notional * ret, ret


def apply_exit_to_trade(
    trade: ShadowTrade,
    exit_time: str,
    exit_price: float,
    exit_reason: Any,
    holding_minutes: float,
    notional: float = 1.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> ShadowTrade:
    entry_price = trade.effective_entry_price()
    if entry_price <= 0:
        return mark_insufficient_forward_data(trade, reason="invalid_entry_price_model")
    pnl, ret = calculate_pnl(entry_price, exit_price, trade.side, notional, fee_bps, slippage_bps)
    trade.exit_time = exit_time
    trade.set_exit_side_price(exit_price, f"{trade.side.value.lower()}_best_bid")
    trade.exit_reason = exit_reason
    trade.pnl = pnl
    trade.return_pct = ret
    trade.holding_minutes = holding_minutes
    trade.status = ShadowTradeStatus.CLOSED
    return trade


def mark_insufficient_forward_data(trade: ShadowTrade, reason: str = "insufficient_forward_data") -> ShadowTrade:
    trade.status = ShadowTradeStatus.INSUFFICIENT_FORWARD_DATA
    trade.exit_time = None
    trade.exit_price = None
    trade.pnl = 0.0
    trade.return_pct = 0.0
    trade.holding_minutes = 0.0
    trade.max_adverse_excursion = 0.0
    trade.max_favorable_excursion = 0.0
    trade.price_model_status = reason if reason != "insufficient_forward_data" else trade.price_model_status
    if reason != "insufficient_forward_data":
        trade.price_model_notes = reason
    return trade


def apply_excursions(
    trade: ShadowTrade,
    observations: list[dict[str, Any]],
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> ShadowTrade:
    returns: list[float] = []
    for obs in observations:
        if trade.side == ShadowSide.NO:
            value = obs.get("no_best_bid", obs.get("price"))
        else:
            value = obs.get("yes_best_bid", obs.get("price"))
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        returns.append(calculate_return_pct(trade.effective_entry_price(), price, trade.side, fee_bps, slippage_bps))
    if returns:
        trade.max_adverse_excursion = min(returns)
        trade.max_favorable_excursion = max(returns)
    return trade


def max_drawdown(returns: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for ret in returns:
        equity += ret
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def summarize_performance(trades: list[ShadowTrade]) -> dict[str, Any]:
    closed = [t for t in trades if t.status == ShadowTradeStatus.CLOSED]
    insufficient = [t for t in trades if t.status == ShadowTradeStatus.INSUFFICIENT_FORWARD_DATA]
    returns = [t.return_pct for t in closed]
    wins = [r for r in returns if r > 0]
    categories: dict[str, list[float]] = defaultdict(list)
    edge_types: dict[str, list[float]] = defaultdict(list)
    relationship_statuses: dict[str, list[float]] = defaultdict(list)
    price_gap_buckets: dict[str, list[float]] = defaultdict(list)
    sources: dict[str, list[float]] = defaultdict(list)
    for trade in closed:
        categories[trade.category or "Unknown"].append(trade.return_pct)
        edge_types[trade.edge_type or "unknown"].append(trade.return_pct)
        relationship_statuses[trade.relationship_status or "unknown"].append(trade.return_pct)
        price_gap_buckets[price_gap_bucket(trade.price_gap)].append(trade.return_pct)
        sources[trade.source or "unknown"].append(trade.return_pct)

    def grouped_performance(groups: dict[str, list[float]]) -> dict[str, dict[str, float]]:
        return {
            key: {
                "trades": len(values),
                "average_return": mean(values) if values else 0.0,
                "total_return": sum(values),
                "win_rate": (len([value for value in values if value > 0]) / len(values)) if values else 0.0,
            }
            for key, values in groups.items()
        }

    return {
        "total_shadow_trades": len(trades),
        "open_positions": len([t for t in trades if t.status == ShadowTradeStatus.OPEN]),
        "insufficient_forward_data_positions": len(insufficient),
        "closed_positions": len(closed),
        "win_rate": (len(wins) / len(closed)) if closed else 0.0,
        "average_return": mean(returns) if returns else 0.0,
        "median_return": median(returns) if returns else 0.0,
        "total_pnl": sum(t.pnl for t in closed),
        "max_drawdown": max_drawdown(returns),
        "avg_holding_minutes": mean([t.holding_minutes for t in closed]) if closed else 0.0,
        "exit_reason_distribution": dict(Counter(t.exit_reason.value for t in closed)),
        "entry_reason_distribution": dict(Counter(t.entry_reason for t in trades)),
        "category_performance": {
            category: {
                "trades": len(values),
                "average_return": mean(values) if values else 0.0,
                "total_return": sum(values),
            }
            for category, values in categories.items()
        },
        "edge_type_performance": grouped_performance(edge_types),
        "relationship_status_performance": grouped_performance(relationship_statuses),
        "price_gap_bucket_performance": grouped_performance(price_gap_buckets),
        "source_performance": grouped_performance(sources),
    }


def price_gap_bucket(value: Any) -> str:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = 0.0

    if numeric_value < 0.05:
        return "<0.05"
    if numeric_value < 0.10:
        return "0.05-0.10"
    if numeric_value < 0.25:
        return "0.10-0.25"
    if numeric_value < 0.50:
        return "0.25-0.50"
    return ">=0.50"
