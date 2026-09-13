#!/usr/bin/env python3
"""
Phase 8F.2 — Read-only forward price polling for shadow positions.

This script polls public CLOB orderbooks for shadow-only PnL evaluation.
It does not authenticate, sign, place orders, cancel orders, call LLMs, or
invoke run_paper.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import scripts.collect_shadow_forward_data as collector
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.shadow.exit_rules import ExitRuleConfig
from polysignal.shadow.forward_observations import (
    ForwardObservation,
    ShadowTokenIdResolver,
    TokenIdResolution,
)
from polysignal.shadow.models import ShadowSide, ShadowTrade, ShadowTradeStatus
from polysignal.utils.time import utc_now

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PollConfig:
    shadow_dir: Path
    runs_dir: Path
    interval_seconds: int = 300
    duration_minutes: int = 60
    once: bool = False
    max_positions: int = 20
    data_mode: str = "real_readonly"
    dry_run: bool = False
    update_positions: bool = True
    max_api_errors: int = 10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll read-only CLOB prices for shadow positions")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--interval_seconds", type=int, default=300)
    parser.add_argument("--duration_minutes", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max_positions", type=int, default=20)
    parser.add_argument("--data_mode", type=str, default="real_readonly", choices=["real_readonly"])
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--update_positions", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max_api_errors", type=int, default=10)
    return parser.parse_args(argv)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def verify_safety(
    risk_path: Path = REPO_ROOT / "config" / "risk.yaml",
    llm_path: Path = REPO_ROOT / "config" / "llm.yaml",
) -> dict[str, Any]:
    risk = load_yaml(risk_path)
    llm = load_yaml(llm_path)
    safety = {
        "live_trading_enabled": bool(risk.get("live_trading_enabled")),
        "allow_auto_execution": bool(risk.get("allow_auto_execution")),
        "paper_trading_enabled": bool(risk.get("paper_trading_enabled")),
        "default_llm_provider": llm.get("provider"),
        "read_only_clob_rest": True,
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "llm_calls": False,
        "run_paper_invoked": False,
        "private_key_handling": False,
    }
    if safety["live_trading_enabled"] or safety["allow_auto_execution"]:
        raise RuntimeError(
            "Refusing to run forward polling unless live trading and auto execution are disabled"
        )
    if not safety["paper_trading_enabled"]:
        raise RuntimeError("Refusing to run forward polling unless paper_trading_enabled=true")
    return safety


def build_config(args: argparse.Namespace) -> PollConfig:
    return PollConfig(
        shadow_dir=Path(args.shadow_dir),
        runs_dir=Path(args.runs_dir),
        interval_seconds=args.interval_seconds,
        duration_minutes=args.duration_minutes,
        once=args.once,
        max_positions=args.max_positions,
        data_mode=args.data_mode,
        dry_run=args.dry_run,
        update_positions=args.update_positions,
        max_api_errors=args.max_api_errors,
    )


def load_positions(shadow_dir: Path) -> list[ShadowTrade]:
    path = shadow_dir / "shadow_trades.csv"
    if not path.exists():
        path = shadow_dir / "updated_shadow_trades.csv"
    if not path.exists():
        path = shadow_dir / "shadow_trades_with_tokens.csv"
    trades = collector.load_shadow_trades(path)
    return [
        trade for trade in trades
        if trade.status in {
            ShadowTradeStatus.OPEN,
            ShadowTradeStatus.INSUFFICIENT_FORWARD_DATA,
        }
    ]


def best_bid(orderbook: Any) -> float | None:
    return _best_level(getattr(orderbook, "bids", []) or [], highest=True)[0]


def best_ask(orderbook: Any) -> float | None:
    return _best_level(getattr(orderbook, "asks", []) or [], highest=False)[0]


def best_bid_size(orderbook: Any) -> float | None:
    return _best_level(getattr(orderbook, "bids", []) or [], highest=True)[1]


def best_ask_size(orderbook: Any) -> float | None:
    return _best_level(getattr(orderbook, "asks", []) or [], highest=False)[1]


def total_liquidity(orderbook: Any) -> float:
    total = 0.0
    for level in (getattr(orderbook, "bids", []) or []) + (getattr(orderbook, "asks", []) or []):
        price = _optional_float(getattr(level, "price", None))
        size = _optional_float(getattr(level, "size", None))
        if price is not None and size is not None:
            total += price * size
    return total


def _best_level(levels: list[Any], highest: bool) -> tuple[float | None, float | None]:
    parsed_levels: list[tuple[float, float | None]] = []
    for level in levels:
        price = _optional_float(getattr(level, "price", None))
        size = _optional_float(getattr(level, "size", None))
        if price is not None and price > 0:
            parsed_levels.append((price, size if size is not None and size > 0 else None))
    if not parsed_levels:
        return None, None
    best_price = (
        max(price for price, _ in parsed_levels)
        if highest
        else min(price for price, _ in parsed_levels)
    )
    sizes = [size for price, size in parsed_levels if price == best_price and size is not None]
    return best_price, sum(sizes) if sizes else None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_forward_observation(
    trade: ShadowTrade,
    tokens: TokenIdResolution,
    yes_book: Any,
    no_book: Any,
    timestamp: str,
    source: str = "clob_rest_readonly",
) -> ForwardObservation:
    yes_bid = best_bid(yes_book) if yes_book is not None else None
    yes_ask = best_ask(yes_book) if yes_book is not None else None
    no_bid = best_bid(no_book) if no_book is not None else None
    no_ask = best_ask(no_book) if no_book is not None else None
    yes_bid_size = best_bid_size(yes_book) if yes_book is not None else None
    yes_ask_size = best_ask_size(yes_book) if yes_book is not None else None
    no_bid_size = best_bid_size(no_book) if no_book is not None else None
    no_ask_size = best_ask_size(no_book) if no_book is not None else None
    combined_ask = (yes_ask + no_ask) if yes_ask is not None and no_ask is not None else 0.0

    yes_spread = yes_ask - yes_bid if yes_bid is not None and yes_ask is not None else None
    no_spread = no_ask - no_bid if no_bid is not None and no_ask is not None else None
    # Spread is the widest available token spread, a conservative shadow-exit quality proxy.
    spread_values = [value for value in [yes_spread, no_spread] if value is not None]
    spread = max(spread_values) if spread_values else 0.0

    observed_price = no_bid if trade.side == ShadowSide.NO else yes_bid

    notes = ""
    stale = False
    error = ""
    if observed_price is None:
        observed_price = 0.0
        stale = True
        error = "liquidity_limitation_missing_exit_bid"
        notes = "liquidity_limitation"

    return ForwardObservation(
        shadow_trade_id=trade.shadow_trade_id,
        market_id=trade.market_id,
        yes_token_id=tokens.yes_token_id,
        no_token_id=tokens.no_token_id,
        timestamp=timestamp,
        observed_price=observed_price,
        yes_best_bid=yes_bid,
        yes_best_ask=yes_ask,
        no_best_bid=no_bid,
        no_best_ask=no_ask,
        yes_best_bid_size=yes_bid_size,
        yes_best_ask_size=yes_ask_size,
        no_best_bid_size=no_bid_size,
        no_best_ask_size=no_ask_size,
        yes_orderbook_timestamp=str(getattr(yes_book, "timestamp", "") or ""),
        no_orderbook_timestamp=str(getattr(no_book, "timestamp", "") or ""),
        yes_price=yes_bid or 0.0,
        no_price=no_bid or 0.0,
        combined_ask=combined_ask,
        spread=spread,
        liquidity=total_liquidity(yes_book) + total_liquidity(no_book),
        source=source,
        stale=stale,
        question=trade.question,
        side=trade.side.value,
        notes=notes,
        error=error,
    )


async def poll_once(
    positions: list[ShadowTrade],
    resolver: ShadowTokenIdResolver,
    clob_client: Any,
    max_api_errors: int,
) -> tuple[list[ForwardObservation], dict[str, Any]]:
    observations: list[ForwardObservation] = []
    errors: list[dict[str, str]] = []
    missing_token_id_count = 0
    api_error_count = 0
    stale_count = 0
    positions_polled = 0

    for trade in positions:
        tokens = resolver.resolve(trade.market_id)
        if not tokens.complete:
            missing_token_id_count += 1
            errors.append({
                "market_id": trade.market_id,
                "shadow_trade_id": trade.shadow_trade_id,
                "error": tokens.error or "missing_token_id",
            })
            continue
        try:
            yes_book, no_book = await clob_client.get_market_orderbook(
                tokens.yes_token_id,
                tokens.no_token_id,
            )
            positions_polled += 1
            observation = build_forward_observation(
                trade,
                tokens,
                yes_book,
                no_book,
                utc_now().isoformat(),
            )
            stale_count += 1 if observation.stale else 0
            if observation.error:
                errors.append({
                    "market_id": trade.market_id,
                    "shadow_trade_id": trade.shadow_trade_id,
                    "error": observation.error,
                })
                continue
            observations.append(observation)
        except Exception as exc:
            api_error_count += 1
            errors.append({
                "market_id": trade.market_id,
                "shadow_trade_id": trade.shadow_trade_id,
                "error": str(exc),
            })
            if api_error_count >= max_api_errors:
                break

    summary = {
        "positions_polled": positions_polled,
        "observations_written": len(observations),
        "missing_token_id_count": missing_token_id_count,
        "api_error_count": api_error_count,
        "stale_observation_count": stale_count,
        "errors": errors,
    }
    return observations, summary


def load_existing_observations(path: Path) -> list[ForwardObservation]:
    return collector.load_existing_forward_observations(path)


def write_observations_jsonl(path: Path, observations: list[ForwardObservation]) -> None:
    collector.write_forward_observations_jsonl(
        path,
        collector.dedupe_forward_observations(observations),
    )


def write_poll_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def update_shadow_performance(config: PollConfig) -> dict[str, Any]:
    exit_config = ExitRuleConfig()
    trades, observations, summary = collector.collect_and_update(
        config.runs_dir,
        config.shadow_dir,
        exit_config,
    )
    paths = collector.write_updated_outputs(config.shadow_dir, trades, observations, summary)
    return {
        "updated": True,
        "paths": paths,
        "collection_summary": summary,
    }


async def run_poll(
    config: PollConfig,
    clob_client: Any | None = None,
) -> dict[str, Any]:
    started_at = utc_now()
    safety = verify_safety()
    positions = load_positions(config.shadow_dir)[: config.max_positions]
    resolver = ShadowTokenIdResolver(config.runs_dir, config.shadow_dir)

    summary: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "ended_at": None,
        "duration_seconds": 0.0,
        "positions_loaded": len(positions),
        "positions_polled": 0,
        "observations_written": 0,
        "missing_token_id_count": 0,
        "api_error_count": 0,
        "stale_observation_count": 0,
        "updated_positions": False,
        "safety_verification": safety,
        "errors": [],
    }

    if config.dry_run:
        for trade in positions:
            if not resolver.resolve(trade.market_id).complete:
                summary["missing_token_id_count"] += 1
        summary["ended_at"] = utc_now().isoformat()
        summary["duration_seconds"] = (
            datetime.fromisoformat(summary["ended_at"]) - started_at
        ).total_seconds()
        return summary

    owns_client = clob_client is None
    client = clob_client or CLOBReadOnlyClient(max_retries=1)
    all_observations = load_existing_observations(config.shadow_dir / "forward_observations.jsonl")

    try:
        loop_deadline = started_at.timestamp() + (config.duration_minutes * 60)
        while True:
            observations, step_summary = await poll_once(
                positions,
                resolver,
                client,
                config.max_api_errors,
            )
            all_observations.extend(observations)
            for key in [
                "positions_polled",
                "observations_written",
                "missing_token_id_count",
                "api_error_count",
                "stale_observation_count",
            ]:
                summary[key] += step_summary[key]
            summary["errors"].extend(step_summary["errors"])

            if config.once or utc_now().timestamp() >= loop_deadline:
                break
            if summary["api_error_count"] >= config.max_api_errors:
                break
            await asyncio.sleep(config.interval_seconds)
    finally:
        if owns_client:
            await client.close()

    write_observations_jsonl(config.shadow_dir / "forward_observations.jsonl", all_observations)
    if config.update_positions:
        update_summary = update_shadow_performance(config)
        summary["updated_positions"] = bool(update_summary.get("updated"))
        summary["updated_outputs"] = update_summary

    ended_at = utc_now()
    summary["ended_at"] = ended_at.isoformat()
    summary["duration_seconds"] = (ended_at - started_at).total_seconds()
    write_poll_summary(config.shadow_dir / "forward_poll_summary.json", summary)
    return summary


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: poll shadow forward prices" if dry_run else "Poll shadow forward prices")
    print(f"positions_loaded: {summary['positions_loaded']}")
    print(f"positions_polled: {summary['positions_polled']}")
    print(f"observations_written: {summary['observations_written']}")
    print(f"missing_token_id_count: {summary['missing_token_id_count']}")
    print(f"api_error_count: {summary['api_error_count']}")
    print(f"stale_observation_count: {summary['stale_observation_count']}")
    print(f"updated_positions: {summary['updated_positions']}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_config(args)
    summary = asyncio.run(run_poll(config))
    print_summary(summary, config.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
