#!/usr/bin/env python3
"""Trading MVP Step 9A — read-only cross-market consistency edge discovery.

This script only uses public Gamma/CLOB read-only data. It does not
authenticate, sign, place orders, cancel orders, call LLMs, or run run_paper.py.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from polysignal.ingestion.api_errors import CLOBError
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.utils.time import utc_now
from scripts.discover_executable_edges import (
    GammaActiveMarketClient,
    TokenPair,
    extract_token_pair,
    filter_markets,
    load_avoid_ids,
    market_id,
    market_safety_reject_reason,
    market_volume,
    question,
    verify_safety,
)
from scripts.run_shadow_paper_loop import safe_float

RELATIONSHIP_DUPLICATE = "same_event_duplicate"
RELATIONSHIP_NEAR_DUPLICATE = "near_duplicate"
RELATIONSHIP_MUTUALLY_EXCLUSIVE = "mutually_exclusive_group"
EDGE_TYPE = "cross_market_consistency_v1"
STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "by",
    "for",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "will",
    "win",
    "wins",
}


@dataclass
class PricedMarket:
    market: dict[str, Any]
    pair: TokenPair
    yes: dict[str, float]
    no: dict[str, float]

    @property
    def market_id(self) -> str:
        return market_id(self.market)

    @property
    def question(self) -> str:
        return question(self.market)

    @property
    def yes_mid(self) -> float:
        return mid_price(self.yes)

    @property
    def no_mid(self) -> float:
        return mid_price(self.no)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover read-only cross-market consistency edges")
    parser.add_argument("--max_markets", type=int, default=1000)
    parser.add_argument("--min_volume", type=float, default=1000.0)
    parser.add_argument("--min_price_gap", type=float, default=0.05)
    parser.add_argument("--max_group_size", type=int, default=20)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--data_mode", type=str, default="real_readonly")
    return parser.parse_args(argv)


def normalize_question_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def question_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_question_text(value).split()
        if len(token) > 2 and token not in STOPWORDS
    }


def group_key(market: dict[str, Any]) -> str:
    slug = str(market.get("slug") or "").strip().lower()
    if slug:
        cleaned = re.sub(r"[^a-z0-9]+", " ", slug)
        tokens = [token for token in cleaned.split() if token not in STOPWORDS]
        return " ".join(tokens[:8])
    tokens = sorted(question_tokens(question(market)))
    return " ".join(tokens[:8])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_related_groups(markets: list[dict[str, Any]], max_group_size: int) -> list[dict[str, Any]]:
    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in markets:
        key = group_key(market)
        if key:
            exact_groups[key].append(market)

    groups: list[dict[str, Any]] = []
    seen_group_members: set[str] = set()
    for key, members in exact_groups.items():
        if 1 < len(members) <= max_group_size:
            groups.append({
                "group_id": f"dup_{abs(hash(key))}",
                "relationship_type": RELATIONSHIP_DUPLICATE,
                "markets": members,
                "confidence": 0.9,
            })
            seen_group_members.update(market_id(member) for member in members)

    candidates = [market for market in markets if market_id(market) not in seen_group_members]
    for idx, market in enumerate(candidates):
        tokens = question_tokens(question(market))
        members = [market]
        for other in candidates[idx + 1:]:
            score = jaccard(tokens, question_tokens(question(other)))
            if score >= 0.82:
                members.append(other)
        if 1 < len(members) <= max_group_size:
            ids = {market_id(member) for member in members}
            if ids & seen_group_members:
                continue
            groups.append({
                "group_id": f"near_{market_id(market)}",
                "relationship_type": RELATIONSHIP_NEAR_DUPLICATE,
                "markets": members,
                "confidence": 0.75,
            })
            seen_group_members.update(ids)

    exclusive: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in markets:
        text = normalize_question_text(question(market))
        for pattern in [
            r"(.+?) win the ([a-z0-9 ]+ election)",
            r"(.+?) win the ([a-z0-9 ]+ championship)",
            r"(.+?) win the ([a-z0-9 ]+ nomination)",
        ]:
            match = re.search(pattern, text)
            if match:
                exclusive[match.group(2).strip()].append(market)
                break
    for key, members in exclusive.items():
        if 1 < len(members) <= max_group_size:
            groups.append({
                "group_id": f"mutex_{abs(hash(key))}",
                "relationship_type": RELATIONSHIP_MUTUALLY_EXCLUSIVE,
                "markets": members,
                "confidence": 0.55,
            })
    return groups


def price_levels(orderbook: CLOBOrderbook | None) -> dict[str, float]:
    if orderbook is None:
        return {
            "best_bid": 0.0,
            "best_ask": 0.0,
            "spread": 0.0,
            "liquidity": 0.0,
            "depth": 0.0,
        }
    bids = [(safe_float(level.price), safe_float(level.size)) for level in orderbook.bids if safe_float(level.price) > 0]
    asks = [(safe_float(level.price), safe_float(level.size)) for level in orderbook.asks if safe_float(level.price) > 0]
    best_bid, _ = max(bids, key=lambda item: item[0]) if bids else (0.0, 0.0)
    best_ask, _ = min(asks, key=lambda item: item[0]) if asks else (0.0, 0.0)
    spread = max(0.0, best_ask - best_bid) if best_bid and best_ask else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "liquidity": sum(size for _, size in bids + asks),
        "depth": float(len(bids) + len(asks)),
    }


def mid_price(features: dict[str, float]) -> float:
    bid = features.get("best_bid", 0.0)
    ask = features.get("best_ask", 0.0)
    if bid and ask:
        return (bid + ask) / 2.0
    return ask or bid or 0.0


def action_for_duplicate(
    price_gap: float,
    entry_price: float,
    spread: float,
    depth: float,
    liquidity: float,
    relationship_confidence: float,
    min_price_gap: float,
) -> str:
    if price_gap < min_price_gap:
        return "watch_only"
    if not entry_price or spread > 0.05 or depth < 2 or liquidity < 1 or relationship_confidence < 0.8:
        return "watch_only"
    if price_gap >= max(min_price_gap * 2.0, 0.10):
        return "shadow_entry"
    return "watch_only"


def build_candidate_rows(
    group: dict[str, Any],
    priced: list[PricedMarket],
    min_price_gap: float,
    timestamp: str,
) -> list[dict[str, Any]]:
    relationship = group["relationship_type"]
    confidence = float(group.get("confidence", 0.0))
    rows: list[dict[str, Any]] = []
    priced = [item for item in priced if item.yes_mid > 0]
    if len(priced) < 2:
        return rows
    reference = max(priced, key=lambda item: item.yes_mid)
    for item in priced:
        if item.market_id == reference.market_id:
            continue
        price_gap = max(0.0, reference.yes_mid - item.yes_mid)
        if price_gap < min_price_gap:
            continue
        spread = item.yes["spread"]
        depth = item.yes["depth"]
        liquidity = item.yes["liquidity"]
        expected_edge = max(0.0, price_gap - spread)
        if relationship == RELATIONSHIP_MUTUALLY_EXCLUSIVE:
            action = "watch_only"
        else:
            action = action_for_duplicate(
                price_gap,
                item.yes["best_ask"],
                spread,
                depth,
                liquidity,
                confidence,
                min_price_gap,
            )
        evidence = [
            EDGE_TYPE,
            relationship,
            "cross_market_price_gap",
            f"reference_market_id={reference.market_id}",
        ]
        rows.append({
            "edge_type": EDGE_TYPE,
            "group_id": group["group_id"],
            "relationship_type": relationship,
            "market_id": item.market_id,
            "question": item.question,
            "side": "YES",
            "yes_token_id": item.pair.yes_token_id,
            "no_token_id": item.pair.no_token_id,
            "entry_price": item.yes["best_ask"],
            "reference_market_id": reference.market_id,
            "reference_question": reference.question,
            "reference_price": reference.yes_mid,
            "price_gap": price_gap,
            "expected_edge": expected_edge,
            "confidence": confidence,
            "evidence": "|".join(evidence),
            "recommended_action": action,
            "yes_best_bid": item.yes["best_bid"],
            "yes_best_ask": item.yes["best_ask"],
            "no_best_bid": item.no["best_bid"],
            "no_best_ask": item.no["best_ask"],
            "spread": spread,
            "liquidity_score": liquidity,
            "orderbook_depth": depth,
            "entry_yes_best_ask": item.yes["best_ask"],
            "entry_no_best_ask": item.no["best_ask"],
            "entry_yes_best_bid": item.yes["best_bid"],
            "entry_no_best_bid": item.no["best_bid"],
            "combined_ask": item.yes["best_ask"] + item.no["best_ask"] if item.yes["best_ask"] and item.no["best_ask"] else 0.0,
            "source": "cross_market_discovery",
            "category": str(item.market.get("category") or ""),
            "volume": market_volume(item.market),
            "timestamp": timestamp,
            "expected_edge_source": EDGE_TYPE,
            "expected_edge_status": "edge_positive" if expected_edge > 0 else "edge_too_low",
            "edge_pass": action == "shadow_entry",
            "edge_failure_reason": "" if action == "shadow_entry" else "cross_market_watch_only",
            "reasons": "|".join(evidence),
            "near_miss_tier": "tier1_mispricing" if action == "shadow_entry" else "",
            "evidence_level": "cross_market_consistency",
            "entry_decision_hint": "eligible_shadow_entry" if action == "shadow_entry" else "watch_only",
            "tradable_score": 0.0,
            "feedback_gate_status": "enabled",
            "feedback_gate_reason": "non_probability_edge",
            "gate_passed": True,
        })
    return rows


async def discover_cross_market_edges(
    args: argparse.Namespace,
    gamma_client: Any | None = None,
    clob_client: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = utc_now()
    timestamp = started.isoformat()
    gamma = gamma_client or GammaActiveMarketClient()
    clob = clob_client or CLOBReadOnlyClient(max_retries=1)
    close_clob = clob_client is None
    api_error_count = 0
    errors: list[dict[str, str]] = []
    raw_markets: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []

    try:
        try:
            raw_markets = await gamma.fetch_active_markets(args.max_markets)
        except Exception as exc:
            api_error_count += 1
            errors.append({"stage": "gamma_markets", "error": str(exc)})
            raw_markets = []
        markets = filter_markets(raw_markets, args.min_volume, args.max_markets)
        avoid_ids = load_avoid_ids(Path(args.output_dir))
        markets = [market for market in markets if not market_safety_reject_reason(market, avoid_ids)]
        groups = detect_related_groups(markets, args.max_group_size)
        sum(1 for group in groups if group["relationship_type"] in {RELATIONSHIP_DUPLICATE, RELATIONSHIP_NEAR_DUPLICATE})
        sum(1 for group in groups if group["relationship_type"] == RELATIONSHIP_MUTUALLY_EXCLUSIVE)
        if args.dry_run:
            return [], summarize(started, markets, groups, [], 0, api_error_count, errors)

        priced_cache: dict[str, PricedMarket] = {}
        orderbooks_fetched = 0
        for group in groups:
            group_priced: list[PricedMarket] = []
            for market in group["markets"]:
                mid = market_id(market)
                if mid in priced_cache:
                    group_priced.append(priced_cache[mid])
                    continue
                pair, token_error = extract_token_pair(market)
                if not pair:
                    errors.append({"market_id": mid, "error": token_error})
                    continue
                try:
                    yes_book, no_book = await clob.get_market_orderbook(pair.yes_token_id, pair.no_token_id)
                except CLOBError as exc:
                    api_error_count += 1
                    errors.append({"market_id": mid, "error": str(exc)})
                    if api_error_count >= args.max_api_errors:
                        break
                    continue
                orderbooks_fetched += int(yes_book is not None) + int(no_book is not None)
                priced_market = PricedMarket(market, pair, price_levels(yes_book), price_levels(no_book))
                priced_cache[mid] = priced_market
                group_priced.append(priced_market)
            rows.extend(build_candidate_rows(group, group_priced, args.min_price_gap, timestamp))
    finally:
        if close_clob:
            await clob.close()

    return rows, summarize(started, filter_markets(raw_markets, args.min_volume, args.max_markets), groups, rows, orderbooks_fetched, api_error_count, errors)


def summarize(
    started: datetime,
    markets: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    orderbooks_fetched: int,
    api_error_count: int,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    ended = utc_now()
    gaps = [safe_float(row.get("price_gap")) for row in rows]
    duplicate_groups = sum(1 for group in groups if group["relationship_type"] in {RELATIONSHIP_DUPLICATE, RELATIONSHIP_NEAR_DUPLICATE})
    mutex_groups = sum(1 for group in groups if group["relationship_type"] == RELATIONSHIP_MUTUALLY_EXCLUSIVE)
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "markets_scanned": len(markets),
        "groups_detected": len(groups),
        "duplicate_groups_detected": duplicate_groups,
        "mutually_exclusive_groups_detected": mutex_groups,
        "orderbooks_fetched": orderbooks_fetched,
        "candidates_generated": len(rows),
        "watch_only_candidates": sum(1 for row in rows if row.get("recommended_action") == "watch_only"),
        "shadow_entry_candidates": sum(1 for row in rows if row.get("recommended_action") == "shadow_entry"),
        "avg_price_gap": mean(gaps) if gaps else 0.0,
        "max_price_gap": max(gaps) if gaps else 0.0,
        "api_error_count": api_error_count,
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": "NO",
        "errors": errors[:100],
    }


FIELDS = [
    "edge_type",
    "group_id",
    "relationship_type",
    "market_id",
    "question",
    "side",
    "yes_token_id",
    "no_token_id",
    "entry_price",
    "reference_market_id",
    "reference_question",
    "reference_price",
    "price_gap",
    "expected_edge",
    "confidence",
    "evidence",
    "recommended_action",
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "spread",
    "liquidity_score",
    "orderbook_depth",
    "entry_yes_best_ask",
    "entry_no_best_ask",
    "entry_yes_best_bid",
    "entry_no_best_bid",
    "combined_ask",
    "source",
    "category",
    "volume",
    "timestamp",
    "expected_edge_source",
    "expected_edge_status",
    "edge_pass",
    "edge_failure_reason",
    "reasons",
    "near_miss_tier",
    "evidence_level",
    "entry_decision_hint",
    "tradable_score",
    "feedback_gate_status",
    "feedback_gate_reason",
    "gate_passed",
]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cross_market_edge_candidates": rows}, indent=2, sort_keys=True))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cross-Market Edge Discovery Report",
        "",
        f"Generated at: `{summary.get('ended_at')}`",
        "",
        "This is read-only, shadow-only discovery. Cross-market candidates are not live trading signals.",
        "Probability edge v1/v2 remains quarantined by feedback gates.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "markets_scanned",
        "groups_detected",
        "duplicate_groups_detected",
        "mutually_exclusive_groups_detected",
        "orderbooks_fetched",
        "candidates_generated",
        "watch_only_candidates",
        "shadow_entry_candidates",
        "avg_price_gap",
        "max_price_gap",
        "api_error_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        "Tiny live recommendation: **NO**",
        "",
        "## Safety Verification",
        "",
        "```json",
        json.dumps(summary.get("safety_verification", {}), indent=2, sort_keys=True),
        "```",
        "",
    ])
    path.write_text("\n".join(lines))


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: cross-market edge discovery" if dry_run else "Cross-market edge discovery")
    for key in [
        "markets_scanned",
        "groups_detected",
        "duplicate_groups_detected",
        "mutually_exclusive_groups_detected",
        "orderbooks_fetched",
        "candidates_generated",
        "watch_only_candidates",
        "shadow_entry_candidates",
        "avg_price_gap",
        "max_price_gap",
        "api_error_count",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


async def run_async(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.data_mode != "real_readonly":
        raise ValueError("discover_cross_market_edges only supports data_mode=real_readonly")
    return await discover_cross_market_edges(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, summary = asyncio.run(run_async(args))
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    csv_path = output_dir / "cross_market_edge_candidates.csv"
    json_path = output_dir / "cross_market_edge_candidates.json"
    summary_path = output_dir / "cross_market_edge_discovery_summary.json"
    report_path = output_dir / "cross_market_edge_discovery_report.md"
    write_csv(csv_path, rows)
    write_json(json_path, rows)
    write_summary(summary_path, summary)
    write_report(report_path, summary)
    print(f"cross_market_edge_candidates_csv: {csv_path}")
    print(f"cross_market_edge_candidates_json: {json_path}")
    print(f"cross_market_edge_discovery_summary_json: {summary_path}")
    print(f"cross_market_edge_discovery_report_md: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
