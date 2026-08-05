#!/usr/bin/env python3
"""
Phase 8J — Refresh tradable candidates with read-only CLOB side prices.

This script only reads public orderbooks and local run artifacts. It does not
authenticate, sign, place orders, cancel orders, call LLMs, or run run_paper.py.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from polysignal.ingestion.api_errors import CLOBError
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.shadow.entry_filter import EntryFilterConfig, ShadowEntryFilter
from polysignal.shadow.forward_observations import ShadowTokenIdResolver
from scripts.backfill_shadow_token_ids import (
    GammaTokenLookupClient,
    lookup_missing_token_pairs,
)
from scripts.run_shadow_paper_loop import candidate_from_tradable, safe_bool, safe_float


REPO_ROOT = Path(__file__).resolve().parent.parent

PRICE_FIELDS = [
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "yes_spread",
    "no_spread",
    "max_spread",
    "liquidity_proxy",
    "expected_edge",
    "executable_edge_proxy",
    "entry_yes_best_ask",
    "entry_no_best_ask",
    "entry_yes_best_bid",
    "entry_no_best_bid",
    "price_snapshot_source",
    "price_snapshot_timestamp",
    "price_refresh_status",
    "price_refresh_error",
]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh tradable candidates with side-specific CLOB prices")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--max_candidates", type=int, default=50)
    parser.add_argument("--max_api_errors", type=int, default=10)
    parser.add_argument("--data_mode", type=str, default="real_readonly")
    parser.add_argument("--allow_gamma_lookup", action="store_true", default=False)
    parser.add_argument("--max_gamma_api_calls", type=int, default=20)
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


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
        "read_only_clob_rest": True,
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "llm_calls": False,
        "run_paper_invoked": False,
        "private_key_handling": False,
    }


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def select_candidate_file(runs_dir: Path) -> Path:
    with_tokens = runs_dir / "tradable_candidates_with_tokens.csv"
    if with_tokens.exists():
        return with_tokens
    return runs_dir / "tradable_candidates.csv"


def valid_token_id(token_id: str, market_id: str) -> bool:
    token = str(token_id or "").strip()
    market = str(market_id or "").strip()
    return bool(token and token != market)


def resolve_token_ids(row: dict[str, str], resolver: ShadowTokenIdResolver) -> tuple[str, str, str]:
    market_id = str(row.get("market_id") or "")
    yes = str(row.get("yes_token_id") or "")
    no = str(row.get("no_token_id") or "")
    if valid_token_id(yes, market_id) and valid_token_id(no, market_id):
        return yes, no, "candidate_file"
    resolved = resolver.resolve(market_id)
    if resolved.complete:
        return resolved.yes_token_id, resolved.no_token_id, resolved.source
    return "", "", "missing_token_id"


def price_levels(orderbook: Optional[CLOBOrderbook]) -> dict[str, float]:
    if orderbook is None:
        return {
            "best_bid": 0.0,
            "best_ask": 0.0,
            "spread": 0.0,
            "liquidity": 0.0,
            "depth": 0.0,
        }
    bids = [safe_float(level.price) for level in orderbook.bids if safe_float(level.price) > 0]
    asks = [safe_float(level.price) for level in orderbook.asks if safe_float(level.price) > 0]
    liquidity = sum(safe_float(level.size) for level in orderbook.bids + orderbook.asks)
    best_bid = max(bids) if bids else 0.0
    best_ask = min(asks) if asks else 0.0
    spread = max(0.0, best_ask - best_bid) if best_bid and best_ask else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "liquidity": liquidity,
        "depth": float(len(orderbook.bids) + len(orderbook.asks)),
    }


def apply_price_snapshot(
    row: dict[str, str],
    yes_book: Optional[CLOBOrderbook],
    no_book: Optional[CLOBOrderbook],
    timestamp: str,
) -> dict[str, str]:
    payload = dict(row)
    yes = price_levels(yes_book)
    no = price_levels(no_book)
    combined_ask = yes["best_ask"] + no["best_ask"] if yes["best_ask"] and no["best_ask"] else 0.0
    max_spread = max(yes["spread"], no["spread"])
    combined_ask_gap = max(0.0, 1.0 - combined_ask) if combined_ask else 0.0
    executable_edge = max(0.0, combined_ask_gap - max_spread)
    liquidity_proxy = yes["liquidity"] + no["liquidity"]
    depth = yes["depth"] + no["depth"]

    payload.update({
        "yes_best_bid": yes["best_bid"],
        "yes_best_ask": yes["best_ask"],
        "no_best_bid": no["best_bid"],
        "no_best_ask": no["best_ask"],
        "yes_spread": yes["spread"],
        "no_spread": no["spread"],
        "max_spread": max_spread,
        "combined_ask": combined_ask,
        "spread": max_spread,
        "liquidity_proxy": liquidity_proxy,
        "liquidity_score": safe_float(payload.get("liquidity_score"), 0.0) or liquidity_proxy,
        "orderbook_depth": safe_float(payload.get("orderbook_depth"), 0.0) or depth,
        "expected_edge": executable_edge,
        "executable_edge_proxy": executable_edge,
        "entry_yes_best_ask": yes["best_ask"],
        "entry_no_best_ask": no["best_ask"],
        "entry_yes_best_bid": yes["best_bid"],
        "entry_no_best_bid": no["best_bid"],
        "price_snapshot_source": "clob_rest_readonly",
        "price_snapshot_timestamp": timestamp,
        "price_refresh_status": "priced" if yes["best_ask"] and no["best_ask"] else "empty_orderbook",
        "price_refresh_error": "",
    })
    return payload


async def refresh_prices(
    rows: list[dict[str, str]],
    runs_dir: Path,
    max_candidates: int,
    max_api_errors: int,
    clob_client: Optional[CLOBReadOnlyClient] = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    shadow_dir = runs_dir / "shadow"
    resolver = ShadowTokenIdResolver(runs_dir, shadow_dir)
    client = clob_client or CLOBReadOnlyClient(max_retries=1)
    created_client = clob_client is None
    priced_rows: list[dict[str, str]] = []
    api_errors = 0
    missing_token_id_count = 0
    empty_orderbook_count = 0
    timestamp = datetime.utcnow().isoformat()

    try:
        for row in rows[:max_candidates]:
            payload = dict(row)
            market_id = str(payload.get("market_id") or "")
            yes_token_id, no_token_id, token_source = resolve_token_ids(payload, resolver)
            payload["yes_token_id"] = yes_token_id
            payload["no_token_id"] = no_token_id
            payload["token_id_source"] = token_source
            if not yes_token_id or not no_token_id:
                missing_token_id_count += 1
                payload.update({
                    "price_refresh_status": "missing_token_id",
                    "price_refresh_error": "missing_token_id",
                })
                priced_rows.append(payload)
                continue
            try:
                yes_book, no_book = await client.get_market_orderbook(yes_token_id, no_token_id)
            except CLOBError as exc:
                api_errors += 1
                payload.update({
                    "price_refresh_status": "api_error",
                    "price_refresh_error": str(exc),
                })
                priced_rows.append(payload)
                if api_errors >= max_api_errors:
                    break
                continue
            priced = apply_price_snapshot(payload, yes_book, no_book, timestamp)
            if priced["price_refresh_status"] == "empty_orderbook":
                empty_orderbook_count += 1
            priced_rows.append(priced)
    finally:
        if created_client:
            await client.close()

    summary = summarize_refresh(priced_rows, len(rows), missing_token_id_count, empty_orderbook_count, api_errors)
    return priced_rows, summary


def summarize_refresh(
    rows: list[dict[str, str]],
    candidates_loaded: int,
    missing_token_id_count: int,
    empty_orderbook_count: int,
    api_error_count: int,
) -> dict[str, Any]:
    priced = [row for row in rows if row.get("price_refresh_status") == "priced"]
    yes_ask = [row for row in rows if safe_float(row.get("yes_best_ask")) > 0]
    no_ask = [row for row in rows if safe_float(row.get("no_best_ask")) > 0]
    expected_edge = [row for row in rows if safe_float(row.get("expected_edge")) > 0]
    entry_filter = ShadowEntryFilter(EntryFilterConfig())
    eligible = 0
    for row in rows:
        candidate = candidate_from_tradable(row, set())
        if entry_filter.evaluate(candidate).allowed:
            eligible += 1
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "candidates_loaded": candidates_loaded,
        "candidates_refreshed": len(rows),
        "candidates_priced": len(priced),
        "missing_token_id_count": missing_token_id_count,
        "empty_orderbook_count": empty_orderbook_count,
        "api_error_count": api_error_count,
        "yes_ask_available_count": len(yes_ask),
        "no_ask_available_count": len(no_ask),
        "side_ask_available_count": sum(1 for row in rows if safe_float(row.get("yes_best_ask")) > 0 and safe_float(row.get("no_best_ask")) > 0),
        "expected_edge_available_count": len(expected_edge),
        "eligible_after_refresh_count": eligible,
        "tiny_live_recommendation": "NO",
        "safety_verification": verify_safety(),
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    for key in PRICE_FIELDS:
        if key not in fieldnames:
            fieldnames.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tradable_candidates_priced": rows}, indent=2))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Tradable Candidate Price Refresh Report",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "combined_ask is a market-level feature only. It is not a side-specific entry price.",
        "YES entries use yes_best_ask; NO entries use no_best_ask.",
        "This is read-only candidate pricing, not trading.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "candidates_loaded",
        "candidates_priced",
        "missing_token_id_count",
        "empty_orderbook_count",
        "api_error_count",
        "yes_ask_available_count",
        "no_ask_available_count",
        "side_ask_available_count",
        "expected_edge_available_count",
        "eligible_after_refresh_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        f"Tiny live recommendation: **{summary.get('tiny_live_recommendation', 'NO')}**",
        "",
        "## Safety Verification",
        "",
        json.dumps(summary["safety_verification"], indent=2),
        "",
    ])
    path.write_text("\n".join(lines))


def load_candidates_with_optional_gamma(args: argparse.Namespace, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not args.allow_gamma_lookup:
        return rows
    client = GammaTokenLookupClient(max_api_calls=args.max_gamma_api_calls)
    token_index: dict[str, Any] = {}
    lookup_missing_token_pairs(token_index, [], rows, client, args.max_gamma_api_calls)
    updated = []
    for row in rows:
        payload = dict(row)
        pair = token_index.get(str(row.get("market_id") or ""))
        if pair:
            payload["yes_token_id"] = pair.yes_token_id
            payload["no_token_id"] = pair.no_token_id
        updated.append(payload)
    return updated


async def run_async(args: argparse.Namespace) -> tuple[list[dict[str, str]], dict[str, Any], Path]:
    runs_dir = Path(args.runs_dir)
    candidate_file = select_candidate_file(runs_dir)
    rows = load_candidates_with_optional_gamma(args, load_csv(candidate_file))
    if args.dry_run:
        rows = rows[:args.max_candidates]
        resolver = ShadowTokenIdResolver(runs_dir, runs_dir / "shadow")
        missing = 0
        prepared = []
        for row in rows:
            payload = dict(row)
            yes, no, source = resolve_token_ids(payload, resolver)
            payload["yes_token_id"] = yes
            payload["no_token_id"] = no
            payload["token_id_source"] = source
            if not yes or not no:
                missing += 1
                payload["price_refresh_status"] = "missing_token_id"
            else:
                payload["price_refresh_status"] = "would_poll"
            prepared.append(payload)
        summary = summarize_refresh(prepared, len(rows), missing, 0, 0)
        return rows, summary, candidate_file
    priced_rows, summary = await refresh_prices(
        rows,
        runs_dir,
        args.max_candidates,
        args.max_api_errors,
    )
    return priced_rows, summary, candidate_file


def print_summary(summary: dict[str, Any], candidate_file: Path, dry_run: bool) -> None:
    print("DRY RUN: tradable candidate price refresh" if dry_run else "Tradable candidate price refresh")
    print(f"candidate_file: {candidate_file}")
    for key in [
        "candidates_loaded",
        "candidates_priced",
        "missing_token_id_count",
        "empty_orderbook_count",
        "api_error_count",
        "yes_ask_available_count",
        "no_ask_available_count",
        "side_ask_available_count",
        "expected_edge_available_count",
        "eligible_after_refresh_count",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    rows, summary, candidate_file = asyncio.run(run_async(args))
    print_summary(summary, candidate_file, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "tradable_candidates_priced.csv", rows)
    write_json(output_dir / "tradable_candidates_priced.json", rows)
    write_summary(output_dir / "tradable_candidate_price_refresh_summary.json", summary)
    write_report(output_dir / "tradable_candidate_price_report.md", summary)
    print(f"tradable_candidates_priced_csv: {output_dir / 'tradable_candidates_priced.csv'}")
    print(f"tradable_candidates_priced_json: {output_dir / 'tradable_candidates_priced.json'}")
    print(f"tradable_candidate_price_refresh_summary_json: {output_dir / 'tradable_candidate_price_refresh_summary.json'}")
    print(f"tradable_candidate_price_report_md: {output_dir / 'tradable_candidate_price_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
