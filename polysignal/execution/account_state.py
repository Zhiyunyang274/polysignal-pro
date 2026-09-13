"""

Account State - Paper/simulation account ledger

IMPORTANT:
- This module only maintains account-level state. It never places orders,
  calls APIs, or talks to an LLM.
- It is the single source of truth for the account fields Risk Governor
  consumes through RiskContext (balance, daily/weekly PnL, consecutive
  losses, per-market and per-strategy exposure).
- Motivation (docs/system_review_2026-09-11.md, R1): Risk Governor's
  daily/weekly/consecutive-loss hard rejections were dead code because no
  caller maintained these fields. Every runner must feed its account state
  into every RiskContext it builds.
- All timestamps are timezone-aware UTC. Methods accept an explicit `now`
  so results stay deterministic for tests; production callers omit it.
- Accounting basis: exposure is recorded at entry notional, and PnL windows
  cover realized PnL only. Unrealized drawdown is intentionally NOT included
  (position limits, spread/stale hard rejects, and shadow exit rules cover
  that risk); this keeps the ledger simple and deterministic.
"""

from datetime import UTC, datetime
from math import isfinite
from typing import TypedDict

from pydantic import BaseModel, Field


class RiskContextAccountFields(TypedDict):
    """Typed splat target for RiskContext construction."""

    account_balance_usd: float
    daily_pnl_usd: float
    weekly_pnl_usd: float
    consecutive_losses: int
    current_market_exposure_usd: float
    current_strategy_exposure_usd: float


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(timestamp: datetime) -> datetime:
    """Treat naive timestamps as UTC and normalize everything to UTC."""
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


class OpenPositionRecord(BaseModel):
    """One open outcome position tracked at entry notional."""

    market_id: str
    strategy_name: str
    entry_notional_usd: float = Field(ge=0)


class ClosedTradeRecord(BaseModel):
    """One fully closed position with its realized result."""

    timestamp: datetime
    strategy_name: str
    market_id: str
    realized_pnl_usd: float


