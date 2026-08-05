"""Deterministic L2 execution-cost estimates for shadow research.

The functions in this module are pure calculations. They do not submit orders,
authenticate, access a wallet, or call a network service. Full-fill simulation
is the default so insufficient visible depth fails closed.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field


class ExecutionSide(str, Enum):
    """Aggressor side used by an execution-cost estimate."""

    BUY = "buy"
    SELL = "sell"


class FillStatus(str, Enum):
    """Outcome of a deterministic visible-book fill estimate."""

    FULL = "full"
    PARTIAL = "partial"
    REJECTED = "rejected"


class L2Level(BaseModel):
    """One visible market-by-price level, with size expressed in shares."""

    model_config = ConfigDict(frozen=True)

    price: float = Field(..., gt=0.0, lt=1.0)
    size: float = Field(..., gt=0.0)


class LevelFill(BaseModel):
    """Quantity consumed from one price level."""

    model_config = ConfigDict(frozen=True)

    price: float
    shares: float
    notional_usd: float


class ExecutionCost(BaseModel):
    """Auditable output of a single-leg L2 execution estimate."""

    model_config = ConfigDict(frozen=True)

    side: ExecutionSide
    status: FillStatus
    requested_notional_usd: float | None = None
    requested_shares: float | None = None
    filled_notional_usd: float = 0.0
    filled_shares: float = 0.0
    available_notional_usd: float = 0.0
    available_shares: float = 0.0
    average_price: float | None = None
    best_price: float | None = None
    worst_price: float | None = None
    adverse_impact_bps: float | None = None
    fee_bps: float = 0.0
    fee_usd: float = 0.0
    net_cash_flow_usd: float = 0.0
    completion_ratio: float = 0.0
    reject_reason: str = ""
    fills: tuple[LevelFill, ...] = ()


class RoundTripCost(BaseModel):
    """Entry and same-share exit estimate for one outcome token."""

    model_config = ConfigDict(frozen=True)

    status: FillStatus
    entry: ExecutionCost
    exit: ExecutionCost | None = None
    gross_pnl_usd: float | None = None
    total_fees_usd: float | None = None
    net_pnl_usd: float | None = None
    return_pct: float | None = None
    reject_reason: str = ""


def simulate_buy_notional(
    asks: Iterable[L2Level],
    notional_usd: float,
    *,
    fee_bps: float = 0.0,
    limit_price: float | None = None,
    allow_partial: bool = False,
) -> ExecutionCost:
    """Walk asks to spend a requested dollar notional.

    Fees use an explicit flat-notional basis-point assumption. This is a
    configurable research cost, not a claim about a market's effective fee
    schedule.
    """

    _validate_positive("notional_usd", notional_usd)
    _validate_fee_bps(fee_bps)
    _validate_limit_price(limit_price)
    levels = _canonical_levels(asks, ExecutionSide.BUY, limit_price)

    available_notional = sum(level.price * level.size for level in levels)
    available_shares = sum(level.size for level in levels)
    remaining = notional_usd
    projected: list[LevelFill] = []
    tolerance = _tolerance(notional_usd)

    for level in levels:
        if remaining <= tolerance:
            break
        level_notional = level.price * level.size
        consumed_notional = min(remaining, level_notional)
        consumed_shares = consumed_notional / level.price
        projected.append(
            LevelFill(
                price=level.price,
                shares=consumed_shares,
                notional_usd=consumed_notional,
            )
        )
        remaining -= consumed_notional

    return _finish_execution(
        side=ExecutionSide.BUY,
        requested_notional_usd=notional_usd,
        requested_shares=None,
        projected=projected,
        request_remaining=max(0.0, remaining),
        request_total=notional_usd,
        available_notional_usd=available_notional,
        available_shares=available_shares,
        fee_bps=fee_bps,
        allow_partial=allow_partial,
    )


def simulate_sell_shares(
    bids: Iterable[L2Level],
    shares: float,
    *,
    fee_bps: float = 0.0,
    limit_price: float | None = None,
    allow_partial: bool = False,
) -> ExecutionCost:
    """Walk bids to sell a requested number of shares."""

    _validate_positive("shares", shares)
    _validate_fee_bps(fee_bps)
    _validate_limit_price(limit_price)
    levels = _canonical_levels(bids, ExecutionSide.SELL, limit_price)

    available_notional = sum(level.price * level.size for level in levels)
    available_shares = sum(level.size for level in levels)
    remaining = shares
    projected: list[LevelFill] = []
    tolerance = _tolerance(shares)

    for level in levels:
        if remaining <= tolerance:
            break
        consumed_shares = min(remaining, level.size)
        projected.append(
            LevelFill(
                price=level.price,
                shares=consumed_shares,
                notional_usd=consumed_shares * level.price,
            )
        )
        remaining -= consumed_shares

    return _finish_execution(
        side=ExecutionSide.SELL,
        requested_notional_usd=None,
        requested_shares=shares,
        projected=projected,
        request_remaining=max(0.0, remaining),
        request_total=shares,
        available_notional_usd=available_notional,
        available_shares=available_shares,
        fee_bps=fee_bps,
        allow_partial=allow_partial,
    )


def simulate_round_trip(
    entry_asks: Iterable[L2Level],
    exit_bids: Iterable[L2Level],
    entry_notional_usd: float,
    *,
    entry_fee_bps: float = 0.0,
    exit_fee_bps: float = 0.0,
    entry_limit_price: float | None = None,
    exit_limit_price: float | None = None,
) -> RoundTripCost:
    """Estimate a full-fill entry followed by an exit of the acquired shares."""

    entry = simulate_buy_notional(
        entry_asks,
        entry_notional_usd,
        fee_bps=entry_fee_bps,
        limit_price=entry_limit_price,
    )
    if entry.status is not FillStatus.FULL:
        return RoundTripCost(
            status=FillStatus.REJECTED,
            entry=entry,
            reject_reason=f"entry_{entry.reject_reason or 'not_fully_fillable'}",
        )

    exit_cost = simulate_sell_shares(
        exit_bids,
        entry.filled_shares,
        fee_bps=exit_fee_bps,
        limit_price=exit_limit_price,
    )
    if exit_cost.status is not FillStatus.FULL:
        return RoundTripCost(
            status=FillStatus.REJECTED,
            entry=entry,
            exit=exit_cost,
            reject_reason=f"exit_{exit_cost.reject_reason or 'not_fully_fillable'}",
        )

    gross_pnl = exit_cost.filled_notional_usd - entry.filled_notional_usd
    total_fees = entry.fee_usd + exit_cost.fee_usd
    net_pnl = gross_pnl - total_fees
    total_entry_cost = entry.filled_notional_usd + entry.fee_usd
    return RoundTripCost(
        status=FillStatus.FULL,
        entry=entry,
        exit=exit_cost,
        gross_pnl_usd=gross_pnl,
        total_fees_usd=total_fees,
        net_pnl_usd=net_pnl,
        return_pct=net_pnl / total_entry_cost if total_entry_cost > 0 else None,
    )


def _canonical_levels(
    levels: Iterable[L2Level],
    side: ExecutionSide,
    limit_price: float | None,
) -> list[L2Level]:
    aggregated: dict[float, float] = {}
    for raw_level in levels:
        level = raw_level if isinstance(raw_level, L2Level) else L2Level.model_validate(raw_level)
        if limit_price is not None:
            outside_limit = (
                side is ExecutionSide.BUY and level.price > limit_price
            ) or (
                side is ExecutionSide.SELL and level.price < limit_price
            )
            if outside_limit:
                continue
        aggregated[level.price] = aggregated.get(level.price, 0.0) + level.size

    reverse = side is ExecutionSide.SELL
    return [
        L2Level(price=price, size=aggregated[price])
        for price in sorted(aggregated, reverse=reverse)
    ]


def _finish_execution(
    *,
    side: ExecutionSide,
    requested_notional_usd: float | None,
    requested_shares: float | None,
    projected: list[LevelFill],
    request_remaining: float,
    request_total: float,
    available_notional_usd: float,
    available_shares: float,
    fee_bps: float,
    allow_partial: bool,
) -> ExecutionCost:
    complete = request_remaining <= _tolerance(request_total)
    if not complete and not allow_partial:
        return ExecutionCost(
            side=side,
            status=FillStatus.REJECTED,
            requested_notional_usd=requested_notional_usd,
            requested_shares=requested_shares,
            available_notional_usd=available_notional_usd,
            available_shares=available_shares,
            fee_bps=fee_bps,
            reject_reason="insufficient_visible_depth",
        )

    filled_notional = sum(fill.notional_usd for fill in projected)
    filled_shares = sum(fill.shares for fill in projected)
    if filled_shares <= 0.0 or filled_notional <= 0.0:
        return ExecutionCost(
            side=side,
            status=FillStatus.REJECTED,
            requested_notional_usd=requested_notional_usd,
            requested_shares=requested_shares,
            available_notional_usd=available_notional_usd,
            available_shares=available_shares,
            fee_bps=fee_bps,
            reject_reason="no_executable_levels",
        )

    average_price = filled_notional / filled_shares
    best_price = projected[0].price
    worst_price = projected[-1].price
    if side is ExecutionSide.BUY:
        adverse_impact_bps = (average_price - best_price) / best_price * 10_000
        net_cash_flow = -(filled_notional + filled_notional * fee_bps / 10_000)
    else:
        adverse_impact_bps = (best_price - average_price) / best_price * 10_000
        net_cash_flow = filled_notional - filled_notional * fee_bps / 10_000
    fee_usd = filled_notional * fee_bps / 10_000
    completion_ratio = (request_total - request_remaining) / request_total

    return ExecutionCost(
        side=side,
        status=FillStatus.FULL if complete else FillStatus.PARTIAL,
        requested_notional_usd=requested_notional_usd,
        requested_shares=requested_shares,
        filled_notional_usd=filled_notional,
        filled_shares=filled_shares,
        available_notional_usd=available_notional_usd,
        available_shares=available_shares,
        average_price=average_price,
        best_price=best_price,
        worst_price=worst_price,
        adverse_impact_bps=max(0.0, adverse_impact_bps),
        fee_bps=fee_bps,
        fee_usd=fee_usd,
        net_cash_flow_usd=net_cash_flow,
        completion_ratio=min(1.0, max(0.0, completion_ratio)),
        fills=tuple(projected),
    )


def _validate_positive(name: str, value: float) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _validate_fee_bps(fee_bps: float) -> None:
    if not isfinite(fee_bps) or not 0.0 <= fee_bps <= 10_000.0:
        raise ValueError("fee_bps must be finite and between 0 and 10000")


def _validate_limit_price(limit_price: float | None) -> None:
    if limit_price is not None and (
        not isfinite(limit_price) or not 0.0 < limit_price < 1.0
    ):
        raise ValueError("limit_price must be finite and between 0 and 1")


def _tolerance(value: float) -> float:
    return max(1e-12, abs(value) * 1e-12)
