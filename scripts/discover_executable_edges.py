#!/usr/bin/env python3
"""
Trading MVP Step 3 — Discover executable microstructure edges.

This script scans public Gamma active markets and public read-only CLOB
orderbooks for YES/NO combined ask dislocations. It does not authenticate,
sign, place orders, cancel orders, call LLMs, run run_paper.py, or enter any
execution pathway.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from polysignal.ingestion.api_errors import CLOBError
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from scripts.backfill_shadow_token_ids import coerce_list, token_pair_from_outcomes, valid_token_id
from scripts.run_shadow_paper_loop import safe_float

REPO_ROOT = Path(__file__).resolve().parent.parent

EDGE_CANDIDATE_FIELDS = [
    "market_id",
    "question",
    "yes_token_id",
    "no_token_id",
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "yes_spread",
    "no_spread",
    "max_spread",
    "spread",
    "combined_ask",
    "combined_ask_gap",
    "executable_edge",
    "expected_edge",
    "expected_edge_source",
    "expected_edge_status",
    "edge_pass",
    "edge_failure_reason",
    "volume",
    "liquidity",
    "liquidity_score",
    "depth",
    "orderbook_depth",
    "category",
    "source",
    "timestamp",
    "near_miss_tier",
    "evidence_level",
    "reasons",
    "entry_decision_hint",
    "tradable_score",
    "edge_status",
    "reject_reason",
]


@dataclass
class TokenPair:
    yes_token_id: str
    no_token_id: str


class GammaActiveMarketClient:
    """Public read-only Gamma active market fetcher with no authentication."""

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, base_url: str = BASE_URL, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_active_markets(self, limit: int) -> list[dict[str, Any]]:
        params = {"active": "true", "closed": "false", "limit": limit}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.get("/markets", params=params)
            response.raise_for_status()
            payload = response.json()
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover read-only executable YES/NO edge candidates")
    parser.add_argument("--max_markets", type=int, default=500)
    parser.add_argument("--min_volume", type=float, default=1000.0)
    parser.add_argument("--max_api_errors", type=int, default=20)
    parser.add_argument("--spread_buffer", type=float, default=0.01)
    parser.add_argument("--min_executable_edge", type=float, default=0.001)
    parser.add_argument("--min_depth", type=float, default=1.0)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--data_mode", type=str, default="real_readonly")
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
    return {
        "live_trading_enabled": bool(risk.get("live_trading_enabled")),
        "allow_auto_execution": bool(risk.get("allow_auto_execution")),
        "paper_trading_enabled": bool(risk.get("paper_trading_enabled")),
        "default_llm_provider": llm.get("provider"),
        "public_gamma_read_only": True,
        "public_clob_read_only": True,
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "llm_calls": False,
        "run_paper_invoked": False,
        "private_key_handling": False,
        "risk_governor_modified": False,
    }


def market_id(market: dict[str, Any]) -> str:
    return str(market.get("id") or market.get("market_id") or market.get("condition_id") or "")


def question(market: dict[str, Any]) -> str:
    return str(market.get("question") or market.get("title") or "")


def market_volume(market: dict[str, Any]) -> float:
    for field in ("volume", "volumeNum", "volume_24h", "liquidity", "liquidityNum"):
        value = safe_float(market.get(field), -1.0)
        if value >= 0:
            return value
    return 0.0


def is_active_open_market(market: dict[str, Any]) -> bool:
    return bool(market.get("active", True)) and not bool(market.get("closed")) and not bool(market.get("resolved"))


def load_avoid_ids(output_dir: Path) -> set[str]:
    path = output_dir / "avoid_candidates.csv"
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {str(row.get("market_id") or "") for row in csv.DictReader(f) if row.get("market_id")}


def normalize_category(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def forbidden_categories() -> set[str]:
    risk = load_yaml(REPO_ROOT / "config" / "risk.yaml")
    return {normalize_category(item) for item in risk.get("forbidden_auto_categories", [])}


def ambiguity_keywords() -> set[str]:
    risk = load_yaml(REPO_ROOT / "config" / "risk.yaml")
    lifecycle = risk.get("lifecycle", {}) if isinstance(risk.get("lifecycle"), dict) else {}
    return {str(item).strip().lower() for item in lifecycle.get("ambiguity_keywords", [])}


def market_safety_reject_reason(market: dict[str, Any], avoid_ids: set[str]) -> str:
    if market_id(market) in avoid_ids:
        return "avoid_candidate"
    category = normalize_category(market.get("category"))
    if category and category in forbidden_categories():
        return "forbidden_category"
    text = f"{question(market)} {market.get('description') or ''}".lower()
    if any(keyword and keyword in text for keyword in ambiguity_keywords()):
        return "ambiguous_market"
    return ""


def extract_token_pair(market: dict[str, Any]) -> tuple[TokenPair | None, str]:
    mid = market_id(market)
    token_ids = coerce_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    outcomes = coerce_list(market.get("outcomes"))
    if len(token_ids) == 2 and len(outcomes) == 2:
        normalized = {str(outcome).strip().lower() for outcome in outcomes}
        if normalized == {"yes", "no"}:
            yes, no = token_pair_from_outcomes(token_ids, outcomes)
            if valid_token_id(yes, mid) and valid_token_id(no, mid):
                return TokenPair(yes, no), ""
        return None, "ambiguous_outcome_mapping"

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        yes = ""
        no = ""
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome") or "").strip().lower()
            token_id = str(token.get("token_id") or token.get("tokenId") or token.get("asset_id") or "")
            if outcome == "yes":
                yes = token_id
            elif outcome == "no":
                no = token_id
        if valid_token_id(yes, mid) and valid_token_id(no, mid):
            return TokenPair(yes, no), ""
        if yes or no:
            return None, "ambiguous_outcome_mapping"

    if token_ids:
        return None, "unsupported_market_structure"
    return None, "missing_token_id"


def price_levels(orderbook: CLOBOrderbook | None) -> dict[str, float]:
    if orderbook is None:
        return {"best_bid": 0.0, "best_ask": 0.0, "spread": 0.0, "liquidity": 0.0, "depth": 0.0}
    bids = [safe_float(level.price) for level in orderbook.bids if safe_float(level.price) > 0]
    asks = [safe_float(level.price) for level in orderbook.asks if safe_float(level.price) > 0]
    best_bid = max(bids) if bids else 0.0
    best_ask = min(asks) if asks else 0.0
    spread = max(0.0, best_ask - best_bid) if best_bid and best_ask else 0.0
    liquidity = sum(safe_float(level.size) for level in orderbook.bids + orderbook.asks)
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "liquidity": liquidity,
        "depth": float(len(orderbook.bids) + len(orderbook.asks)),
    }


def build_edge_candidate(
    market: dict[str, Any],
    pair: TokenPair,
    yes_book: CLOBOrderbook | None,
    no_book: CLOBOrderbook | None,
    spread_buffer: float,
    min_executable_edge: float,
    min_depth: float,
    timestamp: str,
) -> dict[str, Any]:
    yes = price_levels(yes_book)
    no = price_levels(no_book)
    combined_ask = yes["best_ask"] + no["best_ask"] if yes["best_ask"] and no["best_ask"] else 0.0
    max_spread = max(yes["spread"], no["spread"])
    combined_ask_gap = max(0.0, 1.0 - combined_ask) if combined_ask else 0.0
    executable_edge = combined_ask_gap - max_spread - spread_buffer
    depth = yes["depth"] + no["depth"]
    liquidity = yes["liquidity"] + no["liquidity"]
    reject_reason = ""
    edge_status = "edge_candidate"
    edge_pass = True
    if not yes["best_ask"] or not no["best_ask"]:
        edge_status = "missing_side_ask"
        reject_reason = "missing_side_ask"
        edge_pass = False
    elif combined_ask >= 1.0:
        edge_status = "combined_ask_not_below_one"
        reject_reason = "combined_ask_not_below_one"
        edge_pass = False
    elif executable_edge <= min_executable_edge:
        edge_status = "spread_too_wide"
        reject_reason = "spread_too_wide"
        edge_pass = False
    elif depth < min_depth:
        edge_status = "insufficient_depth"
        reject_reason = "insufficient_depth"
        edge_pass = False

    return {
        "market_id": market_id(market),
        "question": question(market),
        "yes_token_id": pair.yes_token_id,
        "no_token_id": pair.no_token_id,
        "yes_best_bid": yes["best_bid"],
        "yes_best_ask": yes["best_ask"],
        "no_best_bid": no["best_bid"],
        "no_best_ask": no["best_ask"],
        "yes_spread": yes["spread"],
        "no_spread": no["spread"],
        "max_spread": max_spread,
        "spread": max_spread,
        "combined_ask": combined_ask,
        "combined_ask_gap": combined_ask_gap,
        "executable_edge": executable_edge,
        "expected_edge": executable_edge,
        "expected_edge_source": "orderbook_combined_ask_gap_v1",
        "expected_edge_status": "edge_positive" if edge_pass else edge_status,
        "edge_pass": edge_pass,
        "edge_failure_reason": "" if edge_pass else reject_reason,
        "volume": market_volume(market),
        "liquidity": liquidity,
        "liquidity_score": liquidity,
        "depth": depth,
        "orderbook_depth": depth,
        "category": str(market.get("category") or ""),
        "source": "executable_edge_discovery",
        "timestamp": timestamp,
        "near_miss_tier": "tier1_mispricing" if edge_pass else "",
        "evidence_level": "microstructure_edge" if edge_pass else "",
        "reasons": "microstructure_edge|executable_edge_discovery" if edge_pass else "",
        "entry_decision_hint": "eligible_shadow_entry" if edge_pass else "watch_only",
        "tradable_score": 0.0,
        "edge_status": edge_status,
        "reject_reason": reject_reason,
    }


def filter_markets(markets: list[dict[str, Any]], min_volume: float, max_markets: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for market in markets:
        if not is_active_open_market(market):
            continue
        if market_volume(market) < min_volume:
            continue
        selected.append(market)
        if len(selected) >= max_markets:
            break
    return selected


async def discover_edges(
    args: argparse.Namespace,
    gamma_client: Any | None = None,
    clob_client: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = datetime.utcnow()
    timestamp = started.isoformat()
    errors: list[dict[str, str]] = []
    api_error_count = 0
    stale_orderbook_count = 0
    gamma = gamma_client or GammaActiveMarketClient()
    clob = clob_client or CLOBReadOnlyClient(max_retries=1)
    close_clob = clob_client is None
    raw_markets: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    evaluated_rows: list[dict[str, Any]] = []
    markets_with_token_ids = 0
    orderbooks_fetched = 0
    insufficient_depth_count = 0
    spread_too_wide_count = 0
    avoid_ids = load_avoid_ids(Path(args.output_dir))
    avoid_candidate_count = 0
    forbidden_category_count = 0
    ambiguous_market_count = 0

    try:
        try:
            raw_markets = await gamma.fetch_active_markets(args.max_markets)
        except Exception as exc:
            api_error_count += 1
            errors.append({"stage": "gamma_markets", "error": str(exc)})
            raw_markets = []

        markets = filter_markets(raw_markets, args.min_volume, args.max_markets)
        if args.dry_run:
            summary = build_summary(
                started,
                markets,
                markets_with_token_ids=0,
                orderbooks_fetched=0,
                candidates=[],
                api_error_count=api_error_count,
                stale_orderbook_count=0,
                insufficient_depth_count=0,
                spread_too_wide_count=0,
                errors=errors,
            )
            summary["active_markets_available"] = len(markets)
            return [], summary

        for market in markets:
            safety_reject = market_safety_reject_reason(market, avoid_ids)
            if safety_reject:
                if safety_reject == "avoid_candidate":
                    avoid_candidate_count += 1
                elif safety_reject == "forbidden_category":
                    forbidden_category_count += 1
                elif safety_reject == "ambiguous_market":
                    ambiguous_market_count += 1
                continue
            pair, token_error = extract_token_pair(market)
            if not pair:
                errors.append({"market_id": market_id(market), "error": token_error})
                continue
            markets_with_token_ids += 1
            try:
                yes_book, no_book = await clob.get_market_orderbook(pair.yes_token_id, pair.no_token_id)
            except CLOBError as exc:
                api_error_count += 1
                errors.append({"market_id": market_id(market), "error": str(exc)})
                if api_error_count >= args.max_api_errors:
                    break
                continue
            orderbooks_fetched += int(yes_book is not None) + int(no_book is not None)
            row = build_edge_candidate(
                market,
                pair,
                yes_book,
                no_book,
                args.spread_buffer,
                args.min_executable_edge,
                args.min_depth,
                timestamp,
            )
            if row["reject_reason"] == "insufficient_depth":
                insufficient_depth_count += 1
            if row["reject_reason"] == "spread_too_wide":
                spread_too_wide_count += 1
            evaluated_rows.append(row)
            if row["edge_pass"]:
                candidates.append(row)
    finally:
        if close_clob:
            await clob.close()

    summary = build_summary(
        started,
        filter_markets(raw_markets, args.min_volume, args.max_markets),
        markets_with_token_ids=markets_with_token_ids,
        orderbooks_fetched=orderbooks_fetched,
        candidates=candidates,
        evaluated_rows=evaluated_rows,
        api_error_count=api_error_count,
        stale_orderbook_count=stale_orderbook_count,
        insufficient_depth_count=insufficient_depth_count,
        spread_too_wide_count=spread_too_wide_count,
        errors=errors,
    )
    summary["avoid_candidate_count"] = avoid_candidate_count
    summary["forbidden_category_count"] = forbidden_category_count
    summary["ambiguous_market_count"] = ambiguous_market_count
    return candidates, summary


def build_summary(
    started: datetime,
    markets: list[dict[str, Any]],
    markets_with_token_ids: int,
    orderbooks_fetched: int,
    candidates: list[dict[str, Any]],
    api_error_count: int,
    stale_orderbook_count: int,
    insufficient_depth_count: int,
    spread_too_wide_count: int,
    errors: list[dict[str, str]],
    evaluated_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ended = datetime.utcnow()
    rows_for_counts = evaluated_rows if evaluated_rows is not None else candidates
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "markets_scanned": len(markets),
        "markets_with_token_ids": markets_with_token_ids,
        "orderbooks_fetched": orderbooks_fetched,
        "combined_ask_below_one_count": sum(1 for row in rows_for_counts if 0 < safe_float(row.get("combined_ask")) < 1.0),
        "executable_edge_positive_count": sum(1 for row in rows_for_counts if safe_float(row.get("executable_edge")) > 0),
        "edge_candidates_count": len(candidates),
        "api_error_count": api_error_count,
        "stale_orderbook_count": stale_orderbook_count,
        "insufficient_depth_count": insufficient_depth_count,
        "spread_too_wide_count": spread_too_wide_count,
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": "NO",
        "errors": errors[:100],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(EDGE_CANDIDATE_FIELDS)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"executable_edge_candidates": rows}, indent=2, sort_keys=True))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Executable Edge Discovery Report",
        "",
        f"Generated at: `{summary['ended_at']}`",
        "",
        "This is read-only executable edge discovery for shadow candidates only.",
        "It does not authenticate, sign, place orders, cancel orders, call LLMs, or enable live trading.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "markets_scanned",
        "markets_with_token_ids",
        "orderbooks_fetched",
        "combined_ask_below_one_count",
        "executable_edge_positive_count",
        "edge_candidates_count",
        "api_error_count",
        "stale_orderbook_count",
        "insufficient_depth_count",
        "spread_too_wide_count",
        "avoid_candidate_count",
        "forbidden_category_count",
        "ambiguous_market_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        f"Tiny live recommendation: **{summary.get('tiny_live_recommendation', 'NO')}**",
        "",
        "## Safety Verification",
        "",
        "```json",
        json.dumps(summary["safety_verification"], indent=2, sort_keys=True),
        "```",
        "",
    ])
    path.write_text("\n".join(lines))


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: executable edge discovery" if dry_run else "Executable edge discovery")
    for key in [
        "markets_scanned",
        "active_markets_available",
        "markets_with_token_ids",
        "orderbooks_fetched",
        "combined_ask_below_one_count",
        "executable_edge_positive_count",
        "edge_candidates_count",
        "api_error_count",
        "stale_orderbook_count",
        "insufficient_depth_count",
        "spread_too_wide_count",
        "avoid_candidate_count",
        "forbidden_category_count",
        "ambiguous_market_count",
    ]:
        if key in summary:
            print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


async def run_async(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.data_mode != "real_readonly":
        raise ValueError("discover_executable_edges only supports data_mode=real_readonly")
    return await discover_edges(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates, summary = asyncio.run(run_async(args))
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "executable_edge_candidates.csv", candidates)
    write_json(output_dir / "executable_edge_candidates.json", candidates)
    write_summary(output_dir / "executable_edge_discovery_summary.json", summary)
    write_report(output_dir / "executable_edge_discovery_report.md", summary)
    print(f"executable_edge_candidates_csv: {output_dir / 'executable_edge_candidates.csv'}")
    print(f"executable_edge_candidates_json: {output_dir / 'executable_edge_candidates.json'}")
    print(f"executable_edge_discovery_summary_json: {output_dir / 'executable_edge_discovery_summary.json'}")
    print(f"executable_edge_discovery_report_md: {output_dir / 'executable_edge_discovery_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
