"""Exit rules for offline shadow trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from polysignal.shadow.models import ExitReason, ShadowSide, ShadowTrade
from polysignal.shadow.pnl import calculate_return_pct


@dataclass
class ExitRuleConfig:
    fixed_horizon_minutes: int = 240
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.05
    stale_after_minutes: int = 60


@dataclass
class ExitDecision:
    should_exit: bool
    reason: ExitReason
    exit_time: str
    exit_price: float | None
    holding_minutes: float


def parse_time(value: str) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.utcnow()


def observation_time(entry_time: datetime, index: int, obs: dict[str, Any]) -> datetime:
    timestamp = str(obs.get("timestamp") or "")
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp)
        except ValueError:
            pass
    return entry_time + timedelta(minutes=(index + 1) * 60)


def price_from_observation(obs: dict[str, Any], trade: ShadowTrade) -> float | None:
    """Return side-specific executable exit bid.

    combined_ask is intentionally ignored because it is a market-level feature,
    not an executable side-specific exit price.
    """
    value = obs.get("no_best_bid") if trade.side == ShadowSide.NO else obs.get("yes_best_bid")
    if value in (None, ""):
        value = obs.get("price")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def decide_exit(
    trade: ShadowTrade,
    observations: list[dict[str, Any]],
    config: ExitRuleConfig | None = None,
) -> ExitDecision:
    cfg = config or ExitRuleConfig()
    entry_time = parse_time(trade.entry_time)
    horizon_time = entry_time + timedelta(minutes=cfg.fixed_horizon_minutes)

    if not observations:
        return ExitDecision(
            should_exit=True,
            reason=ExitReason.STALE_DATA,
            exit_time=horizon_time.isoformat(),
            exit_price=None,
            holding_minutes=float(cfg.fixed_horizon_minutes),
        )

    last_time = entry_time
    last_price: float | None = None
    for index, obs in enumerate(observations):
        current_time = observation_time(entry_time, index, obs)
        current_price = price_from_observation(obs, trade)
        last_time = current_time

        if bool(obs.get("market_closed")):
            if current_price is None:
                return ExitDecision(False, ExitReason.OPEN, current_time.isoformat(), None, minutes(entry_time, current_time))
            return ExitDecision(True, ExitReason.MARKET_CLOSE, current_time.isoformat(), current_price, minutes(entry_time, current_time))
        if bool(obs.get("stale")):
            if current_price is None:
                return ExitDecision(False, ExitReason.OPEN, current_time.isoformat(), None, minutes(entry_time, current_time))
            return ExitDecision(True, ExitReason.STALE_DATA, current_time.isoformat(), current_price, minutes(entry_time, current_time))
        if current_price is None:
            continue
        last_price = current_price

        ret = calculate_return_pct(trade.effective_entry_price(), current_price, trade.side)
        if ret <= cfg.stop_loss_pct:
            return ExitDecision(True, ExitReason.STOP_LOSS, current_time.isoformat(), current_price, minutes(entry_time, current_time))
        if ret >= cfg.take_profit_pct:
            return ExitDecision(True, ExitReason.TAKE_PROFIT, current_time.isoformat(), current_price, minutes(entry_time, current_time))
        if current_time >= horizon_time:
            return ExitDecision(True, ExitReason.FIXED_HORIZON, current_time.isoformat(), current_price, minutes(entry_time, current_time))

    if last_time >= horizon_time and last_price is not None:
        return ExitDecision(True, ExitReason.FIXED_HORIZON, last_time.isoformat(), last_price, minutes(entry_time, last_time))

    stale_time = last_time + timedelta(minutes=cfg.stale_after_minutes)
    if last_price is None:
        return ExitDecision(False, ExitReason.OPEN, stale_time.isoformat(), None, minutes(entry_time, stale_time))
    return ExitDecision(True, ExitReason.STALE_DATA, stale_time.isoformat(), last_price, minutes(entry_time, stale_time))


def minutes(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60.0)