class AccountState:
    """
    Deterministic account ledger for paper/simulated trading.

    Mirrors PaperTrader semantics: one aggregated position per market
    (record_open on the same market accumulates notional), and full closes
    only (matching PaperTrader.close_position, which never partially closes).

    A position's strategy attribution is fixed by the first open on that
    market; subsequent opens on the same market inherit it, because a close
    settles the whole market position at once.
    """

    def __init__(self, starting_capital_usd: float = 10000.0):
        if not isfinite(starting_capital_usd) or starting_capital_usd <= 0:
            raise ValueError("starting_capital_usd must be finite and positive")

        self.starting_capital_usd = starting_capital_usd
        self.cash_usd = starting_capital_usd
        self.realized_pnl_usd = 0.0
        self.consecutive_losses = 0

        self._open_positions: dict[str, OpenPositionRecord] = {}
        self._closed_trades: list[ClosedTradeRecord] = []

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def record_open(
        self,
        market_id: str,
        strategy_name: str,
        notional_usd: float,
    ) -> None:
        """Record a filled entry (or add-on) for a market position."""
        if not market_id:
            raise ValueError("market_id must be non-empty")
        if not strategy_name:
            raise ValueError("strategy_name must be non-empty")
        if not isfinite(notional_usd) or notional_usd <= 0:
            raise ValueError("notional_usd must be finite and positive")
        if notional_usd > self.cash_usd:
            raise ValueError(
                f"notional_usd {notional_usd:.4f} exceeds available cash {self.cash_usd:.4f}"
            )

        existing = self._open_positions.get(market_id)
        if existing is None:
            self._open_positions[market_id] = OpenPositionRecord(
                market_id=market_id,
                strategy_name=strategy_name,
                entry_notional_usd=notional_usd,
            )
        else:
            existing.entry_notional_usd += notional_usd

        self.cash_usd -= notional_usd

    def record_close(
        self,
        market_id: str,
        realized_pnl_usd: float,
        now: datetime | None = None,
    ) -> None:
        """
        Record a full close of a market position.

        `realized_pnl_usd` must be proceeds minus entry cost (the convention
        used by PaperTrader.close_position). Cash returns the entry notional
        plus the realized result; a negative result counts toward consecutive
        losses, a positive one resets the streak, zero leaves it unchanged.
        """
        if not market_id:
            raise ValueError("market_id must be non-empty")
        if not isfinite(realized_pnl_usd):
            raise ValueError("realized_pnl_usd must be finite")

        position = self._open_positions.pop(market_id, None)
        if position is None:
            raise ValueError(f"No open position for market {market_id}")

        closed_at = _normalize_utc(now) if now is not None else _utc_now()
        self._closed_trades.append(
            ClosedTradeRecord(
                timestamp=closed_at,
                strategy_name=position.strategy_name,
                market_id=market_id,
                realized_pnl_usd=realized_pnl_usd,
            )
        )

        self.cash_usd += position.entry_notional_usd + realized_pnl_usd
        self.realized_pnl_usd += realized_pnl_usd

        if realized_pnl_usd < 0:
            self.consecutive_losses += 1
        elif realized_pnl_usd > 0:
            self.consecutive_losses = 0

    # ------------------------------------------------------------------
    # Risk Governor feed
    # ------------------------------------------------------------------

    def daily_pnl_usd(self, now: datetime | None = None) -> float:
        """Realized PnL accumulated since the start of the current UTC day."""
        day = (_normalize_utc(now) if now is not None else _utc_now()).date()
        return sum(
            trade.realized_pnl_usd
            for trade in self._closed_trades
            if _normalize_utc(trade.timestamp).date() == day
        )

    def weekly_pnl_usd(self, now: datetime | None = None) -> float:
        """Realized PnL accumulated in the current ISO week (UTC)."""
        week = (_normalize_utc(now) if now is not None else _utc_now()).isocalendar()[:2]
        return sum(
            trade.realized_pnl_usd
            for trade in self._closed_trades
            if _normalize_utc(trade.timestamp).isocalendar()[:2] == week
        )

    def market_exposure_usd(self, market_id: str) -> float:
        """Entry notional currently open on one market."""
        position = self._open_positions.get(market_id)
        return position.entry_notional_usd if position else 0.0

    def strategy_exposure_usd(self, strategy_name: str) -> float:
        """Entry notional currently open across all positions of a strategy."""
        return sum(
            position.entry_notional_usd
            for position in self._open_positions.values()
            if position.strategy_name == strategy_name
        )

    @property
    def total_exposure_usd(self) -> float:
        """Entry notional currently open across all markets."""
        return sum(position.entry_notional_usd for position in self._open_positions.values())

    @property
    def equity_usd(self) -> float:
        """
        Cash plus open entry notional.

        Unrealized PnL is excluded by design (see module docstring); equity
        therefore converges to the true mark-to-market equity only at close.
        """
        return self.cash_usd + self.total_exposure_usd

    def risk_context_fields(
        self,
        market_id: str,
        strategy_name: str,
        now: datetime | None = None,
    ) -> RiskContextAccountFields:
        """
        Fields to splat into a RiskContext for the given market/strategy.

        Usage:
            RiskContext(..., **account_state.risk_context_fields(market_id, strategy_name))
        """
        return {
            "account_balance_usd": self.equity_usd,
            "daily_pnl_usd": self.daily_pnl_usd(now),
            "weekly_pnl_usd": self.weekly_pnl_usd(now),
            "consecutive_losses": self.consecutive_losses,
            "current_market_exposure_usd": self.market_exposure_usd(market_id),
            "current_strategy_exposure_usd": self.strategy_exposure_usd(strategy_name),
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[OpenPositionRecord]:
        """Snapshot of open positions."""
        return list(self._open_positions.values())

    def get_closed_trades(self) -> list[ClosedTradeRecord]:
        """Snapshot of closed trades in close order."""
        return list(self._closed_trades)
