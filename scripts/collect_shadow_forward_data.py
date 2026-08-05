#!/usr/bin/env python3
"""
Phase 8F.1 — Offline forward observation collector for shadow positions.

This script only reads existing local artifacts. It never calls real APIs,
real LLM providers, run_paper.py, or execution modules.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from polysignal.shadow.exit_rules import ExitRuleConfig, decide_exit
from polysignal.shadow.forward_observations import ForwardObservation
from polysignal.shadow.models import SHADOW_TRADE_FIELDS, ExitReason, ShadowSide, ShadowTrade, ShadowTradeStatus
from polysignal.shadow.pnl import apply_excursions, apply_exit_to_trade, mark_insufficient_forward_data
from polysignal.shadow.reporter import build_performance_summary, write_performance_report_md, write_performance_summary_json, write_shadow_positions_json, write_shadow_trades_csv


REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect offline forward observations for shadow trades")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--fixed_horizon_minutes", type=int, default=240)
    parser.add_argument("--stop_loss_pct", type=float, default=-0.05)
    parser.add_argument("--take_profit_pct", type=float, default=0.05)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--allow_overwrite", action="store_true", default=False)
    return parser.parse_args(argv)


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_json(path: Path) -> Any:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def verify_safety(
    risk_path: Path = REPO_ROOT / "config" / "risk.yaml",
    llm_path: Path = REPO_ROOT / "config" / "llm.yaml",
) -> dict[str, Any]:
    risk = load_yaml(risk_path)
    llm = load_yaml(llm_path)
    return {
        "live_trading_enabled": bool(risk.get("live_trading_enabled")),
        "allow_auto_execution": bool(risk.get("allow_auto_execution")),
        "paper_trading_enabled": bool(risk.get("paper_trading_enabled")),
        "default_llm_provider": llm.get("provider"),
        "offline_only": True,
        "real_api_calls": False,
        "llm_calls": False,
        "run_paper_invoked": False,
        "trading_actions": False,
        "private_key_handling": False,
    }


def load_shadow_trades(path: Path) -> list[ShadowTrade]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    trades = []
    for row in rows:
        trades.append(shadow_trade_from_row(row))
    return trades


def shadow_trade_from_row(row: dict[str, Any]) -> ShadowTrade:
    payload: dict[str, Any] = {}
    for field in SHADOW_TRADE_FIELDS:
        payload[field] = row.get(field, "")
    payload["side"] = ShadowSide(payload.get("side") or ShadowSide.YES.value)
    payload["entry_price"] = safe_float(payload.get("entry_price"))
    payload["expected_edge"] = safe_float(payload.get("expected_edge"))
    payload["confidence"] = safe_float(payload.get("confidence"))
    payload["entry_yes_best_ask"] = safe_float(payload.get("entry_yes_best_ask"))
    payload["entry_no_best_ask"] = safe_float(payload.get("entry_no_best_ask"))
    payload["entry_yes_best_bid"] = safe_float(payload.get("entry_yes_best_bid"))
    payload["entry_no_best_bid"] = safe_float(payload.get("entry_no_best_bid"))
    payload["entry_side_price"] = safe_float(payload.get("entry_side_price"))
    payload["exit_side_price"] = optional_float(payload.get("exit_side_price"))
    payload["tradable_score"] = safe_float(payload.get("tradable_score"))
    payload["alpha_score"] = safe_float(payload.get("alpha_score"))
    payload["combined_ask"] = safe_float(payload.get("combined_ask"))
    payload["liquidity_score"] = safe_float(payload.get("liquidity_score"))
    payload["ambiguity_risk"] = safe_float(payload.get("ambiguity_risk"))
    payload["exit_price"] = optional_float(payload.get("exit_price"))
    payload["exit_time"] = payload.get("exit_time") or None
    payload["exit_reason"] = ExitReason(payload.get("exit_reason") or ExitReason.OPEN.value)
    payload["pnl"] = safe_float(payload.get("pnl"))
    payload["return_pct"] = safe_float(payload.get("return_pct"))
    payload["status"] = ShadowTradeStatus(payload.get("status") or ShadowTradeStatus.OPEN.value)
    payload["orderbook_spread"] = safe_float(payload.get("orderbook_spread"))
    payload["orderbook_depth"] = safe_float(payload.get("orderbook_depth"))
    payload["max_adverse_excursion"] = safe_float(payload.get("max_adverse_excursion"))
    payload["max_favorable_excursion"] = safe_float(payload.get("max_favorable_excursion"))
    payload["holding_minutes"] = safe_float(payload.get("holding_minutes"))
    return ShadowTrade(**payload)


def load_existing_forward_observations(path: Path) -> list[ForwardObservation]:
    if not path.exists():
        return []
    observations = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            observations.append(ForwardObservation.from_dict(json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return observations


def build_trajectory_index(raw: Any) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(raw, list):
        return index
    for item in raw:
        if not isinstance(item, dict):
            continue
        market_id = str(item.get("market_id") or "")
        trajectory = item.get("trajectory", [])
        if market_id and isinstance(trajectory, list):
            index[market_id] = [obs for obs in trajectory if isinstance(obs, dict)]
    return index


def observation_from_trajectory(trade: ShadowTrade, observation: dict[str, Any]) -> Optional[ForwardObservation]:
    timestamp = str(observation.get("timestamp") or "")
    observed_price = optional_float(observation.get("observed_price"))
    if observed_price is None:
        observed_price = optional_float(observation.get("combined_ask"))
    if observed_price is None:
        observed_price = optional_float(observation.get("price"))
    if not timestamp or observed_price is None:
        return None
    return ForwardObservation(
        shadow_trade_id=trade.shadow_trade_id,
        market_id=trade.market_id,
        timestamp=timestamp,
        observed_price=observed_price,
        yes_price=safe_float(observation.get("yes_price")),
        no_price=safe_float(observation.get("no_price")),
        combined_ask=safe_float(observation.get("combined_ask"), observed_price),
        spread=safe_float(observation.get("spread")),
        liquidity=safe_float(observation.get("liquidity"), safe_float(observation.get("volume"))),
        source="market_trajectories",
        stale=bool(observation.get("stale")),
        run_id=str(observation.get("run_id") or ""),
        question=trade.question,
        side=trade.side.value,
        notes="market_closed" if bool(observation.get("market_closed")) else "",
    )


def collect_forward_observations_for_trade(
    trade: ShadowTrade,
    trajectory_index: dict[str, list[dict[str, Any]]],
    existing: list[ForwardObservation],
) -> list[ForwardObservation]:
    entry_time = parse_time(trade.entry_time)
    observations = [
        obs for obs in existing
        if obs.shadow_trade_id == trade.shadow_trade_id or obs.market_id == trade.market_id
    ]
    for raw in trajectory_index.get(trade.market_id, []):
        obs = observation_from_trajectory(trade, raw)
        if obs is None:
            continue
        obs_time = parse_time(obs.timestamp)
        if entry_time and obs_time and obs_time <= entry_time:
            continue
        observations.append(obs)

    deduped: dict[tuple[str, str], ForwardObservation] = {}
    for obs in observations:
        key = (obs.shadow_trade_id or trade.shadow_trade_id, obs.timestamp)
        deduped[key] = obs
    return sorted(deduped.values(), key=lambda obs: obs.timestamp)


def update_trade_with_forward_data(
    trade: ShadowTrade,
    observations: list[ForwardObservation],
    exit_config: ExitRuleConfig,
) -> ShadowTrade:
    if not observations:
        return mark_insufficient_forward_data(trade)
    exit_observations = [obs.to_exit_observation() for obs in observations]
    decision = decide_exit(trade, exit_observations, exit_config)
    if not decision.should_exit or decision.exit_price is None:
        return mark_insufficient_forward_data(trade, reason="missing_exit_side_bid")
    apply_exit_to_trade(
        trade,
        decision.exit_time,
        decision.exit_price,
        decision.reason,
        decision.holding_minutes,
    )
    apply_excursions(trade, exit_observations)
    return trade


def collect_and_update(
    runs_dir: Path,
    shadow_dir: Path,
    exit_config: ExitRuleConfig,
) -> tuple[list[ShadowTrade], list[ForwardObservation], dict[str, Any]]:
    trades_path = shadow_dir / "shadow_trades.csv"
    if not trades_path.exists():
        trades_path = shadow_dir / "updated_shadow_trades.csv"
    if not trades_path.exists():
        trades_path = shadow_dir / "shadow_trades_with_tokens.csv"
    trades = load_shadow_trades(trades_path)
    load_json(shadow_dir / "shadow_positions.json")
    trajectory_index = build_trajectory_index(load_json(runs_dir / "market_trajectories.json"))
    existing_observations = load_existing_forward_observations(shadow_dir / "forward_observations.jsonl")

    updated_trades: list[ShadowTrade] = []
    collected: list[ForwardObservation] = []
    for trade in trades:
        observations = collect_forward_observations_for_trade(trade, trajectory_index, existing_observations)
        collected.extend(observations)
        updated_trades.append(update_trade_with_forward_data(trade, observations, exit_config))

    collected = dedupe_forward_observations(collected)
    summary = {
        "positions_loaded": len(trades),
        "forward_observations_found": len(collected),
        "positions_would_close": len([trade for trade in updated_trades if trade.status == ShadowTradeStatus.CLOSED]),
        "positions_would_remain_insufficient_forward_data": len([
            trade for trade in updated_trades
            if trade.status == ShadowTradeStatus.INSUFFICIENT_FORWARD_DATA
        ]),
        "forward_data_limitation": any(
            trade.status == ShadowTradeStatus.INSUFFICIENT_FORWARD_DATA
            for trade in updated_trades
        ),
    }
    return updated_trades, collected, summary


def dedupe_forward_observations(observations: list[ForwardObservation]) -> list[ForwardObservation]:
    seen: dict[tuple[str, str], ForwardObservation] = {}
    for obs in observations:
        seen[(obs.shadow_trade_id, obs.timestamp)] = obs
    return sorted(seen.values(), key=lambda obs: (obs.shadow_trade_id, obs.timestamp))


def write_forward_observations_jsonl(path: Path, observations: list[ForwardObservation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(obs.to_dict(), sort_keys=True) for obs in observations]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def write_updated_outputs(
    shadow_dir: Path,
    trades: list[ShadowTrade],
    observations: list[ForwardObservation],
    collection_summary: dict[str, Any],
) -> dict[str, str]:
    shadow_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "forward_observations_jsonl": shadow_dir / "forward_observations.jsonl",
        "updated_shadow_positions_json": shadow_dir / "updated_shadow_positions.json",
        "updated_shadow_trades_csv": shadow_dir / "updated_shadow_trades.csv",
        "paper_performance_summary_json": shadow_dir / "paper_performance_summary.json",
        "paper_performance_report_md": shadow_dir / "paper_performance_report.md",
    }
    write_forward_observations_jsonl(paths["forward_observations_jsonl"], observations)
    write_shadow_positions_json(paths["updated_shadow_positions_json"], trades)
    write_shadow_trades_csv(paths["updated_shadow_trades_csv"], trades)
    summary = build_performance_summary(trades, verify_safety())
    summary["forward_observation_summary"] = collection_summary
    summary["forward_data_limitation"] = collection_summary.get("forward_data_limitation", False)
    write_performance_summary_json(paths["paper_performance_summary_json"], summary)
    write_performance_report_md(paths["paper_performance_report_md"], summary, trades)
    return {key: str(value) for key, value in paths.items()}


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: collect shadow forward data" if dry_run else "Collect shadow forward data")
    print(f"positions_loaded: {summary['positions_loaded']}")
    print(f"forward_observations_found: {summary['forward_observations_found']}")
    print(f"positions_would_close: {summary['positions_would_close']}")
    print(
        "positions_would_remain_insufficient_forward_data: "
        f"{summary['positions_would_remain_insufficient_forward_data']}"
    )
    print(f"forward_data_limitation: {summary['forward_data_limitation']}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    exit_config = ExitRuleConfig(
        fixed_horizon_minutes=args.fixed_horizon_minutes,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
    )
    trades, observations, summary = collect_and_update(
        Path(args.runs_dir),
        Path(args.shadow_dir),
        exit_config,
    )
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    paths = write_updated_outputs(Path(args.shadow_dir), trades, observations, summary)
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
