"""

SimBroker - Account-level simulated broker for realistic trading validation

IMPORTANT:
- This module is a research/validation tool. It never touches a network,
  a wallet, or any live-trading path.
- Deterministic by construction: no RNG. Faults are injected by explicit
  order-sequence schedules, timestamps are caller-provided, and fills come
  from the pure L2 sweep in polysignal.shadow.execution_cost.
- Cash, exposure, and realized PnL are ledgered through AccountState, so the
  Risk Governor's account-level hard rejections (daily/weekly/consecutive
  loss) see exactly the same state a live runner would feed them.
- Failure modes modelled: insufficient cash, injected network error, injected
  API timeout, injected venue rejection, stale quote at fill time (latency),
  insufficient visible depth, crossed book, oversell, partial close refusal.
- Full closes only (mirrors PaperTrader.close_position). Partial exits are
  rejected fail-closed until a partial-close ledger contract exists.
- Fees: flat notional bps per side (the same research convention as
  shadow/execution_cost), charged on filled notional.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import Enum
from math import isfinite
from uuid import uuid4

from pydantic import BaseModel, Field

from polysignal.execution.account_state import AccountState
from polysignal.shadow.execution_cost import (
    FillStatus,
    L2Level,
    simulate_buy_notional,
    simulate_sell_shares,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


class SimOrderStatus(str, Enum):
    """Outcome of a simulated order."""

    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"


class SimSide(str, Enum):
    """Aggressor side of a simulated order."""

    BUY = "buy"
    SELL = "sell"


class FaultSchedule:
    """
    Deterministic fault injection by 0-based order sequence number.

    Example: FaultSchedule(network_errors={0}, rejections={2}) makes the first
    simulated order fail with a network error and the third be rejected by the
    venue. Schedules are plain data, so tests and replay runs are repeatable.
    """

    def __init__(
        self,
        network_errors: set[int] | None = None,
        api_timeouts: set[int] | None = None,
        rejections: set[int] | None = None,
    ):
        self.network_errors = set(network_errors or ())
        self.api_timeouts = set(api_timeouts or ())
        self.rejections = set(rejections or ())


class SimPosition(BaseModel):
    """Share-level view of one open market position (buy-net-cost basis)."""

    market_id: str
    strategy_name: str
    shares: float = Field(ge=0)
    avg_net_entry_price: float = Field(ge=0)
    total_net_cost_usd: float = Field(ge=0)


class SimOrder(BaseModel):
    """Auditable record of one simulated order attempt."""

    order_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int
    market_id: str
    strategy_name: str
    side: SimSide
    status: SimOrderStatus
    requested_notional_usd: float | None = None
    requested_shares: float | None = None
    filled_notional_usd: float = 0.0
    filled_shares: float = 0.0
    fee_usd: float = 0.0
    realized_pnl_usd: float | None = None
    reject_reason: str = ""
    quote_timestamp: datetime | None = None
    decision_time: datetime
    fill_time: datetime
    execution_cost: dict = Field(default_factory=dict)


class SimBroker:
    """
    Deterministic account-level simulated broker.

    Usage shape (replay research only):

        broker = SimBroker(account_state, fee_bps=10, submission_latency_seconds=2.0)
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=levels, notional_usd=100.0,
            limit_price=0.55, now=decision_time, quote_timestamp=quote_time,
        )
    """

    def __init__(
        self,
        account_state: AccountState,
        fee_bps: float = 0.0,
        submission_latency_seconds: float = 0.0,
        max_quote_age_seconds: float = 60.0,
        allow_partial_fills: bool = False,
        fault_schedule: FaultSchedule | None = None,
    ):
        if not isfinite(fee_bps) or not 0.0 <= fee_bps <= 10_000.0:
            raise ValueError("fee_bps must be finite and in [0, 10000]")
        if not isfinite(submission_latency_seconds) or submission_latency_seconds < 0:
            raise ValueError("submission_latency_seconds must be finite and >= 0")
        if not isfinite(max_quote_age_seconds) or max_quote_age_seconds < 0:
            raise ValueError("max_quote_age_seconds must be finite and >= 0")

        self.account_state = account_state
        self.fee_bps = fee_bps
        self.submission_latency_seconds = submission_latency_seconds
        self.max_quote_age_seconds = max_quote_age_seconds
        self.allow_partial_fills = allow_partial_fills
        self.fault_schedule = fault_schedule or FaultSchedule()

        self._sequence = 0
        self._share_book: dict[str, SimPosition] = {}
        self.orders: list[SimOrder] = []
        self.traded_notional_usd = 0.0

    # ------------------------------------------------------------------
    # Order entry
    # ------------------------------------------------------------------

    def submit_buy(
        self,
        *,
        market_id: str,
        strategy_name: str,
        asks: Iterable[L2Level],
        notional_usd: float,
        limit_price: float | None = None,
        now: datetime | None = None,
        quote_timestamp: datetime | None = None,
    ) -> SimOrder:
        """Buy outcome shares by spending `notional_usd` through visible asks."""
        decision_time = _normalize_utc(now) if now is not None else _utc_now()
        sequence = self._sequence
        self._sequence += 1

        def reject(reason: str) -> SimOrder:
            return self._record_reject(
                sequence=sequence,
                market_id=market_id,
                strategy_name=strategy_name,
                side=SimSide.BUY,
                reason=reason,
                decision_time=decision_time,
                quote_timestamp=quote_timestamp,
                requested_notional_usd=notional_usd,
            )

        if not isfinite(notional_usd) or notional_usd <= 0:
            return reject("invalid_notional")
        if notional_usd > self.account_state.cash_usd:
            return reject("insufficient_cash")

        fault_reason = self._injected_fault(sequence)
        if fault_reason:
            return reject(fault_reason)

        fill_time = decision_time + timedelta_seconds(self.submission_latency_seconds)
        stale_reason = self._quote_staleness(fill_time, quote_timestamp)
        if stale_reason:
            return reject(stale_reason)

        cost = simulate_buy_notional(
            asks,
            notional_usd,
            fee_bps=self.fee_bps,
            limit_price=limit_price,
            allow_partial=self.allow_partial_fills,
        )
        if cost.status is FillStatus.REJECTED:
            return reject(f"l2_{cost.reject_reason or 'not_fillable'}")

        filled_cost = cost.filled_notional_usd + cost.fee_usd
        self.account_state.record_open(
            market_id=market_id,
            strategy_name=strategy_name,
            notional_usd=filled_cost,
        )
        self._update_share_book_on_buy(
            market_id=market_id,
            strategy_name=strategy_name,
            shares=cost.filled_shares,
            net_cost=filled_cost,
        )
        self.traded_notional_usd += cost.filled_notional_usd

        return self._record_fill(
            sequence=sequence,
            market_id=market_id,
            strategy_name=strategy_name,
            side=SimSide.BUY,
            status=SimOrderStatus.FILLED
            if cost.status is FillStatus.FULL
            else SimOrderStatus.PARTIAL,
            filled_notional=cost.filled_notional_usd,
            filled_shares=cost.filled_shares,
            fee=cost.fee_usd,
            decision_time=decision_time,
            fill_time=fill_time,
            quote_timestamp=quote_timestamp,
            execution_cost=cost.model_dump(),
        )

    def submit_sell(
        self,
        *,
        market_id: str,
        bids: Iterable[L2Level],
        shares: float,
        limit_price: float | None = None,
        now: datetime | None = None,
        quote_timestamp: datetime | None = None,
    ) -> SimOrder:
        """
        Sell the full open position on a market through visible bids.

        `shares` must equal the currently held amount (full close only);
        anything else fails closed. Realized PnL is proceeds minus buy-net
        cost, ledgered through AccountState.record_close.
        """
        decision_time = _normalize_utc(now) if now is not None else _utc_now()
        sequence = self._sequence
        self._sequence += 1

        position = self._share_book.get(market_id)

        def reject(reason: str) -> SimOrder:
            return self._record_reject(
                sequence=sequence,
                market_id=market_id,
                strategy_name=position.strategy_name if position else "unknown",
                side=SimSide.SELL,
                reason=reason,
                decision_time=decision_time,
                quote_timestamp=quote_timestamp,
                requested_shares=shares,
            )

        if position is None:
            return reject("no_open_position")
        if not isfinite(shares) or shares <= 0:
            return reject("invalid_shares")
        if shares != position.shares:
            return reject(
                "full_close_only"
                if shares < position.shares
                else "oversell_blocked"
            )

        fault_reason = self._injected_fault(sequence)
        if fault_reason:
            return reject(fault_reason)

        fill_time = decision_time + timedelta_seconds(self.submission_latency_seconds)
        stale_reason = self._quote_staleness(fill_time, quote_timestamp)
        if stale_reason:
            return reject(stale_reason)

        proceeds = simulate_sell_shares(
            bids,
            shares,
            fee_bps=self.fee_bps,
            limit_price=limit_price,
            allow_partial=self.allow_partial_fills,
        )
        if proceeds.status is FillStatus.REJECTED:
            return reject(f"l2_{proceeds.reject_reason or 'not_fillable'}")

        net_proceeds = proceeds.filled_notional_usd - proceeds.fee_usd
        realized_pnl = net_proceeds - position.total_net_cost_usd
        self.account_state.record_close(
            market_id=market_id,
            realized_pnl_usd=realized_pnl,
            now=fill_time,
        )
        del self._share_book[market_id]
        self.traded_notional_usd += proceeds.filled_notional_usd

        return self._record_fill(
            sequence=sequence,
            market_id=market_id,
            strategy_name=position.strategy_name,
            side=SimSide.SELL,
            status=SimOrderStatus.FILLED
            if proceeds.status is FillStatus.FULL
            else SimOrderStatus.PARTIAL,
            filled_notional=proceeds.filled_notional_usd,
            filled_shares=proceeds.filled_shares,
            fee=proceeds.fee_usd,
            decision_time=decision_time,
            fill_time=fill_time,
            quote_timestamp=quote_timestamp,
            realized_pnl=realized_pnl,
            execution_cost=proceeds.model_dump(),
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_position(self, market_id: str) -> SimPosition | None:
        """Share-level open position for one market."""
        return self._share_book.get(market_id)

    def get_all_positions(self) -> list[SimPosition]:
        """All open share-level positions."""
        return list(self._share_book.values())

    def equity_usd(self) -> float:
        """Current account equity (cash + open entry cost; unrealized excluded)."""
        return self.account_state.equity_usd

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _injected_fault(self, sequence: int) -> str:
        schedule = self.fault_schedule
        if sequence in schedule.network_errors:
            return "injected_network_error"
        if sequence in schedule.api_timeouts:
            return "injected_api_timeout"
        if sequence in schedule.rejections:
            return "injected_venue_rejection"
        return ""

    def _quote_staleness(
        self,
        fill_time: datetime,
        quote_timestamp: datetime | None,
    ) -> str:
        if quote_timestamp is None:
            return ""
        quote_time = _normalize_utc(quote_timestamp)
        age = (fill_time - quote_time).total_seconds()
        if age < -5.0:
            return "quote_from_future"
        if age > self.max_quote_age_seconds:
            return "quote_too_stale_at_fill"
        return ""

    def _update_share_book_on_buy(
        self,
        market_id: str,
        strategy_name: str,
        shares: float,
        net_cost: float,
    ) -> None:
        existing = self._share_book.get(market_id)
        if existing is None:
            self._share_book[market_id] = SimPosition(
                market_id=market_id,
                strategy_name=strategy_name,
                shares=shares,
                avg_net_entry_price=net_cost / shares if shares > 0 else 0.0,
                total_net_cost_usd=net_cost,
            )
            return
        total_cost = existing.total_net_cost_usd + net_cost
        total_shares = existing.shares + shares
        existing.total_net_cost_usd = total_cost
        existing.shares = total_shares
        existing.avg_net_entry_price = total_cost / total_shares if total_shares > 0 else 0.0

    def _record_fill(
        self,
        *,
        sequence: int,
        market_id: str,
        strategy_name: str,
        side: SimSide,
        status: SimOrderStatus,
        filled_notional: float,
        filled_shares: float,
        fee: float,
        decision_time: datetime,
        fill_time: datetime,
        quote_timestamp: datetime | None,
        realized_pnl: float | None = None,
        execution_cost: dict | None = None,
    ) -> SimOrder:
        order = SimOrder(
            sequence=sequence,
            market_id=market_id,
            strategy_name=strategy_name,
            side=side,
            status=status,
            filled_notional_usd=filled_notional,
            filled_shares=filled_shares,
            fee_usd=fee,
            realized_pnl_usd=realized_pnl,
            quote_timestamp=_normalize_utc(quote_timestamp) if quote_timestamp else None,
            decision_time=decision_time,
            fill_time=fill_time,
            execution_cost=execution_cost or {},
        )
        self.orders.append(order)
        return order

    def _record_reject(
        self,
        *,
        sequence: int,
        market_id: str,
        strategy_name: str,
        side: SimSide,
        reason: str,
        decision_time: datetime,
        quote_timestamp: datetime | None,
        requested_notional_usd: float | None = None,
        requested_shares: float | None = None,
    ) -> SimOrder:
        order = SimOrder(
            sequence=sequence,
            market_id=market_id,
            strategy_name=strategy_name,
            side=side,
            status=SimOrderStatus.REJECTED,
            requested_notional_usd=requested_notional_usd,
            requested_shares=requested_shares,
            reject_reason=reason,
            quote_timestamp=_normalize_utc(quote_timestamp) if quote_timestamp else None,
            decision_time=decision_time,
            fill_time=decision_time + timedelta_seconds(self.submission_latency_seconds),
        )
        self.orders.append(order)
        return order


def timedelta_seconds(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)
