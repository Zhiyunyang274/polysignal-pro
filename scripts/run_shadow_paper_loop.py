#!/usr/bin/env python3
"""
Phase 8A — Offline Shadow Paper Trading Loop.

This script reads existing run artifacts and produces hypothetical shadow
entries/exits for paper performance validation.

It never calls run_paper.py, real APIs, real LLM providers, or execution modules.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Optional
from collections import Counter

import yaml

from polysignal.shadow.entry_filter import EntryDecision, EntryFilterConfig, ShadowEntryFilter, filter_shadow_entries
from polysignal.shadow.exit_rules import ExitRuleConfig, decide_exit
from polysignal.shadow.models import CandidateSnapshot, ShadowSide, ShadowTrade
from polysignal.shadow.pnl import apply_excursions, apply_exit_to_trade, mark_insufficient_forward_data
from polysignal.shadow.reporter import write_all_reports_with_diagnostics


REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate offline shadow paper trades")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs/shadow")
    parser.add_argument("--min_alpha_score", type=float, default=35.0)
    parser.add_argument("--max_ambiguity_risk", type=float, default=30.0)
    parser.add_argument("--min_liquidity_score", type=float, default=1.0)
    parser.add_argument("--max_spread", type=float, default=0.05)
    parser.add_argument("--fixed_horizon_minutes", type=int, default=240)
    parser.add_argument("--stop_loss_pct", type=float, default=-0.05)
    parser.add_argument("--take_profit_pct", type=float, default=0.05)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--watch_only_output", action="store_true")
    parser.add_argument("--min_watch_alpha_score", type=float, default=30.0)
    parser.add_argument("--watch_tier3", action="store_true", default=True)
    parser.add_argument("--max_shadow_entries", type=int, default=25)
    parser.add_argument("--min_expected_edge", type=float, default=0.001)
    parser.add_argument("--min_confidence", type=float, default=0.6)
    parser.add_argument("--edge_type", type=str, default="all")
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    if not path.exists():
        return [] if path.suffix == ".json" else {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return [] if path.suffix == ".json" else {}


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def safe_optional_bool(value: Any) -> Optional[bool]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def split_reasons(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def side_price(row: dict[str, Any], *names: str) -> float:
    for name in names:
        value = safe_float(row.get(name), 0.0)
        if value > 0:
            return value
    return 0.0


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
        "safe_to_shadow_trade": (
            bool(risk.get("live_trading_enabled")) is False
            and bool(risk.get("allow_auto_execution")) is False
            and bool(risk.get("paper_trading_enabled")) is True
        ),
    }


def normalize_tier(value: str) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "tier1": "tier1_mispricing",
        "tier 1": "tier1_mispricing",
        "tier2": "tier2_strong_near_miss",
        "tier 2": "tier2_strong_near_miss",
        "tier3": "tier3_weak_near_miss",
        "tier 3": "tier3_weak_near_miss",
    }
    return mapping.get(raw, raw)


def latest_observation(trajectory: list[dict[str, Any]]) -> dict[str, Any]:
    if not trajectory:
        return {}
    return trajectory[-1]


def build_trajectory_index(raw: Any) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, list):
        return index
    for item in raw:
        if not isinstance(item, dict):
            continue
        market_id = str(item.get("market_id") or "")
        if market_id:
            index[market_id] = item
    return index


def avoid_market_ids(rows: list[dict[str, str]]) -> set[str]:
    return {str(row.get("market_id") or "") for row in rows if row.get("market_id")}


def candidate_from_alpha(
    row: dict[str, str],
    trajectory_item: dict[str, Any],
    avoid_ids: set[str],
) -> CandidateSnapshot:
    trajectory = trajectory_item.get("trajectory", []) if isinstance(trajectory_item, dict) else []
    last = latest_observation(trajectory)
    appearances = safe_float(row.get("appearances"), 0.0)
    liquidity = max(appearances, safe_float(row.get("avg_volume"), 0.0))
    combined_ask = safe_float(row.get("avg_combined_ask"), safe_float(last.get("combined_ask"), 1.0))
    ambiguity = safe_float(row.get("avg_ambiguity_risk"), safe_float(last.get("ambiguity_risk"), 0.0))
    return CandidateSnapshot(
        market_id=str(row.get("market_id") or ""),
        question=str(row.get("question") or ""),
        side=ShadowSide.YES,
        run_id=str(row.get("run_ids") or "").split("|")[0],
        category=str(row.get("category") or trajectory_item.get("category", "")),
        entry_time=str(last.get("timestamp") or ""),
        alpha_score=safe_float(row.get("alpha_score")),
        expected_edge=safe_float(row.get("expected_edge"), 0.0),
        entry_yes_best_ask=side_price(row, "entry_yes_best_ask", "yes_best_ask"),
        entry_no_best_ask=side_price(row, "entry_no_best_ask", "no_best_ask"),
        entry_yes_best_bid=side_price(row, "entry_yes_best_bid", "yes_best_bid"),
        entry_no_best_bid=side_price(row, "entry_no_best_bid", "no_best_bid"),
        combined_ask=combined_ask,
        liquidity_score=liquidity,
        ambiguity_risk=ambiguity,
        near_miss_tier=normalize_tier(str(last.get("near_miss_tier") or "")),
        orderbook_spread=max(0.0, combined_ask - 1.0),
        orderbook_depth=liquidity,
        risk_decision="allow_shadow",
        is_avoid_candidate=str(row.get("market_id") or "") in avoid_ids,
        is_stale=False,
        is_llm_only=False,
        source="alpha_candidate",
        observations=trajectory[1:] if len(trajectory) > 1 else trajectory,
    )


def candidate_from_watchlist(
    row: dict[str, str],
    trajectory_item: dict[str, Any],
    avoid_ids: set[str],
) -> CandidateSnapshot:
    trajectory = trajectory_item.get("trajectory", []) if isinstance(trajectory_item, dict) else []
    last = latest_observation(trajectory)
    appearances = safe_float(row.get("appearances"), 0.0)
    combined_ask = safe_float(row.get("avg_combined_ask"), safe_float(last.get("combined_ask"), 1.0))
    ambiguity = safe_float(row.get("avg_ambiguity_risk"), safe_float(last.get("ambiguity_risk"), 0.0))
    suggested_mode = str(row.get("suggested_mode_mode") or last.get("suggested_mode") or "")
    tier = "tier2_strong_near_miss" if suggested_mode in {"alert", "alert_only", "research"} else ""
    return CandidateSnapshot(
        market_id=str(row.get("market_id") or ""),
        question=str(row.get("question") or ""),
        side=ShadowSide.YES,
        run_id=str(row.get("run_ids") or "").split("|")[0],
        category=str(row.get("category") or trajectory_item.get("category", "")),
        entry_time=str(last.get("timestamp") or ""),
        alpha_score=0.0,
        expected_edge=safe_float(row.get("expected_edge"), 0.0),
        entry_yes_best_ask=side_price(row, "entry_yes_best_ask", "yes_best_ask"),
        entry_no_best_ask=side_price(row, "entry_no_best_ask", "no_best_ask"),
        entry_yes_best_bid=side_price(row, "entry_yes_best_bid", "yes_best_bid"),
        entry_no_best_bid=side_price(row, "entry_no_best_bid", "no_best_bid"),
        combined_ask=combined_ask,
        liquidity_score=appearances,
        ambiguity_risk=ambiguity,
        near_miss_tier=tier,
        orderbook_spread=max(0.0, combined_ask - 1.0),
        orderbook_depth=appearances,
        risk_decision="allow_shadow",
        is_avoid_candidate=str(row.get("market_id") or "") in avoid_ids,
        is_stale=False,
        is_llm_only=False,
        source="watchlist",
        observations=trajectory[1:] if len(trajectory) > 1 else trajectory,
    )


def candidate_from_tradable(row: dict[str, str], avoid_ids: set[str]) -> CandidateSnapshot:
    combined_ask = safe_float(row.get("combined_ask"), 0.0)
    liquidity = safe_float(row.get("liquidity_score"), 0.0)
    side = ShadowSide.NO if str(row.get("side") or "").strip().upper() == "NO" else ShadowSide.YES
    return CandidateSnapshot(
        market_id=str(row.get("market_id") or ""),
        question=str(row.get("question") or ""),
        side=side,
        run_id=str(row.get("run_ids") or "").split("|")[0],
        category=str(row.get("category") or ""),
        entry_time="",
        alpha_score=safe_float(row.get("alpha_score"), 0.0),
        expected_edge=safe_float(row.get("expected_edge"), 0.0),
        executable_edge=safe_float(row.get("executable_edge"), safe_float(row.get("expected_edge"), 0.0)),
        combined_ask_gap=safe_float(row.get("combined_ask_gap"), 0.0),
        expected_edge_source=str(row.get("expected_edge_source") or ""),
        expected_edge_status=str(row.get("expected_edge_status") or ""),
        edge_pass=safe_optional_bool(row.get("edge_pass")),
        edge_failure_reason=str(row.get("edge_failure_reason") or ""),
        edge_notes=str(row.get("edge_notes") or ""),
        confidence=safe_float(row.get("confidence"), 0.0),
        edge_type=str(row.get("edge_type") or ""),
        evidence=str(row.get("evidence") or row.get("reasons") or ""),
        relationship_status=str(row.get("relationship_status") or ""),
        relationship_confidence=safe_float(row.get("relationship_confidence"), 0.0),
        price_gap=safe_float(row.get("price_gap"), 0.0),
        reference_market_id=str(row.get("reference_market_id") or ""),
        reference_question=str(row.get("reference_question") or ""),
        reference_price=safe_float(row.get("reference_price"), 0.0),
        convergence_gate_passed=safe_optional_bool(row.get("convergence_gate_passed")),
        convergence_score=safe_float(row.get("convergence_score"), 0.0),
        convergence_status=str(row.get("convergence_status") or ""),
        convergence_reason=str(row.get("convergence_reason") or ""),
        convergence_observation_count=int(safe_float(row.get("convergence_observation_count"), 0.0)),
        initial_price_gap=safe_float(row.get("initial_price_gap"), 0.0),
        final_price_gap=safe_float(row.get("final_price_gap"), 0.0),
        gap_change=safe_float(row.get("gap_change"), 0.0),
        feedback_gate_status=str(row.get("feedback_gate_status") or ""),
        feedback_gate_reason=str(row.get("feedback_gate_reason") or ""),
        gate_passed=safe_optional_bool(row.get("gate_passed")),
        entry_yes_best_ask=side_price(row, "entry_yes_best_ask", "yes_best_ask"),
        entry_no_best_ask=side_price(row, "entry_no_best_ask", "no_best_ask"),
        entry_yes_best_bid=side_price(row, "entry_yes_best_bid", "yes_best_bid"),
        entry_no_best_bid=side_price(row, "entry_no_best_bid", "no_best_bid"),
        combined_ask=combined_ask,
        liquidity_score=liquidity,
        ambiguity_risk=safe_float(row.get("ambiguity_risk"), 0.0),
        near_miss_tier=normalize_tier(str(row.get("near_miss_tier") or "")),
        orderbook_spread=safe_float(row.get("spread"), max(0.0, combined_ask - 1.0)),
        orderbook_depth=safe_float(row.get("orderbook_depth"), liquidity),
        risk_decision="allow_shadow",
        is_avoid_candidate=safe_bool(row.get("is_avoid_candidate")) or str(row.get("market_id") or "") in avoid_ids,
        is_stale=False,
        is_llm_only=False,
        source="tradable_candidate",
        entry_decision_hint=str(row.get("entry_decision_hint") or ""),
        tradable_score=safe_float(row.get("tradable_score"), 0.0),
        tradable_source=str(row.get("source") or ""),
        tradable_reasons=split_reasons(row.get("reasons")),
        evidence_level=str(row.get("evidence_level") or ""),
        yes_token_id=str(row.get("yes_token_id") or ""),
        no_token_id=str(row.get("no_token_id") or ""),
        observations=[],
    )


def load_tradable_candidates(runs_dir: Path, avoid_ids: set[str]) -> Optional[list[CandidateSnapshot]]:
    crypto_threshold_path = runs_dir / "crypto_threshold_edge_candidates.csv"
    cross_market_convergence_path = runs_dir / "cross_market_edge_candidates_convergence_gated.csv"
    cross_market_calibrated_path = runs_dir / "cross_market_edge_candidates_calibrated.csv"
    cross_market_path = runs_dir / "cross_market_edge_candidates.csv"
    multi_edge_gated_path = runs_dir / "multi_edge_candidates_gated.csv"
    multi_edge_v2_path = runs_dir / "multi_edge_candidates_v2.csv"
    multi_edge_path = runs_dir / "multi_edge_candidates.csv"
    edge_path = runs_dir / "executable_edge_candidates.csv"
    priced_path = runs_dir / "tradable_candidates_priced.csv"
    if crypto_threshold_path.exists():
        path = crypto_threshold_path
    elif cross_market_convergence_path.exists():
        path = cross_market_convergence_path
    elif cross_market_calibrated_path.exists():
        path = cross_market_calibrated_path
    elif cross_market_path.exists():
        path = cross_market_path
    elif multi_edge_gated_path.exists():
        path = multi_edge_gated_path
    elif multi_edge_v2_path.exists():
        path = multi_edge_v2_path
    elif multi_edge_path.exists():
        path = multi_edge_path
    elif edge_path.exists():
        path = edge_path
    elif priced_path.exists():
        path = priced_path
    else:
        path = runs_dir / "tradable_candidates.csv"
    if not path.exists():
        return None
    candidates = []
    load_watch_only_for_diagnostics = path.name in {
        "multi_edge_candidates_gated.csv",
        "cross_market_edge_candidates.csv",
        "cross_market_edge_candidates_calibrated.csv",
        "cross_market_edge_candidates_convergence_gated.csv",
    }
    for row in load_csv(path):
        market_id = str(row.get("market_id") or "")
        if (
            path.name.startswith("multi_edge_candidates")
            and not load_watch_only_for_diagnostics
            and str(row.get("recommended_action") or "") != "shadow_entry"
        ):
            continue
        if market_id:
            candidates.append(candidate_from_tradable(row, avoid_ids))
    return candidates


def load_candidates(runs_dir: Path) -> list[CandidateSnapshot]:
    avoid_rows = load_csv(runs_dir / "avoid_candidates.csv")
    avoid_ids = avoid_market_ids(avoid_rows)
    tradable_candidates = load_tradable_candidates(runs_dir, avoid_ids)
    if tradable_candidates is not None:
        return tradable_candidates

    alpha_rows = load_csv(runs_dir / "alpha_candidates.csv")
    watchlist_rows = load_csv(runs_dir / "persistent_watchlist.csv")
    trajectories = build_trajectory_index(load_json(runs_dir / "market_trajectories.json"))

    candidates: list[CandidateSnapshot] = []
    seen: set[str] = set()
    for row in alpha_rows:
        market_id = str(row.get("market_id") or "")
        if not market_id:
            continue
        candidates.append(candidate_from_alpha(row, trajectories.get(market_id, {}), avoid_ids))
        seen.add(market_id)
    for row in watchlist_rows:
        market_id = str(row.get("market_id") or "")
        if not market_id or market_id in seen:
            continue
        candidates.append(candidate_from_watchlist(row, trajectories.get(market_id, {}), avoid_ids))
    return candidates


def select_shadow_candidates(
    candidates: list[CandidateSnapshot],
    max_shadow_entries: int,
    min_expected_edge: float,
    min_confidence: float,
    edge_type: str = "all",
    apply_limit: bool = True,
) -> list[CandidateSnapshot]:
    edge_type_filter = (edge_type or "all").strip()
    filtered: list[CandidateSnapshot] = []
    for candidate in candidates:
        if edge_type_filter != "all" and candidate.edge_type != edge_type_filter:
            continue
        if candidate.edge_type:
            if candidate.expected_edge < min_expected_edge:
                continue
            if candidate.confidence < min_confidence:
                continue
        filtered.append(candidate)
    filtered.sort(
        key=lambda item: (
            item.expected_edge,
            item.confidence,
            item.liquidity_score,
            item.orderbook_depth,
        ),
        reverse=True,
    )
    if apply_limit and max_shadow_entries > 0:
        return filtered[:max_shadow_entries]
    return filtered


def forward_observations(candidate: CandidateSnapshot) -> list[dict[str, Any]]:
    return candidate.observations


def build_shadow_trades(
    candidates: list[CandidateSnapshot],
    entry_config: EntryFilterConfig,
    exit_config: ExitRuleConfig,
    max_shadow_entries: int = 0,
) -> list[ShadowTrade]:
    trades: list[ShadowTrade] = []
    for candidate, result in filter_shadow_entries(candidates, entry_config):
        if max_shadow_entries > 0 and len(trades) >= max_shadow_entries:
            break
        trade = ShadowTrade.from_candidate(candidate, result.reason)
        observations = forward_observations(candidate)
        if not observations:
            mark_insufficient_forward_data(trade)
            trades.append(trade)
            continue
        decision = decide_exit(trade, observations, exit_config)
        if not decision.should_exit or decision.exit_price is None:
            mark_insufficient_forward_data(trade, reason="missing_exit_side_bid")
            trades.append(trade)
            continue
        apply_exit_to_trade(
            trade,
            decision.exit_time,
            decision.exit_price,
            decision.reason,
            decision.holding_minutes,
        )
        apply_excursions(trade, observations)
        trades.append(trade)
    return trades


def build_entry_diagnostics(
    candidates: list[CandidateSnapshot],
    entry_config: EntryFilterConfig,
) -> list[dict[str, Any]]:
    entry_filter = ShadowEntryFilter(entry_config)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        result = entry_filter.evaluate(candidate)
        rows.append({
            "market_id": candidate.market_id,
            "question": candidate.question,
            "alpha_score": candidate.alpha_score,
            "ambiguity_risk": candidate.ambiguity_risk,
            "liquidity_score": candidate.liquidity_score,
            "combined_ask": candidate.combined_ask,
            "expected_edge": candidate.expected_edge,
            "confidence": candidate.confidence,
            "edge_type": candidate.edge_type,
            "evidence": candidate.evidence,
            "relationship_status": candidate.relationship_status,
            "relationship_confidence": candidate.relationship_confidence,
            "price_gap": candidate.price_gap,
            "reference_market_id": candidate.reference_market_id,
            "reference_price": candidate.reference_price,
            "convergence_gate_passed": candidate.convergence_gate_passed,
            "convergence_score": candidate.convergence_score,
            "convergence_status": candidate.convergence_status,
            "convergence_reason": candidate.convergence_reason,
            "convergence_observation_count": candidate.convergence_observation_count,
            "initial_price_gap": candidate.initial_price_gap,
            "final_price_gap": candidate.final_price_gap,
            "gap_change": candidate.gap_change,
            "feedback_gate_status": candidate.feedback_gate_status,
            "feedback_gate_reason": candidate.feedback_gate_reason,
            "gate_passed": candidate.gate_passed,
            "entry_side_price": candidate.entry_side_price or candidate.side_entry_ask(),
            "entry_yes_best_ask": candidate.entry_yes_best_ask,
            "entry_no_best_ask": candidate.entry_no_best_ask,
            "entry_yes_best_bid": candidate.entry_yes_best_bid,
            "entry_no_best_bid": candidate.entry_no_best_bid,
            "near_miss_tier": candidate.near_miss_tier,
            "is_avoid_candidate": candidate.is_avoid_candidate,
            "tradable_score": candidate.tradable_score,
            "tradable_source": candidate.tradable_source,
            "tradable_reasons": candidate.tradable_reasons,
            "evidence_level": candidate.evidence_level,
            "entry_decision": result.entry_decision.value,
            "reject_reasons": result.reject_reasons,
            "watch_reasons": result.watch_reasons,
        })
    return rows


def summarize_diagnostics(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("entry_decision")) for row in diagnostics)
    rejection_reasons: Counter[str] = Counter()
    watch_reasons: Counter[str] = Counter()
    for row in diagnostics:
        rejection_reasons.update(row.get("reject_reasons", []))
        watch_reasons.update(row.get("watch_reasons", []))

    watch_candidates = [
        {
            "market_id": row.get("market_id"),
            "question": row.get("question"),
            "alpha_score": row.get("alpha_score"),
            "tradable_score": row.get("tradable_score"),
            "watch_reasons": row.get("watch_reasons", []),
        }
        for row in diagnostics
        if row.get("entry_decision") == EntryDecision.WATCH_ONLY.value
    ]
    watch_candidates.sort(
        key=lambda item: max(
            safe_float(item.get("alpha_score")),
            safe_float(item.get("tradable_score")),
        ),
        reverse=True,
    )

    return {
        "candidates_loaded": len(diagnostics),
        "eligible_shadow_entry": decision_counts.get(EntryDecision.ELIGIBLE_SHADOW_ENTRY.value, 0),
        "watch_only": decision_counts.get(EntryDecision.WATCH_ONLY.value, 0),
        "rejected": decision_counts.get(EntryDecision.REJECTED.value, 0),
        "top_rejection_reasons": dict(rejection_reasons.most_common(10)),
        "top_watch_reasons": dict(watch_reasons.most_common(10)),
        "top_watch_only_candidates": watch_candidates[:10],
        "edge_type_distribution": dict(Counter(str(row.get("edge_type") or "unknown") for row in diagnostics)),
    }


def print_diagnostics_summary(summary: dict[str, Any]) -> None:
    print(f"eligible_shadow_entry: {summary['eligible_shadow_entry']}")
    print(f"watch_only: {summary['watch_only']}")
    print(f"rejected: {summary['rejected']}")
    print(f"top_rejection_reasons: {summary['top_rejection_reasons']}")
    print(f"top_watch_reasons: {summary['top_watch_reasons']}")
    print(f"top_watch_only_candidates: {summary['top_watch_only_candidates'][:5]}")
    print(f"edge_type_distribution: {summary.get('edge_type_distribution', {})}")


def run(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    output_dir = Path(args.output_dir)
    candidates = load_candidates(runs_dir)
    candidates = select_shadow_candidates(
        candidates,
        args.max_shadow_entries,
        args.min_expected_edge,
        args.min_confidence,
        args.edge_type,
        apply_limit=False,
    )
    entry_config = EntryFilterConfig(
        min_alpha_score=args.min_alpha_score,
        min_watch_alpha_score=args.min_watch_alpha_score,
        max_ambiguity_risk=args.max_ambiguity_risk,
        min_liquidity_score=args.min_liquidity_score,
        max_spread=args.max_spread,
        watch_tier3=args.watch_tier3,
        min_confidence=args.min_confidence,
    )
    exit_config = ExitRuleConfig(
        fixed_horizon_minutes=args.fixed_horizon_minutes,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
    )
    diagnostics = build_entry_diagnostics(candidates, entry_config)
    diagnostics_summary = summarize_diagnostics(diagnostics)
    accepted_all = filter_shadow_entries(candidates, entry_config)
    accepted = accepted_all[: args.max_shadow_entries] if args.max_shadow_entries > 0 else accepted_all

    if args.dry_run:
        print("DRY RUN: shadow paper loop")
        print(f"runs_dir: {runs_dir}")
        print(f"output_dir: {output_dir}")
        print(f"candidates_loaded: {len(candidates)}")
        print(f"shadow_entries_would_generate: {len(accepted)}")
        print_diagnostics_summary(diagnostics_summary)
        return 0

    trades = build_shadow_trades(candidates, entry_config, exit_config, args.max_shadow_entries)
    paths = write_all_reports_with_diagnostics(
        output_dir,
        trades,
        verify_safety(),
        diagnostics,
        diagnostics_summary,
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
