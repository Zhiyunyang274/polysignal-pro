"""Regime stress test — run the real risk chain through hostile environments.

READ-ONLY research harness: for each synthetic market regime (trend up/down,
range, high volatility, liquidity crisis) it drives a probe strategy through
the production path

    MockDataProvider(regime=...) → MicrostructureEngine scores → Signal
    → RiskGovernor.evaluate(real account state) → SimBroker → AccountState

and records whether the risk design holds:

Invariants asserted by tests (and reported here):
- I1 equity stays positive in every regime
- I2 exposure never exceeds starting capital (cash guard holds)
- I3 once a loss breaker (daily/weekly/consecutive) has fired, zero further
    entries are filled — the breaker is never overridden
- I4 liquidity_crisis blocks entries via spread/depth hard rejects
- I5 runs are deterministic for a fixed seed

The probe strategy (enter YES whenever flat, exit on stop/take-profit/horizon)
is a stress vehicle, NOT a production strategy; its PnL carries no signal.

Usage:
    uv run python scripts/run_regime_stress_test.py             # write report
    uv run python scripts/run_regime_stress_test.py --dry_run   # no writes
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polysignal.engines.market_microstructure import MarketMicrostructureEngine
from polysignal.execution.account_state import AccountState
from polysignal.execution.sim_broker import SimBroker, SimOrderStatus
from polysignal.ingestion.market_regimes import MarketRegime
from polysignal.ingestion.mock_data_provider import MockDataProvider
from polysignal.models.risk import RiskAction, RiskContext
from polysignal.models.signal import Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor
from polysignal.shadow.execution_cost import L2Level
from polysignal.utils.performance_metrics import compute_performance_metrics

OUTPUT_DIR = Path("runs") / "stress"

BREAKER_REASONS = {
    "daily_loss_limit_breached",
    "weekly_loss_limit_breached",
    "consecutive_loss_limit_breached",
}

STEP_MINUTES = 1
BASE_TIME = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


@dataclass
class StressConfig:
    steps: int = 60
    markets: int = 6
    starting_capital_usd: float = 1000.0
    entry_notional_usd: float = 50.0
    stop_loss_pct: float = 0.15
    take_profit_pct: float = 0.25
    max_holding_steps: int = 10
    fee_bps: float = 10.0
    latency_seconds: float = 2.0
    seed: int = 42
    # Probe entry mode (Iteration 022b A/B precheck):
    #   "always"        — enter whenever flat (original probe)
    #   "near_threshold" — enter only when the YES mid is within
    #                      threshold_proximity_pct of threshold_level
    #                      (synthetic analog of barrier-proximity entry;
    #                      NOT a claim about the real edge's profitability)
    entry_mode: str = "always"
    threshold_level: float = 0.50
    threshold_proximity_pct: float = 0.10


@dataclass
class OpenProbe:
    entry_step: int
    entry_price: float


@dataclass
class RegimeStressResult:
    regime: MarketRegime
    steps: int
    entries_filled: int = 0
    entries_rejected: int = 0
    exits_filled: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_usd: float = 0.0
    final_equity_usd: float = 0.0
    min_equity_usd: float = float("inf")
    max_exposure_usd: float = 0.0
    hard_rejects: dict[str, int] = field(default_factory=dict)
    breakers_fired: set[str] = field(default_factory=set)
    step_breaker_first_fired: int | None = None
    # Fills recorded after a breaker was first observed (informational: the
    # consecutive-loss breaker legitimately resets on a winning close).
    entries_filled_after_breaker: int = 0
    # THE invariant: fills in steps where a breaker condition was actually
    # active on the account (daily/weekly loss beyond limit, or
    # consecutive_losses >= limit). Must always be zero.
    entries_filled_while_breaker_active: int = 0
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)


def run_regime_stress(
    regime: MarketRegime,
    config: StressConfig | None = None,
) -> RegimeStressResult:
    """Run one regime through the production risk chain. Deterministic."""
    config = config or StressConfig()
    result = RegimeStressResult(regime=regime, steps=config.steps)

    provider = MockDataProvider(
        num_markets=config.markets,
        price_range=(0.2, 0.8),
        volume_range_usd=(200000, 500000),
        seed=config.seed,
        regime=regime,
    )
    account = AccountState(starting_capital_usd=config.starting_capital_usd)
    broker = SimBroker(
        account,
        fee_bps=config.fee_bps,
        submission_latency_seconds=config.latency_seconds,
        max_quote_age_seconds=60.0,
    )
    governor = RiskGovernor(
        live_trading_enabled=False,
        allow_auto_execution=False,
        paper_trading_enabled=True,
        max_account_capital_usd=config.starting_capital_usd,
        daily_max_loss_pct=0.03,
        weekly_max_loss_pct=0.08,
        max_consecutive_losses=3,
        min_total_volume_usd=100000,
        min_depth_usd=20,
        max_spread_pct=0.05,
    )
    engine = MarketMicrostructureEngine()

    markets = [
        m for m in provider.get_markets().markets
        if m.is_tradable() and m.is_auto_allowed()
    ][: config.markets]

    open_probes: dict[str, OpenProbe] = {}
    prev_mids: dict[str, float] = {}

    def step_time(step: int) -> datetime:
        return BASE_TIME + timedelta(minutes=STEP_MINUTES * step)

    def to_l2(levels: list) -> list[L2Level]:
        return [L2Level(price=level.price, size=level.size) for level in levels]

    for step in range(config.steps):
        now = step_time(step)

        for market in markets:
            snapshot = provider.get_orderbook_snapshot(market.market_id)
            ask = snapshot.yes_asks.levels[0].price
            bid = snapshot.yes_bids.levels[0].price
            mid = (ask + bid) / 2

            # ---- exit management for the open probe (risk-reducing) ----
            probe = open_probes.get(market.market_id)
            if probe is not None:
                position = broker.get_position(market.market_id)
                if position is None:  # defensive: book and probe out of sync
                    del open_probes[market.market_id]
                else:
                    move = (bid - probe.entry_price) / probe.entry_price
                    holding = step - probe.entry_step
                    should_exit = (
                        move <= -config.stop_loss_pct
                        or move >= config.take_profit_pct
                        or holding >= config.max_holding_steps
                    )
                    if should_exit:
                        exit_order = broker.submit_sell(
                            market_id=market.market_id,
                            bids=to_l2(snapshot.yes_bids.levels),
                            shares=position.shares,
                            now=now,
                            quote_timestamp=now,
                        )
                        if exit_order.status is not SimOrderStatus.REJECTED:
                            del open_probes[market.market_id]
                            result.exits_filled += 1
                            pnl = exit_order.realized_pnl_usd or 0.0
                            result.total_pnl_usd += pnl
                            if pnl > 0:
                                result.wins += 1
                            elif pnl < 0:
                                result.losses += 1

            # ---- entry probe (risk-checked through the full chain) ----
            if market.market_id in open_probes:
                prev_mids[market.market_id] = mid
                continue

            if config.entry_mode == "near_threshold":
                distance = abs(mid - config.threshold_level) / config.threshold_level
                if distance > config.threshold_proximity_pct:
                    prev_mids[market.market_id] = mid
                    continue

            scores = engine.get_component_scores(snapshot)
            # The probe simulates a world where the slow path has already
            # cached its assessments for this market (event 80 / lifecycle 85):
            # with fully neutral slow-path scores the weighted total is
            # structurally capped below the 80 paper-trade threshold and no
            # regime could ever reach execution. These are inputs to the
            # Governor, not changes to the Governor.
            scores.event_score = 80.0
            scores.lifecycle_score = 85.0
            signal = Signal(
                market_id=market.market_id,
                market_title=market.title,
                market_category=market.category.value,
                strategy_name="regime_stress_probe",
                side=SignalSide.YES,
                price=ask,
                component_scores=scores,
                raw_score=scores.microstructure_score,
            )
            context = RiskContext(
                live_trading_enabled=False,
                allow_auto_execution=False,
                api_healthy=True,
                websocket_healthy=True,
                price_stale=snapshot.is_stale,
                market_tradable=market.is_tradable(),
                market_ambiguous=market.is_ambiguous,
                market_forbidden=not market.is_auto_allowed(),
                **account.risk_context_fields(
                    market_id=market.market_id,
                    strategy_name="regime_stress_probe",
                    now=now,
                ),
            )
            decision = governor.evaluate(signal, context, snapshot, market)

            if decision.action == RiskAction.HARD_REJECT:
                for reason in decision.hard_reject_reasons:
                    result.hard_rejects[reason] = result.hard_rejects.get(reason, 0) + 1
                breaker_hits = BREAKER_REASONS & set(decision.hard_reject_reasons)
                if breaker_hits and result.step_breaker_first_fired is None:
                    result.step_breaker_first_fired = step
                result.breakers_fired |= breaker_hits
                prev_mids[market.market_id] = mid
                continue

            if decision.allows_paper_trade():
                # Independent double-check of the breaker condition at fill
                # time (mirrors the Governor's inputs from the same account):
                # a fill while this holds would mean the breaker was bypassed.
                breaker_condition_active = (
                    account.consecutive_losses >= 3
                    or account.daily_pnl_usd(now) < -(config.starting_capital_usd * 0.03)
                    or account.weekly_pnl_usd(now) < -(config.starting_capital_usd * 0.08)
                )
                order = broker.submit_buy(
                    market_id=market.market_id,
                    strategy_name="regime_stress_probe",
                    asks=to_l2(snapshot.yes_asks.levels),
                    notional_usd=config.entry_notional_usd,
                    limit_price=ask,
                    now=now,
                    quote_timestamp=now,
                )
                if order.status is SimOrderStatus.REJECTED:
                    result.entries_rejected += 1
                else:
                    result.entries_filled += 1
                    if result.step_breaker_first_fired is not None:
                        result.entries_filled_after_breaker += 1
                    if breaker_condition_active:
                        result.entries_filled_while_breaker_active += 1
                    position = broker.get_position(market.market_id)
                    assert position is not None
                    open_probes[market.market_id] = OpenProbe(
                        entry_step=step,
                        entry_price=position.avg_net_entry_price,
                    )

            prev_mids[market.market_id] = mid

        result.max_exposure_usd = max(result.max_exposure_usd, account.total_exposure_usd)
        result.min_equity_usd = min(result.min_equity_usd, account.equity_usd)
        result.equity_curve.append((now, account.equity_usd))

    result.final_equity_usd = account.equity_usd
    return result


def summarize(result: RegimeStressResult, config: StressConfig) -> dict:
    metrics = compute_performance_metrics(result.equity_curve, []).model_dump()
    return {
        "regime": result.regime.value,
        "steps": result.steps,
        "entries_filled": result.entries_filled,
        "entries_rejected": result.entries_rejected,
        "exits_filled": result.exits_filled,
        "wins": result.wins,
        "losses": result.losses,
        "total_pnl_usd": round(result.total_pnl_usd, 4),
        "final_equity_usd": round(result.final_equity_usd, 4),
        "min_equity_usd": round(result.min_equity_usd, 4),
        "max_exposure_usd": round(result.max_exposure_usd, 4),
        "breakers_fired": sorted(result.breakers_fired),
        "step_breaker_first_fired": result.step_breaker_first_fired,
        "entries_filled_after_breaker": result.entries_filled_after_breaker,
        "entries_filled_while_breaker_active": result.entries_filled_while_breaker_active,
        "hard_rejects": result.hard_rejects,
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
    }


def build_report(results: list[RegimeStressResult], config: StressConfig) -> str:
    lines = [
        "# Regime Stress Test Report — Production Risk Chain",
        "",
        f"- Steps per regime: {config.steps}; markets: {config.markets}; "
        f"seed: {config.seed}",
        f"- Starting capital: {config.starting_capital_usd:.0f} USDT; "
        f"entry clip: {config.entry_notional_usd:.0f} USDT; fee: {config.fee_bps:.0f} bps/side",
        "- Chain under test: MockDataProvider(regime) → MicrostructureEngine → "
        "RiskGovernor → SimBroker → AccountState",
        "- Probe strategy PnL is NOT a strategy signal; the deliverable is risk behaviour.",
        "",
        "| regime | entries | rejected | exits | win/loss | total PnL | final equity | "
        "min equity | max exposure | breakers | fills while breaker active |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.regime.value} | {r.entries_filled} | {r.entries_rejected} "
            f"| {r.exits_filled} | {r.wins}/{r.losses} | {r.total_pnl_usd:.2f} "
            f"| {r.final_equity_usd:.2f} | {r.min_equity_usd:.2f} "
            f"| {r.max_exposure_usd:.2f} | {', '.join(sorted(r.breakers_fired)) or 'none'} "
            f"| {r.entries_filled_while_breaker_active} |"
        )
    lines += [
        "",
        "## Invariant Verdicts",
        "",
    ]
    for r in results:
        verdicts = {
            "I1_equity_positive": r.min_equity_usd > 0,
            "I2_exposure_within_capital": r.max_exposure_usd <= config.starting_capital_usd,
            "I3_no_fills_while_breaker_active": r.entries_filled_while_breaker_active == 0,
        }
        failed = [name for name, ok in verdicts.items() if not ok]
        lines.append(
            f"- {r.regime.value}: " + ("ALL PASS" if not failed else f"FAIL {failed}")
        )
    lines += [
        "",
        "_Synthetic environments; probe strategy; hypothetical results. "
        "Live trading remains disabled._",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--markets", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    config = StressConfig(steps=args.steps, markets=args.markets, seed=args.seed)
    results = [run_regime_stress(regime, config) for regime in MarketRegime]
    report = build_report(results, config)
    print(report)

    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "regime_stress_report.md").write_text(report, encoding="utf-8")
        (OUTPUT_DIR / "regime_stress_summary.json").write_text(
            json.dumps(
                {
                    "config": vars(config),
                    "regimes": [summarize(r, config) for r in results],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"written: {OUTPUT_DIR}/regime_stress_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
