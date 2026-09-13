"""Replay recorded shadow trades through the SimBroker with realistic costs.

READ-ONLY research tool: it reads runs/shadow artifacts, replays each closed
shadow trade as a SimBroker round trip (fees, latency, quote-age gate, L2
fill), and writes an account-level performance report to runs/sim_replay/.

Honest-data rules (house contract):
- Trades without a usable side-specific exit price are skipped, never
  assigned a synthetic PnL.
- Legacy artifacts record best prices without best-level sizes. The replay
  therefore constructs a single-level book that can absorb the small replay
  clip and discloses this assumption in every report.
- Determinism: fixed assumptions, no RNG, caller-injected timestamps.

Usage:
    uv run python scripts/replay_shadow_trades_sim.py            # write report
    uv run python scripts/replay_shadow_trades_sim.py --dry_run  # no writes
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from polysignal.execution.account_state import AccountState
from polysignal.execution.sim_broker import SimBroker, SimOrderStatus
from polysignal.shadow.execution_cost import L2Level
from polysignal.utils.performance_metrics import compute_performance_metrics

RUNS_DIR = Path("runs")
SHADOW_TRADES_CSV = RUNS_DIR / "shadow" / "shadow_trades.csv"
OUTPUT_DIR = RUNS_DIR / "sim_replay"

DEFAULT_STARTING_CAPITAL_USD = 10000.0
DEFAULT_NOTIONAL_PER_TRADE_USD = 100.0
DEFAULT_FEE_BPS = 0.0  # Polymarket's published base schedule is 0; sensitivity rows cover 50/100
DEFAULT_LATENCY_SECONDS = 5.0
DEFAULT_MAX_QUOTE_AGE_SECONDS = 60.0
REPLAY_BOOK_SIZE_SHARES = 1_000_000.0  # disclosed assumption: top level absorbs the clip


@dataclass
class ReplayAssumptions:
    starting_capital_usd: float = DEFAULT_STARTING_CAPITAL_USD
    notional_per_trade_usd: float = DEFAULT_NOTIONAL_PER_TRADE_USD
    fee_bps: float = DEFAULT_FEE_BPS
    latency_seconds: float = DEFAULT_LATENCY_SECONDS
    max_quote_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS


@dataclass
class RecordedTrade:
    shadow_trade_id: str
    market_id: str
    question: str
    side: str
    entry_time: datetime
    entry_side_price: float
    exit_time: datetime | None
    exit_side_price: float | None
    price_model_status: str
    edge_type: str


@dataclass
class ForwardObservation:
    """One recorded read-only forward price observation."""

    shadow_trade_id: str
    side: str
    timestamp: datetime
    side_best_bid: float | None
    stale: bool


@dataclass
class ReplayResult:
    assumptions: ReplayAssumptions
    trades_loaded: int
    trades_replayed: int = 0
    trades_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    total_pnl_usd: float = 0.0
    final_equity_usd: float = DEFAULT_STARTING_CAPITAL_USD
    metrics: dict = field(default_factory=dict)
    per_trade: list[dict] = field(default_factory=list)


def _parse_float(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _parse_time(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def load_recorded_trades(csv_path: Path) -> list[RecordedTrade]:
    """Load shadow trades that carry a full corrected price model."""
    trades: list[RecordedTrade] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            entry_price = _parse_float(row.get("entry_side_price", ""))
            exit_price = _parse_float(row.get("exit_side_price", ""))
            entry_time = _parse_time(row.get("entry_time", ""))
            exit_time = _parse_time(row.get("exit_time", ""))
            if entry_price is None or entry_price <= 0 or entry_time is None:
                continue
            trades.append(
                RecordedTrade(
                    shadow_trade_id=row.get("shadow_trade_id", ""),
                    market_id=row.get("market_id", ""),
                    question=row.get("question", ""),
                    side=row.get("side", "").strip().upper(),
                    entry_time=entry_time,
                    entry_side_price=entry_price,
                    exit_time=exit_time,
                    exit_side_price=exit_price,
                    price_model_status=row.get("price_model_status", ""),
                    edge_type=row.get("edge_type", ""),
                )
            )
    return trades


def load_forward_observations(jsonl_path: Path) -> dict[str, list[ForwardObservation]]:
    """Load forward observations keyed by shadow trade id (order preserved)."""
    observations: dict[str, list[ForwardObservation]] = {}
    if not jsonl_path.exists():
        return observations
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            trade_id = str(row.get("shadow_trade_id", ""))
            side = str(row.get("side", "")).strip().upper()
            timestamp = _parse_time(str(row.get("timestamp", "")))
            bid_key = "yes_best_bid" if side == "YES" else "no_best_bid"
            bid = _parse_float(str(row.get(bid_key, "")))
            if not trade_id or timestamp is None:
                continue
            observations.setdefault(trade_id, []).append(
                ForwardObservation(
                    shadow_trade_id=trade_id,
                    side=side,
                    timestamp=timestamp,
                    side_best_bid=bid,
                    stale=bool(row.get("stale", False)),
                )
            )
    return observations


def replay_trades(
    trades: list[RecordedTrade],
    assumptions: ReplayAssumptions,
    forward_observations: dict[str, list[ForwardObservation]] | None = None,
) -> ReplayResult:
    """Replay every fully-closed recorded trade through SimBroker."""
    account = AccountState(starting_capital_usd=assumptions.starting_capital_usd)
    broker = SimBroker(
        account,
        fee_bps=assumptions.fee_bps,
        submission_latency_seconds=assumptions.latency_seconds,
        max_quote_age_seconds=assumptions.max_quote_age_seconds,
    )

    result = ReplayResult(assumptions=assumptions, trades_loaded=len(trades))
    equity_curve: list[tuple[datetime, float]] = [
        (trades[0].entry_time if trades else datetime.now().replace(microsecond=0),
         assumptions.starting_capital_usd)
    ]

    for trade in trades:
        if trade.price_model_status and "invalid" in trade.price_model_status:
            result.trades_skipped += 1
            result.skip_reasons["invalid_price_model"] = (
                result.skip_reasons.get("invalid_price_model", 0) + 1
            )
            continue
        if trade.side not in ("YES", "NO"):
            result.trades_skipped += 1
            result.skip_reasons["unknown_side"] = (
                result.skip_reasons.get("unknown_side", 0) + 1
            )
            continue

        # Resolve exit evidence before entering: a replay position without a
        # real observed exit must be skipped, never priced synthetically.
        exit_resolution = _resolve_exit(trade, forward_observations or {})
        if exit_resolution is None:
            result.trades_skipped += 1
            result.skip_reasons["missing_exit_evidence"] = (
                result.skip_reasons.get("missing_exit_evidence", 0) + 1
            )
            continue
        exit_price, exit_time, exit_source = exit_resolution

        entry_book = [L2Level(price=trade.entry_side_price, size=REPLAY_BOOK_SIZE_SHARES)]

        entry_order = broker.submit_buy(
            market_id=trade.market_id,
            strategy_name=trade.edge_type or "shadow_replay",
            asks=entry_book,
            notional_usd=assumptions.notional_per_trade_usd,
            now=trade.entry_time,
            quote_timestamp=trade.entry_time,
        )

        if entry_order.status is SimOrderStatus.REJECTED:
            result.trades_skipped += 1
            result.skip_reasons[f"entry_{entry_order.reject_reason}"] = (
                result.skip_reasons.get(f"entry_{entry_order.reject_reason}", 0) + 1
            )
            continue

        position = broker.get_position(trade.market_id)
        assert position is not None  # filled entry guarantees a share book row

        exit_book = [L2Level(price=exit_price, size=REPLAY_BOOK_SIZE_SHARES)]
        exit_order = broker.submit_sell(
            market_id=trade.market_id,
            bids=exit_book,
            shares=position.shares,
            now=exit_time,
            quote_timestamp=exit_time,
        )

        if exit_order.status is SimOrderStatus.REJECTED:
            result.trades_skipped += 1
            result.skip_reasons[f"exit_{exit_order.reject_reason}"] = (
                result.skip_reasons.get(f"exit_{exit_order.reject_reason}", 0) + 1
            )
            continue

        result.trades_replayed += 1
        realized = exit_order.realized_pnl_usd or 0.0
        result.total_pnl_usd += realized
        equity_curve.append((exit_time, broker.equity_usd()))
        result.per_trade.append(
            {
                "shadow_trade_id": trade.shadow_trade_id,
                "market_id": trade.market_id,
                "side": trade.side,
                "entry_side_price": trade.entry_side_price,
                "exit_side_price": exit_price,
                "exit_source": exit_source,
                "filled_shares": exit_order.filled_shares,
                "fee_usd": entry_order.fee_usd + exit_order.fee_usd,
                "realized_pnl_usd": realized,
            }
        )

    result.final_equity_usd = broker.equity_usd()
    pnls = [row["realized_pnl_usd"] for row in result.per_trade]
    result.metrics = compute_performance_metrics(
        equity_curve,
        pnls,
        traded_notional_usd=broker.traded_notional_usd,
    ).model_dump()
    return result


def _resolve_exit(
    trade: RecordedTrade,
    forward_observations: dict[str, list[ForwardObservation]],
) -> tuple[float, datetime, str] | None:
    """
    Resolve the exit evidence for one trade.

    Preference order:
    1. A recorded side-specific exit price in the shadow trades artifact.
    2. The latest non-stale forward observation for the same trade id and
       side that carries a usable side-specific best bid.
    Returns (exit_bid, exit_time, source) or None when no real evidence
    exists — a synthetic exit price is never invented.
    """
    if trade.exit_side_price is not None and trade.exit_side_price > 0 and trade.exit_time:
        return trade.exit_side_price, trade.exit_time, "recorded_exit"

    candidates = [
        obs
        for obs in forward_observations.get(trade.shadow_trade_id, [])
        if not obs.stale
        and obs.side == trade.side
        and obs.side_best_bid is not None
        and obs.side_best_bid > 0
        and obs.timestamp > trade.entry_time
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda obs: obs.timestamp)
    assert latest.side_best_bid is not None
    return latest.side_best_bid, latest.timestamp, "forward_observation"


def build_report(result: ReplayResult) -> str:
    a = result.assumptions
    notional_display = f"{a.notional_per_trade_usd:.2f} USDT"
    lines = [
        "# SimBroker Replay Report — Recorded Shadow Trades",
        "",
        f"- Trades loaded: {result.trades_loaded}",
        f"- Trades replayed: {result.trades_replayed}",
        f"- Trades skipped: {result.trades_skipped} ({result.skip_reasons})",
        f"- Starting capital: {a.starting_capital_usd:.2f} USDT",
        f"- Notional per trade: {notional_display}",
        f"- Fee assumption: {a.fee_bps:.0f} bps per side",
        f"- Submission latency: {a.latency_seconds:.1f}s; max quote age: "
        f"{a.max_quote_age_seconds:.0f}s",
        "",
        "## Assumptions",
        "",
        "- Entry fills at the recorded side best ask; exit at the recorded side best bid.",
        "- Exit prices come from the recorded artifact when present, otherwise from the "
        "latest non-stale forward observation for the same trade id and side. Trades "
        "without real exit evidence are skipped, never priced synthetically.",
        f"- Legacy artifacts carry no best-level sizes; the replay book assumes the top "
        f"level can absorb the {notional_display} clip. Real top-of-book sizes may "
        "reject; this makes results an upper bound on fill feasibility.",
        "- Fees are a configurable research assumption, not a claim about any venue's "
        "current fee schedule.",
        "",
        "## Account Result",
        "",
        f"- Total realized PnL: {result.total_pnl_usd:.4f} USDT",
        f"- Final equity: {result.final_equity_usd:.4f} USDT",
        f"- Win rate: {result.metrics.get('win_rate')}",
        f"- Profit factor: {result.metrics.get('profit_factor')}",
        f"- Max consecutive losses: {result.metrics.get('max_consecutive_losses')}",
        "",
        "## Per-Trade Detail",
        "",
        "| trade | market | side | entry ask | exit bid | fees | realized PnL |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result.per_trade:
        lines.append(
            f"| {row['shadow_trade_id']} | {row['market_id']} | {row['side']} "
            f"| {row['entry_side_price']:.4f} | {row['exit_side_price']:.4f} "
            f"| {row['fee_usd']:.4f} | {row['realized_pnl_usd']:.4f} |"
        )
    lines.append("")
    lines.append("_Hypothetical research replay. Not a live trading result._")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry_run", action="store_true", help="do not write outputs")
    parser.add_argument("--starting_capital", type=float, default=DEFAULT_STARTING_CAPITAL_USD)
    parser.add_argument("--notional_per_trade", type=float, default=DEFAULT_NOTIONAL_PER_TRADE_USD)
    parser.add_argument("--fee_bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--latency_seconds", type=float, default=DEFAULT_LATENCY_SECONDS)
    args = parser.parse_args()

    if not SHADOW_TRADES_CSV.exists():
        print(f"missing input: {SHADOW_TRADES_CSV}")
        return 1

    assumptions = ReplayAssumptions(
        starting_capital_usd=args.starting_capital,
        notional_per_trade_usd=args.notional_per_trade,
        fee_bps=args.fee_bps,
        latency_seconds=args.latency_seconds,
    )
    trades = load_recorded_trades(SHADOW_TRADES_CSV)
    observations = load_forward_observations(RUNS_DIR / "shadow" / "forward_observations.jsonl")
    result = replay_trades(trades, assumptions, observations)
    report = build_report(result)

    print(report)
    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "sim_replay_report.md").write_text(report, encoding="utf-8")
        (OUTPUT_DIR / "sim_replay_summary.json").write_text(
            json.dumps(
                {
                    "assumptions": vars(assumptions),
                    "trades_loaded": result.trades_loaded,
                    "trades_replayed": result.trades_replayed,
                    "trades_skipped": result.trades_skipped,
                    "skip_reasons": result.skip_reasons,
                    "total_pnl_usd": result.total_pnl_usd,
                    "final_equity_usd": result.final_equity_usd,
                    "metrics": result.metrics,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"written: {OUTPUT_DIR}/sim_replay_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
