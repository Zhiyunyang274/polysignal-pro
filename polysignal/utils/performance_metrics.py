"""

Performance Metrics - Account-level trading performance statistics

IMPORTANT:
- Pure calculations only. No API, no LLM, no orders.
- All inputs are deterministic data (equity curve, closed trade PnLs).
- Conventions:
  * `max_drawdown_pct` is <= 0 (a fraction in percent units, e.g. -23.4).
  * Sharpe/Sortino use zero risk-free rate and infer annualization from the
    median equity-curve interval (365-day year).
  * win = trade pnl > 0; loss = trade pnl < 0; breakeven is neither.
  * profit_factor / payoff_ratio return None when there are no losses,
    rather than a fake infinite value.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from statistics import mean, median, pstdev

from pydantic import BaseModel

SECONDS_PER_YEAR = 365.0 * 24 * 3600


def _normalize_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


class PerformanceMetrics(BaseModel):
    """Account-level performance summary. Optional fields are None when the
    input does not support a meaningful value (e.g. too few points)."""

    point_count: int = 0
    start_equity_usd: float | None = None
    end_equity_usd: float | None = None
    total_return_pct: float | None = None
    annualized_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    periods_per_year: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None

    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float | None = None
    total_pnl_usd: float = 0.0
    gross_profit_usd: float = 0.0
    gross_loss_usd: float = 0.0
    profit_factor: float | None = None
    payoff_ratio: float | None = None
    avg_win_usd: float | None = None
    avg_loss_usd: float | None = None
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0

    turnover_x: float | None = None
    avg_exposure_pct: float | None = None


def period_returns(equity_curve: Sequence[tuple[datetime, float]]) -> list[float]:
    """Simple returns between consecutive equity points (order preserved)."""
    returns: list[float] = []
    for (_, prev), (_, curr) in zip(equity_curve, equity_curve[1:], strict=False):
        if prev <= 0:
            returns.append(0.0)
            continue
        returns.append((curr - prev) / prev)
    return returns


def _infer_periods_per_year(equity_curve: Sequence[tuple[datetime, float]]) -> float | None:
    if len(equity_curve) < 3:
        return None
    intervals = [
        (_normalize_utc(curr_t) - _normalize_utc(prev_t)).total_seconds()
        for (prev_t, _), (curr_t, _) in zip(equity_curve, equity_curve[1:], strict=False)
    ]
    positive = [interval for interval in intervals if interval > 0]
    if not positive:
        return None
    median_interval = median(positive)
    if median_interval <= 0:
        return None
    return SECONDS_PER_YEAR / median_interval


def max_drawdown(equity_curve: Sequence[tuple[datetime, float]]) -> float | None:
    """Peak-to-trough drawdown as a fraction <= 0 (e.g. -0.234)."""
    if not equity_curve:
        return None
    peak = -float("inf")
    worst = 0.0
    for _, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, (equity - peak) / peak)
    return worst


def max_consecutive(pnls: Sequence[float], *, wins: bool) -> int:
    """Longest streak of consecutive wins (pnl > 0) or losses (pnl < 0)."""
    best = 0
    current = 0
    for pnl in pnls:
        is_match = pnl > 0 if wins else pnl < 0
        if is_match:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def compute_performance_metrics(
    equity_curve: Sequence[tuple[datetime, float]],
    closed_trade_pnls: Sequence[float] = (),
    traded_notional_usd: float | None = None,
    exposure_curve: Sequence[tuple[datetime, float]] | None = None,
) -> PerformanceMetrics:
    """
    Compute the full account-level metric set.

    Args:
        equity_curve: ordered (timestamp, equity_usd) observations.
        closed_trade_pnls: realized PnL per closed trade, in close order.
        traded_notional_usd: total filled notional (for turnover).
        exposure_curve: optional ordered (timestamp, open exposure_usd)
            paired with the equity curve by index for exposure stats.
    """
    metrics = PerformanceMetrics()
    metrics.point_count = len(equity_curve)

    if equity_curve:
        start_equity = equity_curve[0][1]
        end_equity = equity_curve[-1][1]
        metrics.start_equity_usd = start_equity
        metrics.end_equity_usd = end_equity
        if start_equity > 0:
            metrics.total_return_pct = (end_equity - start_equity) / start_equity * 100.0

            span_seconds = (
                _normalize_utc(equity_curve[-1][0]) - _normalize_utc(equity_curve[0][0])
            ).total_seconds()
            years = span_seconds / SECONDS_PER_YEAR
            if years > 0 and end_equity > 0:
                metrics.annualized_return_pct = (
                    (end_equity / start_equity) ** (1.0 / years) - 1.0
                ) * 100.0

        metrics.max_drawdown_pct = _percent(max_drawdown(equity_curve))

        ppy = _infer_periods_per_year(equity_curve)
        metrics.periods_per_year = ppy
        returns = period_returns(equity_curve)
        if ppy is not None and returns:
            mean_return = mean(returns)
            volatility = pstdev(returns)
            if volatility > 0:
                metrics.sharpe_ratio = mean_return / volatility * (ppy**0.5)
            downside = [min(r, 0.0) for r in returns]
            downside_std = (mean([d**2 for d in downside])) ** 0.5
            if downside_std > 0:
                metrics.sortino_ratio = mean_return / downside_std * (ppy**0.5)

    pnls = list(closed_trade_pnls)
    metrics.trade_count = len(pnls)
    metrics.total_pnl_usd = sum(pnls)
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    metrics.win_count = len(wins)
    metrics.loss_count = len(losses)
    if pnls:
        metrics.win_rate = len(wins) / len(pnls) * 100.0
        metrics.max_consecutive_losses = max_consecutive(pnls, wins=False)
        metrics.max_consecutive_wins = max_consecutive(pnls, wins=True)
    if wins:
        metrics.gross_profit_usd = sum(wins)
        metrics.avg_win_usd = mean(wins)
    if losses:
        metrics.gross_loss_usd = sum(losses)
        metrics.avg_loss_usd = mean(losses)
    if metrics.gross_loss_usd < 0:
        metrics.profit_factor = metrics.gross_profit_usd / abs(metrics.gross_loss_usd)
        metrics.payoff_ratio = (metrics.avg_win_usd or 0.0) / abs(metrics.avg_loss_usd or 1.0)

    if traded_notional_usd is not None and equity_curve:
        avg_equity = mean([equity for _, equity in equity_curve])
        if avg_equity > 0:
            metrics.turnover_x = traded_notional_usd / avg_equity

    if exposure_curve:
        pairs = [
            (exposure, equity)
            for (_, equity), (_, exposure) in zip(equity_curve, exposure_curve, strict=False)
        ]
        usable = [(exposure, equity) for exposure, equity in pairs if equity > 0]
        if usable:
            metrics.avg_exposure_pct = mean(
                exposure / equity for exposure, equity in usable
            ) * 100.0

    return metrics


def _percent(fraction: float | None) -> float | None:
    return None if fraction is None else fraction * 100.0


def summarize_closed_pnls(pnls: Iterable[float]) -> dict[str, float | int | None]:
    """Small helper for callers that only have trade PnLs (no equity curve)."""
    metrics = compute_performance_metrics([], list(pnls))
    return metrics.model_dump(include={"trade_count", "win_rate", "total_pnl_usd", "profit_factor"})
