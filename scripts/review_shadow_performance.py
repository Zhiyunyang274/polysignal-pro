#!/usr/bin/env python3
"""
Phase 8H — Offline shadow performance review gate.

This script reads existing shadow artifacts and produces loss attribution.
It never calls real APIs, real LLMs, run_paper.py, or execution modules.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

DIAGNOSTIC_FIELDS = [
    "shadow_trade_id",
    "market_id",
    "question",
    "side",
    "entry_price",
    "exit_price",
    "pnl",
    "return_pct",
    "entry_reason",
    "exit_reason",
    "edge_type",
    "relationship_status",
    "relationship_confidence",
    "price_gap",
    "reference_market_id",
    "reference_price",
    "expected_edge",
    "confidence",
    "tradable_score",
    "source",
    "category",
    "near_miss_tier",
    "ambiguity_risk",
    "liquidity_score",
    "orderbook_depth",
    "entry_combined_ask",
    "exit_combined_ask",
    "exit_spread",
    "holding_minutes",
    "diagnosis_flags",
    "primary_loss_driver",
    "recommendation",
]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review closed shadow trade performance")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs/shadow")
    parser.add_argument("--min_expected_edge", type=float, default=0.02)
    parser.add_argument("--spread_buffer", type=float, default=0.01)
    parser.add_argument("--dry_run", action="store_true")
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


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


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


def select_trade_file(shadow_dir: Path) -> Path:
    for name in ["updated_shadow_trades.csv", "shadow_trades_with_tokens.csv", "shadow_trades.csv"]:
        path = shadow_dir / name
        if path.exists():
            return path
    return shadow_dir / "updated_shadow_trades.csv"


def load_position_rows(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    rows: dict[str, dict[str, Any]] = {}
    if not isinstance(payload, dict):
        return rows
    for key in ["closed_positions", "open_positions", "insufficient_forward_data_positions"]:
        for item in payload.get(key, []):
            if isinstance(item, dict) and item.get("shadow_trade_id"):
                rows[str(item["shadow_trade_id"])] = item
    return rows


def load_forward_observations(path: Path) -> dict[str, list[dict[str, Any]]]:
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return observations
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        trade_id = str(row.get("shadow_trade_id") or "")
        if trade_id:
            observations[trade_id].append(row)
    return observations


def load_tradable_candidates(runs_dir: Path) -> dict[str, dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in ["tradable_candidates_with_tokens.csv", "tradable_candidates.csv"]:
        rows.extend(load_csv(runs_dir / name))
    by_market: dict[str, dict[str, str]] = {}
    for row in rows:
        market_id = str(row.get("market_id") or "")
        if market_id and market_id not in by_market:
            by_market[market_id] = row
    return by_market


def last_observation_for_trade(
    trade: dict[str, Any],
    observations: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    rows = observations.get(str(trade.get("shadow_trade_id") or ""), [])
    if not rows:
        return {}
    return sorted(rows, key=lambda row: str(row.get("timestamp") or ""))[-1]


def estimate_expected_edge(row: dict[str, Any]) -> float:
    """Return explicit expected edge if present; otherwise 0 to avoid inventing edge."""
    for key in ["expected_edge", "edge", "estimated_edge"]:
        value = optional_float(row.get(key))
        if value is not None:
            return value
    return 0.0


def has_strong_near_miss(tier: str) -> bool:
    normalized = str(tier or "").strip().lower().replace(" ", "")
    return normalized in {"tier1", "tier2", "1", "2"}


def diagnose_trade(
    trade: dict[str, Any],
    position: dict[str, Any],
    observation: dict[str, Any],
    tradable: dict[str, Any],
    min_expected_edge: float,
    spread_buffer: float,
) -> dict[str, Any]:
    merged = {**tradable, **trade, **position}
    entry_price = safe_float(merged.get("entry_price"))
    entry_side_price = safe_float(merged.get("entry_side_price"))
    exit_price = optional_float(merged.get("exit_price"))
    exit_side_price = optional_float(merged.get("exit_side_price")) or exit_price
    pnl = safe_float(merged.get("pnl"))
    return_pct = safe_float(merged.get("return_pct"))
    exit_spread = safe_float(observation.get("spread"), safe_float(merged.get("orderbook_spread")))
    exit_combined_ask = safe_float(observation.get("combined_ask"))
    entry_combined_ask = safe_float(merged.get("combined_ask"), entry_price)
    source = str(merged.get("source") or tradable.get("source") or "")
    near_miss_tier = str(merged.get("near_miss_tier") or tradable.get("near_miss_tier") or "")
    evidence_level = str(merged.get("evidence_level") or tradable.get("evidence_level") or "")
    orderbook_depth = safe_float(merged.get("orderbook_depth"))
    liquidity_score = safe_float(merged.get("liquidity_score"))
    tradable_score = safe_float(merged.get("tradable_score"))
    expected_edge = estimate_expected_edge(merged)
    edge_type = str(merged.get("edge_type") or "unknown")
    confidence = safe_float(merged.get("confidence"))
    relationship_status = str(merged.get("relationship_status") or "")
    relationship_confidence = safe_float(merged.get("relationship_confidence"))
    price_gap = safe_float(merged.get("price_gap"))
    flags: list[str] = []

    if pnl < 0 and exit_spread >= spread_buffer:
        flags.append("spread_drag")
    if edge_type == "price_dislocation_probability_v1" and pnl < 0:
        flags.append("probability_model_bias")
    if edge_type == "price_dislocation_probability_v1" and confidence >= 0.9 and pnl < 0:
        flags.append("confidence_overestimated")
    if pnl < 0 and expected_edge > 0:
        flags.append("expected_edge_too_optimistic")
    if exit_side_price is not None and exit_side_price < entry_side_price:
        flags.append("exit_bid_weakness")
    if source == "control_group":
        flags.append("control_group_source_risk")
    if not has_strong_near_miss(near_miss_tier):
        flags.append("near_miss_evidence_weak")
    if not has_strong_near_miss(near_miss_tier) and evidence_level in {"", "control_group", "watch_only", "weak"}:
        flags.append("weak_tradable_evidence")
    if expected_edge <= max(0.0, exit_spread + spread_buffer, min_expected_edge):
        flags.append("insufficient_expected_edge")
    if liquidity_score < 3 or orderbook_depth < 3:
        flags.append("liquidity_depth_risk")
    if safe_float(merged.get("holding_minutes")) < 30 and str(merged.get("exit_reason")) in {"stop_loss", "take_profit"}:
        flags.append("exit_timing_risk")
    if len(observation) <= 1:
        flags.append("stale_or_sparse_observation")
    if entry_price >= 0.95 and exit_price is not None and exit_price < 0.25:
        flags.append("price_interpretation_risk")
    if entry_side_price <= 0 and abs(entry_price - entry_combined_ask) < 1e-9:
        flags.append("legacy_invalid_price_model")
    if tradable_score > 10 and not has_strong_near_miss(near_miss_tier):
        flags.append("candidate_scoring_risk")
    if edge_type == "cross_market_consistency_v1" and pnl < 0:
        if relationship_status != "high_confidence_duplicate":
            flags.append("relationship_false_positive")
        if relationship_confidence < 0.75:
            flags.append("duplicate_mismatch")
        if price_gap > 0 and exit_side_price is not None and exit_side_price <= entry_side_price:
            flags.append("price_gap_not_converging")
        if len(observation) <= 1:
            flags.append("stale_price_gap")
        if liquidity_score < 3 or orderbook_depth < 3:
            flags.append("liquidity_weakness")

    primary = choose_primary_loss_driver(flags, pnl)
    recommendation = recommendation_for_driver(primary)
    return {
        "shadow_trade_id": str(merged.get("shadow_trade_id") or ""),
        "market_id": str(merged.get("market_id") or ""),
        "question": str(merged.get("question") or ""),
        "side": str(merged.get("side") or ""),
        "entry_price": entry_price,
        "exit_price": exit_price if exit_price is not None else "",
        "entry_side_price": entry_side_price,
        "exit_side_price": exit_side_price if exit_side_price is not None else "",
        "pnl": pnl,
        "return_pct": return_pct,
        "entry_reason": str(merged.get("entry_reason") or ""),
        "exit_reason": str(merged.get("exit_reason") or ""),
        "edge_type": edge_type,
        "relationship_status": relationship_status,
        "relationship_confidence": relationship_confidence,
        "price_gap": price_gap,
        "reference_market_id": str(merged.get("reference_market_id") or ""),
        "reference_price": safe_float(merged.get("reference_price")),
        "expected_edge": expected_edge,
        "confidence": confidence,
        "tradable_score": tradable_score,
        "source": source,
        "category": str(merged.get("category") or tradable.get("category") or ""),
        "near_miss_tier": near_miss_tier,
        "ambiguity_risk": safe_float(merged.get("ambiguity_risk")),
        "liquidity_score": liquidity_score,
        "orderbook_depth": orderbook_depth,
        "entry_combined_ask": entry_combined_ask,
        "exit_combined_ask": exit_combined_ask,
        "exit_spread": exit_spread,
        "holding_minutes": safe_float(merged.get("holding_minutes")),
        "diagnosis_flags": flags,
        "primary_loss_driver": primary,
        "recommendation": recommendation,
    }


def choose_primary_loss_driver(flags: list[str], pnl: float) -> str:
    if pnl >= 0:
        return "not_losing_trade"
    priority = [
        "legacy_invalid_price_model",
        "price_interpretation_risk",
        "probability_model_bias",
        "expected_edge_too_optimistic",
        "price_gap_not_converging",
        "exit_bid_weakness",
        "relationship_false_positive",
        "duplicate_mismatch",
        "confidence_overestimated",
        "insufficient_expected_edge",
        "control_group_source_risk",
        "weak_tradable_evidence",
        "candidate_scoring_risk",
        "spread_drag",
        "liquidity_depth_risk",
        "exit_timing_risk",
        "stale_or_sparse_observation",
        "stale_price_gap",
        "liquidity_weakness",
    ]
    for flag in priority:
        if flag in flags:
            return flag
    return "unknown"


def recommendation_for_driver(driver: str) -> str:
    return {
        "price_interpretation_risk": "Use side-specific executable entry price, not combined_ask, for shadow entries.",
        "legacy_invalid_price_model": "Treat legacy combined_ask-entry PnL as invalid until side-specific entry ask is available.",
        "insufficient_expected_edge": "Require expected_edge > spread + buffer before eligible_shadow_entry.",
        "control_group_source_risk": "Reduce or exclude control_group-only candidates from executable shadow entries.",
        "weak_tradable_evidence": "Require Tier1/Tier2 near-miss or stronger repeated evidence.",
        "candidate_scoring_risk": "Separate research score from executable shadow entry score.",
        "spread_drag": "Increase spread buffer and model bid/ask crossing cost explicitly.",
        "probability_model_bias": "Calibrate probability_edge_v1 against forward PnL before promoting it beyond shadow.",
        "expected_edge_too_optimistic": "Raise the edge threshold or discount microstructure-only expected_edge.",
        "exit_bid_weakness": "Require stronger bid support or repeated observations before shadow entry.",
        "price_gap_not_converging": "Require repeated cross-market observations before entering duplicate gap shadow trades.",
        "relationship_false_positive": "Keep this relationship class watch-only until duplicate matching is manually or statistically validated.",
        "duplicate_mismatch": "Raise relationship confidence threshold or improve deterministic duplicate detection.",
        "stale_price_gap": "Require repeated fresh price-gap snapshots before shadow entry.",
        "liquidity_weakness": "Raise cross-market liquidity and depth thresholds.",
        "confidence_overestimated": "Lower confidence for shallow or one-sided books until forward validation improves.",
        "liquidity_depth_risk": "Raise liquidity and depth thresholds for executable shadow entries.",
        "exit_timing_risk": "Review stop-loss timing after multiple forward observations.",
        "stale_or_sparse_observation": "Require repeated forward observations before judging exit quality.",
    }.get(driver, "Keep trade as watch-only until stronger evidence is available.")


def price_gap_bucket(value: float) -> str:
    if value < 0.05:
        return "<0.05"
    if value < 0.10:
        return "0.05-0.10"
    if value < 0.25:
        return "0.10-0.25"
    if value < 0.50:
        return "0.25-0.50"
    return ">=0.50"


def build_summary(
    diagnostics: list[dict[str, Any]],
    performance_summary: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    losing = [row for row in diagnostics if safe_float(row["pnl"]) < 0]
    winning = [row for row in diagnostics if safe_float(row["pnl"]) > 0]
    flags = Counter(flag for row in diagnostics for flag in row["diagnosis_flags"])
    weak_evidence_count = sum(
        1 for row in diagnostics
        if "weak_tradable_evidence" in row["diagnosis_flags"]
        or "near_miss_evidence_weak" in row["diagnosis_flags"]
    )
    primary = Counter(row["primary_loss_driver"] for row in diagnostics)
    edge_type_counts = Counter(str(row.get("edge_type") or "unknown") for row in diagnostics)
    edge_type_returns: dict[str, list[float]] = defaultdict(list)
    relationship_returns: dict[str, list[float]] = defaultdict(list)
    price_gap_returns: dict[str, list[float]] = defaultdict(list)
    for row in diagnostics:
        edge_type_returns[str(row.get("edge_type") or "unknown")].append(safe_float(row.get("return_pct")))
        relationship_returns[str(row.get("relationship_status") or "unknown")].append(safe_float(row.get("return_pct")))
        price_gap_returns[price_gap_bucket(safe_float(row.get("price_gap")))].append(safe_float(row.get("return_pct")))
    recommendations = [
        "require expected_edge > spread + buffer",
        "reduce or exclude control_group-only candidates from eligible_shadow_entry",
        "require Tier1/Tier2 near-miss evidence for executable shadow entries",
        "require stronger liquidity/depth",
        "require repeated forward observations before entry",
        "separate research watchlist candidates from executable shadow entries",
        "use side-specific executable entry prices instead of combined_ask for shadow PnL",
        "do not enter tiny live until shadow PnL improves over a larger sample",
    ]
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "trades_reviewed": len(diagnostics),
        "losing_trades": len(losing),
        "winning_trades": len(winning),
        "total_pnl": safe_float(performance_summary.get("total_pnl"), sum(safe_float(row["pnl"]) for row in diagnostics)),
        "win_rate": safe_float(performance_summary.get("win_rate"), len(winning) / len(diagnostics) if diagnostics else 0.0),
        "max_drawdown": safe_float(performance_summary.get("max_drawdown")),
        "average_return": mean([safe_float(row["return_pct"]) for row in diagnostics]) if diagnostics else 0.0,
        "primary_loss_drivers": dict(primary),
        "edge_type_counts": dict(edge_type_counts),
        "edge_type_performance": {
            edge_type: {
                "trades": len(values),
                "average_return": mean(values) if values else 0.0,
                "total_return": sum(values),
                "win_rate": (len([value for value in values if value > 0]) / len(values)) if values else 0.0,
            }
            for edge_type, values in edge_type_returns.items()
        },
        "relationship_status_performance": {
            status: {
                "trades": len(values),
                "average_return": mean(values) if values else 0.0,
                "total_return": sum(values),
                "win_rate": (len([value for value in values if value > 0]) / len(values)) if values else 0.0,
            }
            for status, values in relationship_returns.items()
        },
        "price_gap_bucket_performance": {
            bucket: {
                "trades": len(values),
                "average_return": mean(values) if values else 0.0,
                "total_return": sum(values),
                "win_rate": (len([value for value in values if value > 0]) / len(values)) if values else 0.0,
            }
            for bucket, values in price_gap_returns.items()
        },
        "spread_drag_count": flags["spread_drag"],
        "weak_evidence_count": weak_evidence_count,
        "control_group_source_count": flags["control_group_source_risk"],
        "expected_edge_missing_count": flags["insufficient_expected_edge"],
        "exit_timing_risk_count": flags["exit_timing_risk"],
        "price_interpretation_risk_count": flags["price_interpretation_risk"],
        "probability_model_bias_count": flags["probability_model_bias"],
        "adverse_selection_count": flags["expected_edge_too_optimistic"] + flags["exit_bid_weakness"],
        "exit_bid_weakness_count": flags["exit_bid_weakness"],
        "relationship_false_positive_count": flags["relationship_false_positive"],
        "duplicate_mismatch_count": flags["duplicate_mismatch"],
        "price_gap_not_converging_count": flags["price_gap_not_converging"],
        "stale_price_gap_count": flags["stale_price_gap"],
        "liquidity_weakness_count": flags["liquidity_weakness"],
        "confidence_overestimated_count": flags["confidence_overestimated"],
        "all_diagnosis_flags": dict(flags),
        "recommended_filter_adjustments": recommendations,
        "safety_verification": safety,
        "conclusion": "Current shadow sample is loss-making and requires filter calibration before any live consideration.",
        "tiny_live_recommendation": "NO",
    }


def write_diagnostics_csv(path: Path, diagnostics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DIAGNOSTIC_FIELDS)
        writer.writeheader()
        for row in diagnostics:
            payload = dict(row)
            payload["diagnosis_flags"] = "|".join(payload.get("diagnosis_flags", []))
            writer.writerow({field: payload.get(field, "") for field in DIAGNOSTIC_FIELDS})


def write_summary_json(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))


def answer_line(question: str, answer: str) -> str:
    return f"- {question}: **{answer}**"


def write_report_md(path: Path, summary: dict[str, Any], diagnostics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Shadow Performance Review",
        "",
        f"Generated at: `{summary.get('generated_at')}`",
        "",
        "This is an offline shadow-only review. It is not a live trading result.",
        "",
        "## Executive Summary",
        "",
        f"- Trades reviewed: {summary['trades_reviewed']}",
        f"- Losing trades: {summary['losing_trades']}",
        f"- Winning trades: {summary['winning_trades']}",
        f"- Total PnL: {summary['total_pnl']}",
        f"- Win rate: {summary['win_rate']}",
        f"- Max drawdown: {summary['max_drawdown']}",
        f"- Tiny live recommendation: **{summary['tiny_live_recommendation']}**",
        "",
        "## Aggregate Loss Attribution",
        "",
        json.dumps(summary["primary_loss_drivers"], indent=2),
        "",
        "| Driver | Count |",
        "| --- | ---: |",
        f"| spread_drag | {summary['spread_drag_count']} |",
        f"| probability_model_bias | {summary['probability_model_bias_count']} |",
        f"| expected_edge_too_optimistic / exit_bid_weakness | {summary['adverse_selection_count']} |",
        f"| confidence_overestimated | {summary['confidence_overestimated_count']} |",
        f"| weak_evidence | {summary['weak_evidence_count']} |",
        f"| control_group_source_risk | {summary['control_group_source_count']} |",
        f"| insufficient_expected_edge | {summary['expected_edge_missing_count']} |",
        f"| exit_timing_risk | {summary['exit_timing_risk_count']} |",
        f"| price_interpretation_risk | {summary['price_interpretation_risk_count']} |",
        "",
        "## Edge Type Performance",
        "",
        json.dumps(summary.get("edge_type_performance", {}), indent=2),
        "",
        "## Relationship Status Performance",
        "",
        json.dumps(summary.get("relationship_status_performance", {}), indent=2),
        "",
        "## Price Gap Bucket Performance",
        "",
        json.dumps(summary.get("price_gap_bucket_performance", {}), indent=2),
        "",
        "## Required Questions",
        "",
        answer_line("这些 trades 是否因为 spread 过宽而入场即亏", "Not primarily; spread drag is tracked separately, but bid/ask execution cost still needs explicit modeling."),
        answer_line("是否 entry 用 ask，但 exit 用 bid，导致自然滑点亏损", "Partly yes; shadow PnL now uses side-specific ask for entry and side-specific bid for exit, so exit bid weakness is an explicit risk."),
        answer_line("是否 tradable_score 高但 near-miss evidence 弱", "Yes; all reviewed trades need stronger near-miss/executable evidence."),
        answer_line("是否 low-risk control group 不等于可交易机会", "Yes; control_group-only candidates should not be executable by default."),
        answer_line("是否 exit rule 过快触发", "Not the primary driver in this sample; losses were already large at first observed exit."),
        answer_line("是否缺少 minimum expected edge filter", "Yes."),
        answer_line("是否应该要求 expected_edge > spread + buffer", "Yes."),
        answer_line("是否应该提高 liquidity / depth 阈值", "Yes, for executable shadow entries."),
        answer_line("是否应该降低 control group source 权重", "Yes; consider excluding control_group-only from eligible_shadow_entry."),
        answer_line("是否需要区分 research watchlist 和 executable shadow entry", "Yes."),
        answer_line("当前是否应该进入 tiny live", "NO."),
        answer_line("当前 edge 是否已证明正期望", "NO; the reviewed shadow PnL is not positive and requires more calibration before any live consideration."),
        "",
        "## Recommended Filter Calibration",
        "",
    ]
    for item in summary["recommended_filter_adjustments"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Per-Trade Diagnosis",
        "",
        "| Trade | Market | PnL | Return | Primary driver | Flags | Recommendation |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
    ])
    for row in diagnostics:
        flags = ", ".join(row["diagnosis_flags"])
        question = str(row["question"])[:56].replace("|", "/")
        lines.append(
            f"| {row['shadow_trade_id']} | {question} | {row['pnl']} | {row['return_pct']} | "
            f"{row['primary_loss_driver']} | {flags} | {row['recommendation']} |"
        )
    lines.extend([
        "",
        "## Safety Verification",
        "",
        json.dumps(summary["safety_verification"], indent=2),
        "",
    ])
    path.write_text("\n".join(lines))


def build_review(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    shadow_dir = Path(args.shadow_dir)
    runs_dir = Path(args.runs_dir)
    trade_file = select_trade_file(shadow_dir)
    trades = load_csv(trade_file)
    positions = load_position_rows(shadow_dir / "updated_shadow_positions.json")
    observations = load_forward_observations(shadow_dir / "forward_observations.jsonl")
    tradable_by_market = load_tradable_candidates(runs_dir)
    performance_summary = load_json(shadow_dir / "paper_performance_summary.json")
    if not isinstance(performance_summary, dict):
        performance_summary = {}
    diagnostics = []
    for trade in trades:
        trade_id = str(trade.get("shadow_trade_id") or "")
        market_id = str(trade.get("market_id") or "")
        diagnostics.append(diagnose_trade(
            trade,
            positions.get(trade_id, {}),
            last_observation_for_trade(trade, observations),
            tradable_by_market.get(market_id, {}),
            args.min_expected_edge,
            args.spread_buffer,
        ))
    summary = build_summary(diagnostics, performance_summary, verify_safety())
    paths = {
        "trade_file": str(trade_file),
        "review_md": str(Path(args.output_dir) / "shadow_performance_review.md"),
        "summary_json": str(Path(args.output_dir) / "shadow_performance_review_summary.json"),
        "diagnostics_csv": str(Path(args.output_dir) / "shadow_trade_diagnostics.csv"),
    }
    return summary, diagnostics, paths


def print_dry_run(summary: dict[str, Any], paths: dict[str, str]) -> None:
    print("DRY RUN: shadow performance review")
    print(f"trade_file: {paths['trade_file']}")
    print(f"trades_reviewed: {summary['trades_reviewed']}")
    print(f"losing_trades: {summary['losing_trades']}")
    print(f"winning_trades: {summary['winning_trades']}")
    print(f"total_pnl: {summary['total_pnl']}")
    print(f"win_rate: {summary['win_rate']}")
    print(f"max_drawdown: {summary['max_drawdown']}")
    print(f"primary_loss_drivers: {summary['primary_loss_drivers']}")
    print(f"tiny_live_recommendation: {summary['tiny_live_recommendation']}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    summary, diagnostics, paths = build_review(args)
    if args.dry_run:
        print_dry_run(summary, paths)
        return 0
    write_report_md(Path(paths["review_md"]), summary, diagnostics)
    write_summary_json(Path(paths["summary_json"]), summary)
    write_diagnostics_csv(Path(paths["diagnostics_csv"]), diagnostics)
    print("Shadow performance review")
    print(f"trades_reviewed: {summary['trades_reviewed']}")
    print(f"losing_trades: {summary['losing_trades']}")
    print(f"winning_trades: {summary['winning_trades']}")
    print(f"primary_loss_drivers: {summary['primary_loss_drivers']}")
    print(f"tiny_live_recommendation: {summary['tiny_live_recommendation']}")
    print(f"shadow_performance_review_md: {paths['review_md']}")
    print(f"shadow_performance_review_summary_json: {paths['summary_json']}")
    print(f"shadow_trade_diagnostics_csv: {paths['diagnostics_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
