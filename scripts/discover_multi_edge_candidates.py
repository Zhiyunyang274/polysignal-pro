#!/usr/bin/env python3
"""
Trading MVP Step 4A — Multi-edge discovery framework v1.

This script scans public Gamma active markets and public read-only CLOB
orderbooks, then emits unified shadow-only edge candidates. It does not
authenticate, sign, place orders, cancel orders, call LLMs, run run_paper.py, or
enter any live execution pathway.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from polysignal.ingestion.api_errors import CLOBError
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.shadow.edge_candidates import (
    EDGE_CANDIDATE_FIELDS,
    EdgeAction,
    EdgeCandidate,
    EdgeType,
)
from polysignal.shadow.feedback_gate import (
    PROBABILITY_EDGE_TYPES,
    EdgeTypeGate,
    FeedbackGateConfig,
    evaluate_edge_type_gate,
)
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

FEEDBACK_SUMMARY_NAME = "edge_feedback_calibration_summary.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover read-only multi-edge candidates")
    parser.add_argument("--max_markets", type=int, default=500)
    parser.add_argument("--min_volume", type=float, default=1000.0)
    parser.add_argument("--spread_buffer", type=float, default=0.01)
    parser.add_argument("--min_expected_edge", type=float, default=0.001)
    parser.add_argument("--min_confidence", type=float, default=0.6)
    parser.add_argument("--min_depth", type=float, default=1.0)
    parser.add_argument("--max_api_errors", type=int, default=50)
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--edge_version", choices=["v1", "v2", "both"], default="both")
    parser.add_argument("--output_suffix", type=str, default="")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--data_mode", type=str, default="real_readonly")
    return parser.parse_args(argv)


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def load_feedback_summary(output_dir: Path) -> dict[str, Any]:
    path = output_dir / FEEDBACK_SUMMARY_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def build_feedback_gates(output_dir: Path) -> dict[str, EdgeTypeGate]:
    feedback_summary = load_feedback_summary(output_dir)
    return {
        edge_type: evaluate_edge_type_gate(edge_type, feedback_summary, FeedbackGateConfig())
        for edge_type in sorted(PROBABILITY_EDGE_TYPES)
    }


def _append_once(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def apply_feedback_gates(candidates: list[EdgeCandidate], gates: dict[str, EdgeTypeGate]) -> None:
    for candidate in candidates:
        gate = gates.get(candidate.edge_type.value)
        if not gate:
            candidate.feedback_gate_status = "enabled"
            candidate.feedback_gate_reason = "edge_type_not_probability_gated"
            candidate.gate_passed = True
            continue
        candidate.feedback_gate_status = gate.status
        candidate.feedback_gate_reason = gate.gate_reason
        candidate.gate_passed = gate.gate_passed
        if gate.gate_passed:
            _append_once(candidate.evidence, "feedback_gate_passed")
            continue
        candidate.recommended_action = EdgeAction.WATCH_ONLY
        _append_once(candidate.evidence, "feedback_gate_failed")
        if gate.status == "quarantined":
            _append_once(candidate.evidence, "edge_type_quarantined")
        if "expected_edge_negative_correlation" in gate.gate_reason:
            _append_once(candidate.evidence, "expected_edge_negative_correlation")
        if "confidence_not_predictive" in gate.gate_reason:
            _append_once(candidate.evidence, "confidence_not_predictive")


def book_features(orderbook: CLOBOrderbook | None) -> dict[str, float]:
    if orderbook is None:
        return {
            "best_bid": 0.0,
            "best_ask": 0.0,
            "best_bid_size": 0.0,
            "best_ask_size": 0.0,
            "spread": 0.0,
            "mid": 0.0,
            "liquidity": 0.0,
            "depth": 0.0,
            "imbalance": 0.0,
        }
    bids = [(safe_float(level.price), safe_float(level.size)) for level in orderbook.bids if safe_float(level.price) > 0]
    asks = [(safe_float(level.price), safe_float(level.size)) for level in orderbook.asks if safe_float(level.price) > 0]
    best_bid, best_bid_size = max(bids, key=lambda item: item[0]) if bids else (0.0, 0.0)
    best_ask, best_ask_size = min(asks, key=lambda item: item[0]) if asks else (0.0, 0.0)
    spread = max(0.0, best_ask - best_bid) if best_bid and best_ask else 0.0
    mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0
    liquidity = sum(size for _, size in bids + asks)
    depth = float(len(bids) + len(asks))
    top_size = best_bid_size + best_ask_size
    imbalance = ((best_bid_size - best_ask_size) / top_size) if top_size else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_size": best_bid_size,
        "best_ask_size": best_ask_size,
        "spread": spread,
        "mid": mid,
        "liquidity": liquidity,
        "depth": depth,
        "imbalance": imbalance,
    }


def confidence_score(spread: float, depth: float, liquidity: float, min_depth: float) -> float:
    spread_component = clamp(1.0 - (spread / 0.08))
    depth_component = clamp(depth / max(min_depth * 4.0, 1.0))
    liquidity_component = clamp(liquidity / 100.0)
    return round((0.45 * spread_component) + (0.30 * depth_component) + (0.25 * liquidity_component), 6)


def calibrated_confidence_score(
    spread: float,
    depth: float,
    liquidity: float,
    bid_size: float,
    ask_size: float,
    min_depth: float,
) -> tuple[float, float]:
    spread_component = clamp(1.0 - (spread / 0.04))
    depth_component = clamp(depth / max(min_depth * 8.0, 1.0))
    liquidity_component = clamp(liquidity / 250.0)
    total_top = bid_size + ask_size
    bid_support_component = clamp(bid_size / total_top) if total_top else 0.0
    raw_confidence = (
        0.35 * spread_component
        + 0.25 * depth_component
        + 0.20 * liquidity_component
        + 0.20 * bid_support_component
    )
    confidence_penalty = clamp((spread / 0.10) + (1.0 - bid_support_component) * 0.15, 0.0, 0.35)
    return round(clamp(raw_confidence - confidence_penalty), 6), round(confidence_penalty, 6)


def action_for_candidate(
    expected_edge: float,
    confidence: float,
    depth: float,
    spread: float,
    side_ask: float,
    risk_flags: list[str],
    args: argparse.Namespace,
) -> EdgeAction:
    if side_ask <= 0 or depth < args.min_depth or "avoid_candidate" in risk_flags or "forbidden_category" in risk_flags or "ambiguous_market" in risk_flags:
        return EdgeAction.REJECT
    edge_gate = max(args.min_expected_edge, spread + args.spread_buffer)
    if expected_edge > edge_gate and confidence >= args.min_confidence:
        return EdgeAction.SHADOW_ENTRY
    return EdgeAction.WATCH_ONLY


def action_for_probability_v2(
    candidate: EdgeCandidate,
    side_bid: float,
    side_bid_size: float,
    args: argparse.Namespace,
) -> EdgeAction:
    if (
        candidate.entry_price <= 0
        or side_bid <= 0
        or side_bid_size < args.min_depth
        or candidate.depth < args.min_depth
        or candidate.spread > 0.05
        or "avoid_candidate" in candidate.risk_flags
        or "forbidden_category" in candidate.risk_flags
        or "ambiguous_market" in candidate.risk_flags
    ):
        return EdgeAction.REJECT if candidate.entry_price <= 0 or side_bid <= 0 else EdgeAction.WATCH_ONLY
    edge_gate = max(args.min_expected_edge, candidate.spread + args.spread_buffer)
    if candidate.calibrated_expected_edge > edge_gate and candidate.confidence >= args.min_confidence:
        return EdgeAction.SHADOW_ENTRY
    return EdgeAction.WATCH_ONLY


def common_market_values(
    market: dict[str, Any],
    pair: TokenPair,
    yes: dict[str, float],
    no: dict[str, float],
    timestamp: str,
) -> dict[str, Any]:
    combined_ask = yes["best_ask"] + no["best_ask"] if yes["best_ask"] and no["best_ask"] else 0.0
    combined_ask_gap = max(0.0, 1.0 - combined_ask) if combined_ask else 0.0
    max_spread = max(yes["spread"], no["spread"])
    depth = yes["depth"] + no["depth"]
    liquidity = yes["liquidity"] + no["liquidity"]
    return {
        "market_id": market_id(market),
        "question": question(market),
        "yes_token_id": pair.yes_token_id,
        "no_token_id": pair.no_token_id,
        "yes_best_bid": yes["best_bid"],
        "yes_best_ask": yes["best_ask"],
        "no_best_bid": no["best_bid"],
        "no_best_ask": no["best_ask"],
        "combined_ask": combined_ask,
        "combined_ask_gap": combined_ask_gap,
        "spread": max_spread,
        "depth": depth,
        "liquidity_score": liquidity,
        "timestamp": timestamp,
        "category": str(market.get("category") or ""),
        "volume": market_volume(market),
    }


def combined_ask_arbitrage_edge(
    market: dict[str, Any],
    pair: TokenPair,
    yes: dict[str, float],
    no: dict[str, float],
    args: argparse.Namespace,
    timestamp: str,
    risk_flags: list[str],
) -> EdgeCandidate:
    common = common_market_values(market, pair, yes, no, timestamp)
    executable_edge = common["combined_ask_gap"] - common["spread"] - args.spread_buffer
    confidence = confidence_score(common["spread"], common["depth"], common["liquidity_score"], args.min_depth)
    evidence = ["combined_ask_arbitrage"]
    if common["combined_ask"] >= 1.0:
        evidence.append("combined_ask_not_below_one")
    action = action_for_candidate(
        executable_edge,
        confidence,
        common["depth"],
        common["spread"],
        yes["best_ask"],
        risk_flags,
        args,
    )
    return EdgeCandidate(
        edge_type=EdgeType.COMBINED_ASK_ARBITRAGE,
        side="YES",
        entry_price=yes["best_ask"],
        estimated_probability=1.0 - no["best_ask"] if no["best_ask"] else 0.0,
        expected_edge=executable_edge,
        confidence=confidence,
        risk_flags=risk_flags,
        evidence=evidence,
        recommended_action=action,
        executable_edge=executable_edge,
        source="multi_edge_discovery",
        **common,
    )


def probability_edge_for_side(
    market: dict[str, Any],
    pair: TokenPair,
    yes: dict[str, float],
    no: dict[str, float],
    side: str,
    args: argparse.Namespace,
    timestamp: str,
    risk_flags: list[str],
) -> EdgeCandidate:
    common = common_market_values(market, pair, yes, no, timestamp)
    features = yes if side == "YES" else no
    entry_price = features["best_ask"]
    base_prob = features["mid"]
    # Explicit microstructure adjustment. It uses only top-of-book imbalance and
    # is capped so it cannot become a subjective/news-based probability model.
    micro_adjustment = clamp(features["imbalance"] * 0.06, -0.06, 0.06)
    estimated_probability = clamp(base_prob + micro_adjustment)
    expected_edge = estimated_probability - entry_price - args.spread_buffer
    confidence = confidence_score(features["spread"], features["depth"], features["liquidity"], args.min_depth)
    evidence = [
        "probability_edge_v1",
        "microstructure_probability_edge",
        f"base_prob={base_prob:.6f}",
        f"imbalance_adjustment={micro_adjustment:.6f}",
    ]
    action = action_for_candidate(
        expected_edge,
        confidence,
        common["depth"],
        features["spread"],
        entry_price,
        risk_flags,
        args,
    )
    return EdgeCandidate(
        edge_type=EdgeType.PRICE_DISLOCATION_PROBABILITY_V1,
        side=side,
        entry_price=entry_price,
        estimated_probability=estimated_probability,
        expected_edge=expected_edge,
        confidence=confidence,
        risk_flags=risk_flags,
        evidence=evidence,
        recommended_action=action,
        executable_edge=expected_edge,
        source="multi_edge_discovery",
        **common,
    )


def probability_edge_v2_for_side(
    market: dict[str, Any],
    pair: TokenPair,
    yes: dict[str, float],
    no: dict[str, float],
    side: str,
    args: argparse.Namespace,
    timestamp: str,
    risk_flags: list[str],
) -> EdgeCandidate:
    common = common_market_values(market, pair, yes, no, timestamp)
    features = yes if side == "YES" else no
    entry_price = features["best_ask"]
    raw_estimated_probability = features["mid"]
    probability_adjustment = clamp(features["imbalance"] * 0.03, -0.03, 0.03)
    calibrated_estimated_probability = clamp(raw_estimated_probability + probability_adjustment)
    raw_expected_edge = raw_estimated_probability + probability_adjustment - entry_price - args.spread_buffer

    bid_size = features["best_bid_size"]
    ask_size = features["best_ask_size"]
    total_top = bid_size + ask_size
    bid_support = (bid_size / total_top) if total_top else 0.0
    bid_depth_shortfall = clamp((args.min_depth - bid_size) / max(args.min_depth, 1.0))
    exit_bid_penalty = round(max(features["spread"], 0.0) * 0.75 + bid_depth_shortfall * 0.02, 6)
    adverse_selection_penalty = round(
        clamp(features["spread"] * 0.50 + (1.0 - bid_support) * 0.02 + (1.0 / max(features["depth"], 1.0)) * 0.01, 0.0, 0.08),
        6,
    )
    liquidity_penalty = round(clamp((50.0 - features["liquidity"]) / 50.0, 0.0, 1.0) * 0.02, 6)
    calibrated_expected_edge = (
        calibrated_estimated_probability
        - entry_price
        - args.spread_buffer
        - exit_bid_penalty
        - adverse_selection_penalty
        - liquidity_penalty
    )
    calibrated_expected_edge = min(calibrated_expected_edge, raw_expected_edge)
    confidence, confidence_penalty = calibrated_confidence_score(
        features["spread"],
        features["depth"],
        features["liquidity"],
        bid_size,
        ask_size,
        args.min_depth,
    )
    evidence = [
        "probability_edge_v2",
        "calibrated_microstructure_probability_edge",
        f"raw_prob={raw_estimated_probability:.6f}",
        f"probability_adjustment={probability_adjustment:.6f}",
        f"exit_bid_penalty={exit_bid_penalty:.6f}",
        f"adverse_selection_penalty={adverse_selection_penalty:.6f}",
        f"liquidity_penalty={liquidity_penalty:.6f}",
    ]
    candidate = EdgeCandidate(
        edge_type=EdgeType.PRICE_DISLOCATION_PROBABILITY_V2,
        side=side,
        entry_price=entry_price,
        estimated_probability=calibrated_estimated_probability,
        expected_edge=calibrated_expected_edge,
        confidence=confidence,
        risk_flags=risk_flags,
        evidence=evidence,
        recommended_action=EdgeAction.WATCH_ONLY,
        executable_edge=calibrated_expected_edge,
        source="multi_edge_discovery",
        raw_estimated_probability=raw_estimated_probability,
        calibrated_estimated_probability=calibrated_estimated_probability,
        probability_adjustment=probability_adjustment,
        exit_bid_penalty=exit_bid_penalty,
        adverse_selection_penalty=adverse_selection_penalty,
        liquidity_penalty=liquidity_penalty,
        confidence_penalty=confidence_penalty,
        calibrated_expected_edge=calibrated_expected_edge,
        calibration_version="probability_edge_v2",
        **common,
    )
    candidate.recommended_action = action_for_probability_v2(candidate, features["best_bid"], bid_size, args)
    if candidate.recommended_action != EdgeAction.SHADOW_ENTRY:
        if entry_price <= 0:
            candidate.evidence.append("missing_entry_ask")
        elif features["best_bid"] <= 0:
            candidate.evidence.append("missing_exit_bid")
        elif bid_size < args.min_depth:
            candidate.evidence.append("exit_bid_depth_insufficient")
        elif candidate.calibrated_expected_edge <= max(args.min_expected_edge, candidate.spread + args.spread_buffer):
            candidate.evidence.append("calibrated_edge_too_low")
        elif candidate.confidence < args.min_confidence:
            candidate.evidence.append("confidence_too_low")
    return candidate


def candidate_to_output(candidate: EdgeCandidate) -> dict[str, Any]:
    row = candidate.to_dict()
    row.update({
        "max_spread": candidate.spread,
        "orderbook_depth": candidate.depth,
        "entry_yes_best_ask": candidate.yes_best_ask,
        "entry_no_best_ask": candidate.no_best_ask,
        "entry_yes_best_bid": candidate.yes_best_bid,
        "entry_no_best_bid": candidate.no_best_bid,
        "expected_edge_source": candidate.edge_type.value,
        "expected_edge_status": "edge_positive" if candidate.expected_edge > 0 else "edge_too_low",
        "edge_pass": candidate.recommended_action == EdgeAction.SHADOW_ENTRY,
        "edge_failure_reason": "" if candidate.recommended_action == EdgeAction.SHADOW_ENTRY else "edge_too_low",
        "reasons": row["evidence"],
        "near_miss_tier": "tier1_mispricing" if candidate.recommended_action == EdgeAction.SHADOW_ENTRY else "",
        "evidence_level": "microstructure_edge",
        "entry_decision_hint": "eligible_shadow_entry" if candidate.recommended_action == EdgeAction.SHADOW_ENTRY else "watch_only",
        "tradable_score": 0.0,
    })
    return row


async def discover_multi_edges(
    args: argparse.Namespace,
    gamma_client: Any | None = None,
    clob_client: Any | None = None,
) -> tuple[list[EdgeCandidate], dict[str, Any]]:
    started = datetime.utcnow()
    timestamp = started.isoformat()
    gamma = gamma_client or GammaActiveMarketClient()
    clob = clob_client or CLOBReadOnlyClient(max_retries=1)
    close_clob = clob_client is None
    api_error_count = 0
    errors: list[dict[str, str]] = []
    candidates: list[EdgeCandidate] = []
    raw_markets: list[dict[str, Any]] = []
    markets_with_token_ids = 0
    orderbooks_fetched = 0
    avoid_ids = load_avoid_ids(Path(args.output_dir))

    try:
        try:
            raw_markets = await gamma.fetch_active_markets(args.max_markets)
        except Exception as exc:
            raw_markets = []
            api_error_count += 1
            errors.append({"stage": "gamma_markets", "error": str(exc)})
        markets = filter_markets(raw_markets, args.min_volume, args.max_markets)
        if args.dry_run:
            summary = summarize(started, markets, 0, 0, [], api_error_count, errors)
            summary["active_markets_available"] = len(markets)
            feedback_gates = build_feedback_gates(Path(args.output_dir))
            summary["feedback_gates"] = {edge_type: gate.to_dict() for edge_type, gate in feedback_gates.items()}
            return [], summary

        for market in markets:
            safety_reject = market_safety_reject_reason(market, avoid_ids)
            if safety_reject:
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
            yes = book_features(yes_book)
            no = book_features(no_book)
            risk_flags: list[str] = []
            if yes["best_ask"] <= 0 or no["best_ask"] <= 0:
                risk_flags.append("missing_side_ask")
            if yes["depth"] + no["depth"] < args.min_depth:
                risk_flags.append("insufficient_depth")
            candidates.append(combined_ask_arbitrage_edge(market, pair, yes, no, args, timestamp, risk_flags))
            if args.edge_version in {"v1", "both"}:
                candidates.append(probability_edge_for_side(market, pair, yes, no, "YES", args, timestamp, risk_flags))
                candidates.append(probability_edge_for_side(market, pair, yes, no, "NO", args, timestamp, risk_flags))
            if args.edge_version in {"v2", "both"}:
                candidates.append(probability_edge_v2_for_side(market, pair, yes, no, "YES", args, timestamp, risk_flags))
                candidates.append(probability_edge_v2_for_side(market, pair, yes, no, "NO", args, timestamp, risk_flags))
    finally:
        if close_clob:
            await clob.close()

    feedback_gates = build_feedback_gates(Path(args.output_dir))
    apply_feedback_gates(candidates, feedback_gates)
    summary = summarize(started, filter_markets(raw_markets, args.min_volume, args.max_markets), markets_with_token_ids, orderbooks_fetched, candidates, api_error_count, errors)
    summary["feedback_gates"] = {edge_type: gate.to_dict() for edge_type, gate in feedback_gates.items()}
    return candidates, summary


def summarize(
    started: datetime,
    markets: list[dict[str, Any]],
    markets_with_token_ids: int,
    orderbooks_fetched: int,
    candidates: list[EdgeCandidate],
    api_error_count: int,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    ended = datetime.utcnow()
    edge_type_counts: dict[str, int] = {}
    for candidate in candidates:
        edge_type_counts[candidate.edge_type.value] = edge_type_counts.get(candidate.edge_type.value, 0) + 1
    expected_edges = [candidate.expected_edge for candidate in candidates]
    raw_edges = [
        candidate.raw_estimated_probability + candidate.probability_adjustment - candidate.entry_price
        for candidate in candidates
        if candidate.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V2
    ]
    calibrated_edges = [
        candidate.calibrated_expected_edge
        for candidate in candidates
        if candidate.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V2
    ]
    confidences = [candidate.confidence for candidate in candidates]
    v2_candidates = [candidate for candidate in candidates if candidate.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V2]
    v1_candidates = [candidate for candidate in candidates if candidate.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V1]
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "markets_scanned": len(markets),
        "markets_with_token_ids": markets_with_token_ids,
        "orderbooks_fetched": orderbooks_fetched,
        "edge_type_counts": edge_type_counts,
        "combined_ask_arbitrage_count": edge_type_counts.get(EdgeType.COMBINED_ASK_ARBITRAGE.value, 0),
        "probability_edge_count": edge_type_counts.get(EdgeType.PRICE_DISLOCATION_PROBABILITY_V1.value, 0),
        "probability_edge_v2_count": edge_type_counts.get(EdgeType.PRICE_DISLOCATION_PROBABILITY_V2.value, 0),
        "v1_shadow_entry_candidates": sum(1 for candidate in v1_candidates if candidate.recommended_action == EdgeAction.SHADOW_ENTRY),
        "v2_shadow_entry_candidates": sum(1 for candidate in v2_candidates if candidate.recommended_action == EdgeAction.SHADOW_ENTRY),
        "v2_watch_only_candidates": sum(1 for candidate in v2_candidates if candidate.recommended_action == EdgeAction.WATCH_ONLY),
        "v2_rejected_candidates": sum(1 for candidate in v2_candidates if candidate.recommended_action == EdgeAction.REJECT),
        "shadow_entry_candidates": sum(1 for candidate in candidates if candidate.recommended_action == EdgeAction.SHADOW_ENTRY),
        "watch_only_candidates": sum(1 for candidate in candidates if candidate.recommended_action == EdgeAction.WATCH_ONLY),
        "rejected_candidates": sum(1 for candidate in candidates if candidate.recommended_action == EdgeAction.REJECT),
        "avg_expected_edge": mean(expected_edges) if expected_edges else 0.0,
        "max_expected_edge": max(expected_edges) if expected_edges else 0.0,
        "avg_raw_expected_edge": mean(raw_edges) if raw_edges else 0.0,
        "avg_calibrated_expected_edge": mean(calibrated_edges) if calibrated_edges else 0.0,
        "avg_confidence": mean(confidences) if confidences else 0.0,
        "exit_bid_penalty_avg": mean([candidate.exit_bid_penalty for candidate in v2_candidates]) if v2_candidates else 0.0,
        "adverse_selection_penalty_avg": mean([candidate.adverse_selection_penalty for candidate in v2_candidates]) if v2_candidates else 0.0,
        "liquidity_penalty_avg": mean([candidate.liquidity_penalty for candidate in v2_candidates]) if v2_candidates else 0.0,
        "api_error_count": api_error_count,
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": "NO",
        "errors": errors[:100],
    }


def output_rows(candidates: list[EdgeCandidate]) -> list[dict[str, Any]]:
    return [candidate_to_output(candidate) for candidate in candidates]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(EDGE_CANDIDATE_FIELDS)
    for extra in [
        "max_spread",
        "orderbook_depth",
        "entry_yes_best_ask",
        "entry_no_best_ask",
        "entry_yes_best_bid",
        "entry_no_best_bid",
        "expected_edge_source",
        "expected_edge_status",
        "edge_pass",
        "edge_failure_reason",
        "reasons",
        "near_miss_tier",
        "evidence_level",
        "entry_decision_hint",
        "tradable_score",
    ]:
        if extra not in fields:
            fields.append(extra)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"multi_edge_candidates": rows}, indent=2, sort_keys=True))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Multi-Edge Discovery Report",
        "",
        f"Generated at: `{summary['ended_at']}`",
        "",
        "This is read-only, shadow-only multi-edge discovery.",
        "Implemented edge types: combined_ask_arbitrage and price_dislocation_probability_v1.",
        "probability_edge_v2 is a conservative calibration that discounts exit bid weakness, adverse selection, and liquidity risk.",
        "Reserved but not implemented: stale_price_lag, closing_market_convergence, cross_market_consistency, spread_capture_passive.",
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
        "combined_ask_arbitrage_count",
        "probability_edge_count",
        "probability_edge_v2_count",
        "v1_shadow_entry_candidates",
        "v2_shadow_entry_candidates",
        "v2_watch_only_candidates",
        "v2_rejected_candidates",
        "shadow_entry_candidates",
        "watch_only_candidates",
        "rejected_candidates",
        "avg_expected_edge",
        "avg_raw_expected_edge",
        "avg_calibrated_expected_edge",
        "max_expected_edge",
        "avg_confidence",
        "exit_bid_penalty_avg",
        "adverse_selection_penalty_avg",
        "liquidity_penalty_avg",
        "api_error_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        "## Edge Type Counts",
        "",
        "```json",
        json.dumps(summary.get("edge_type_counts", {}), indent=2, sort_keys=True),
        "```",
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


def write_feedback_gate_summary(path: Path, summary: dict[str, Any]) -> None:
    payload = {
        "generated_at": summary.get("ended_at"),
        "feedback_gates": summary.get("feedback_gates", {}),
        "tiny_live_recommendation": "NO",
        "safety_verification": summary.get("safety_verification", {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def write_feedback_gate_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Edge Feedback Gate Report",
        "",
        f"Generated at: `{summary.get('ended_at')}`",
        "",
        "Probability edge types are shadow-entry gated by closed shadow PnL feedback.",
        "A failed gate forces probability candidates to watch_only. Combined ask arbitrage is not probability-gated.",
        "",
        "## Gate Status",
        "",
        "| Edge Type | Status | Gate Passed | Trades | Avg Return | Edge Corr | Confidence Corr | Reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for edge_type, gate in sorted((summary.get("feedback_gates") or {}).items()):
        lines.append(
            f"| {edge_type} | {gate.get('status')} | {gate.get('gate_passed')} | "
            f"{gate.get('trades_analyzed')} | {gate.get('average_return')} | "
            f"{gate.get('expected_edge_realized_return_correlation')} | "
            f"{gate.get('confidence_win_correlation')} | {gate.get('gate_reason')} |"
        )
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
    print("DRY RUN: multi-edge discovery" if dry_run else "Multi-edge discovery")
    for key in [
        "markets_scanned",
        "active_markets_available",
        "orderbooks_fetched",
        "combined_ask_arbitrage_count",
        "probability_edge_count",
        "probability_edge_v2_count",
        "v1_shadow_entry_candidates",
        "v2_shadow_entry_candidates",
        "v2_watch_only_candidates",
        "v2_rejected_candidates",
        "shadow_entry_candidates",
        "watch_only_candidates",
        "rejected_candidates",
        "avg_expected_edge",
        "avg_raw_expected_edge",
        "avg_calibrated_expected_edge",
        "max_expected_edge",
        "avg_confidence",
        "exit_bid_penalty_avg",
        "adverse_selection_penalty_avg",
        "liquidity_penalty_avg",
        "api_error_count",
    ]:
        if key in summary:
            print(f"{key}: {summary.get(key, 0)}")
    print(f"edge_type_counts: {summary.get('edge_type_counts', {})}")
    if summary.get("feedback_gates"):
        gate_status = {
            edge_type: {
                "status": gate.get("status"),
                "gate_passed": gate.get("gate_passed"),
                "gate_reason": gate.get("gate_reason"),
            }
            for edge_type, gate in summary.get("feedback_gates", {}).items()
        }
        print(f"feedback_gates: {gate_status}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


async def run_async(args: argparse.Namespace) -> tuple[list[EdgeCandidate], dict[str, Any]]:
    if args.data_mode != "real_readonly":
        raise ValueError("discover_multi_edge_candidates only supports data_mode=real_readonly")
    return await discover_multi_edges(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates, summary = asyncio.run(run_async(args))
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    rows = output_rows(candidates)
    output_dir = Path(args.output_dir)
    suffix = args.output_suffix or ""
    candidates_csv = output_dir / f"multi_edge_candidates{suffix}.csv"
    candidates_json = output_dir / f"multi_edge_candidates{suffix}.json"
    summary_json = output_dir / f"multi_edge_discovery{suffix}_summary.json"
    report_md = output_dir / f"multi_edge_discovery{suffix}_report.md"
    gate_summary_json = output_dir / "edge_feedback_gate_summary.json"
    gate_report_md = output_dir / "edge_feedback_gate_report.md"
    write_csv(candidates_csv, rows)
    write_json(candidates_json, rows)
    write_summary(summary_json, summary)
    write_report(report_md, summary)
    write_feedback_gate_summary(gate_summary_json, summary)
    write_feedback_gate_report(gate_report_md, summary)
    print(f"multi_edge_candidates_csv: {candidates_csv}")
    print(f"multi_edge_candidates_json: {candidates_json}")
    print(f"multi_edge_discovery_summary_json: {summary_json}")
    print(f"multi_edge_discovery_report_md: {report_md}")
    print(f"edge_feedback_gate_summary_json: {gate_summary_json}")
    print(f"edge_feedback_gate_report_md: {gate_report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
