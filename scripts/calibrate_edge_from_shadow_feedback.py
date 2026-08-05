#!/usr/bin/env python3
"""
Trading MVP Step 7 — Expected edge feedback calibration.

This script is offline-only. It reads shadow trade artifacts and multi-edge
candidate files, joins predicted edge features with realized shadow PnL, and
emits calibration diagnostics. It never calls APIs, LLMs, run_paper.py, or any
execution modules.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

DATASET_FIELDS = [
    "shadow_trade_id",
    "market_id",
    "question",
    "edge_type",
    "side",
    "expected_edge",
    "calibrated_expected_edge",
    "confidence",
    "entry_price",
    "exit_price",
    "yes_spread",
    "no_spread",
    "max_spread",
    "depth",
    "liquidity",
    "exit_bid_penalty",
    "adverse_selection_penalty",
    "liquidity_penalty",
    "combined_ask",
    "bid_support",
    "orderbook_imbalance",
    "holding_minutes",
    "realized_return",
    "pnl",
    "is_win",
    "is_closed",
    "loss_patterns",
]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate edge model from closed shadow PnL")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--high_confidence_threshold", type=float, default=0.8)
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
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
    except OSError:
        return {}
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
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


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


def pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denom_x = math.sqrt(sum(x * x for x in dx))
    denom_y = math.sqrt(sum(y * y for y in dy))
    if denom_x == 0 or denom_y == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / (denom_x * denom_y)


def candidate_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("market_id") or ""),
        str(row.get("edge_type") or ""),
        str(row.get("side") or "").upper(),
    )


def load_candidates(runs_dir: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    index: dict[tuple[str, str, str], dict[str, str]] = {}
    for name in ["multi_edge_candidates.csv", "multi_edge_candidates_v2.csv"]:
        for row in load_csv(runs_dir / name):
            key = candidate_key(row)
            if key[0] and key not in index:
                index[key] = row
    return index


def load_trade_rows(shadow_dir: Path) -> list[dict[str, str]]:
    rows_by_id: dict[str, dict[str, str]] = {}
    for name in ["shadow_trades.csv", "updated_shadow_trades.csv"]:
        for row in load_csv(shadow_dir / name):
            trade_id = str(row.get("shadow_trade_id") or "")
            if trade_id:
                rows_by_id[trade_id] = row
    return list(rows_by_id.values())


def load_diagnostics(shadow_dir: Path) -> dict[str, dict[str, str]]:
    return {
        str(row.get("shadow_trade_id") or ""): row
        for row in load_csv(shadow_dir / "shadow_trade_diagnostics.csv")
        if row.get("shadow_trade_id")
    }


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


def extract_penalty_from_evidence(evidence: str, name: str) -> float:
    prefix = f"{name}="
    for part in str(evidence or "").split("|"):
        if part.startswith(prefix):
            return safe_float(part.split("=", 1)[1], 0.0)
    return 0.0


def merge_trade_with_candidate(
    trade: dict[str, str],
    candidate: dict[str, str],
    diagnostic: dict[str, str],
    observation: dict[str, Any],
) -> dict[str, Any]:
    merged = {**candidate, **trade}
    evidence = str(merged.get("evidence") or "")
    yes_spread = max(0.0, safe_float(merged.get("entry_yes_best_ask")) - safe_float(merged.get("entry_yes_best_bid")))
    no_spread = max(0.0, safe_float(merged.get("entry_no_best_ask")) - safe_float(merged.get("entry_no_best_bid")))
    max_spread = max(
        yes_spread,
        no_spread,
        safe_float(merged.get("max_spread")),
        safe_float(merged.get("spread")),
        safe_float(merged.get("orderbook_spread")),
    )
    status = str(merged.get("status") or "")
    realized_return = safe_float(merged.get("return_pct"))
    pnl = safe_float(merged.get("pnl"))
    is_closed = status == "closed"
    is_win = is_closed and realized_return > 0
    calibrated_expected_edge = safe_float(
        merged.get("calibrated_expected_edge"),
        safe_float(merged.get("expected_edge")),
    )
    row: dict[str, Any] = {
        "shadow_trade_id": str(merged.get("shadow_trade_id") or ""),
        "market_id": str(merged.get("market_id") or ""),
        "question": str(merged.get("question") or ""),
        "edge_type": str(merged.get("edge_type") or ""),
        "side": str(merged.get("side") or "").upper(),
        "expected_edge": safe_float(merged.get("expected_edge")),
        "calibrated_expected_edge": calibrated_expected_edge,
        "confidence": safe_float(merged.get("confidence")),
        "entry_price": safe_float(merged.get("entry_side_price"), safe_float(merged.get("entry_price"))),
        "exit_price": safe_float(merged.get("exit_side_price"), safe_float(merged.get("exit_price"))),
        "yes_spread": yes_spread,
        "no_spread": no_spread,
        "max_spread": max_spread,
        "depth": safe_float(merged.get("depth"), safe_float(merged.get("orderbook_depth"))),
        "liquidity": safe_float(merged.get("liquidity_score")),
        "exit_bid_penalty": safe_float(merged.get("exit_bid_penalty"), extract_penalty_from_evidence(evidence, "exit_bid_penalty")),
        "adverse_selection_penalty": safe_float(
            merged.get("adverse_selection_penalty"),
            extract_penalty_from_evidence(evidence, "adverse_selection_penalty"),
        ),
        "liquidity_penalty": safe_float(merged.get("liquidity_penalty"), extract_penalty_from_evidence(evidence, "liquidity_penalty")),
        "combined_ask": safe_float(merged.get("combined_ask")),
        "bid_support": safe_float(merged.get("bid_support")),
        "orderbook_imbalance": safe_float(merged.get("orderbook_imbalance")),
        "holding_minutes": safe_float(merged.get("holding_minutes")),
        "realized_return": realized_return,
        "pnl": pnl,
        "is_win": is_win,
        "is_closed": is_closed,
        "diagnosis_flags": str(diagnostic.get("diagnosis_flags") or ""),
        "primary_loss_driver": str(diagnostic.get("primary_loss_driver") or ""),
        "exit_reason": str(merged.get("exit_reason") or ""),
        "observation_count": len(observation) if isinstance(observation, list) else 0,
    }
    row["loss_patterns"] = "|".join(loss_patterns(row))
    return row


def loss_patterns(row: dict[str, Any]) -> list[str]:
    if not row.get("is_closed") or row.get("realized_return", 0.0) >= 0:
        return ["not_losing_trade"]
    patterns: list[str] = []
    if row["expected_edge"] > 0:
        patterns.append("expected_edge_false_positive")
    if row["confidence"] >= 0.8:
        patterns.append("high_confidence_loss")
    if row["max_spread"] > 0.03:
        patterns.append("wide_spread_loss")
    if row["depth"] and row["depth"] < 10:
        patterns.append("shallow_depth_loss")
    if row["liquidity"] and row["liquidity"] < 50:
        patterns.append("low_liquidity_loss")
    if row["exit_price"] < row["entry_price"]:
        patterns.append("exit_bid_weakness")
    if row["exit_bid_penalty"] < abs(row["realized_return"]):
        patterns.append("exit_bid_penalty_underestimated")
    if row["adverse_selection_penalty"] < abs(row["realized_return"]):
        patterns.append("adverse_selection_underestimated")
    if "probability" in row["edge_type"]:
        patterns.append("microstructure_probability_loss")
    if row["holding_minutes"] <= 1 and row.get("exit_reason") in {"stop_loss", "take_profit", "fixed_horizon"}:
        patterns.append("single_snapshot_exit_risk")
    return patterns or ["unclassified_loss"]


def build_dataset(runs_dir: Path, shadow_dir: Path) -> list[dict[str, Any]]:
    candidates = load_candidates(runs_dir)
    diagnostics = load_diagnostics(shadow_dir)
    observations = load_forward_observations(shadow_dir / "forward_observations.jsonl")
    dataset: list[dict[str, Any]] = []
    for trade in load_trade_rows(shadow_dir):
        key = candidate_key(trade)
        candidate = candidates.get(key, {})
        trade_id = str(trade.get("shadow_trade_id") or "")
        dataset.append(
            merge_trade_with_candidate(
                trade,
                candidate,
                diagnostics.get(trade_id, {}),
                observations.get(trade_id, []),
            )
        )
    return dataset


def top_loss_patterns(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in dataset:
        if row.get("realized_return", 0.0) < 0:
            counter.update(str(row.get("loss_patterns") or "").split("|"))
    return [{"pattern": pattern, "count": count} for pattern, count in counter.most_common(10)]


def grouped_edge_performance(dataset: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dataset:
        groups[str(row.get("edge_type") or "unknown")].append(row)
    result: dict[str, dict[str, Any]] = {}
    for edge_type, rows in groups.items():
        closed = [row for row in rows if row.get("is_closed")]
        returns = [safe_float(row.get("realized_return")) for row in closed]
        wins = [row for row in closed if row.get("is_win")]
        result[edge_type] = {
            "trades": len(rows),
            "closed_trades": len(closed),
            "win_rate": (len(wins) / len(closed)) if closed else 0.0,
            "average_return": mean(returns) if returns else 0.0,
        }
    return result


def recommended_v3_filters(summary: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if summary["trades_analyzed"] < 30:
        recommendations.append("sample_size_insufficient_collect_more_shadow_data_before_live")
    if summary["expected_edge_realized_return_correlation"] is None or summary["expected_edge_realized_return_correlation"] <= 0:
        recommendations.append("quarantine_probability_edge_executable_to_watch_only_until_edge_correlation_is_positive")
    if summary["confidence_win_correlation"] is None or summary["confidence_win_correlation"] <= 0:
        recommendations.append("redesign_confidence_model_do_not_use_current_confidence_as_execution_gate")
    if summary["high_confidence_loss_count"] > 0:
        recommendations.append("lower_confidence_ceiling_or_penalize_high_confidence_single_snapshot_edges")
    patterns = {item["pattern"]: item["count"] for item in summary["top_loss_patterns"]}
    if patterns.get("exit_bid_weakness") or patterns.get("exit_bid_penalty_underestimated"):
        recommendations.append("increase_exit_bid_penalty_and_require_stronger_exit_bid_support")
    if patterns.get("adverse_selection_underestimated"):
        recommendations.append("increase_adverse_selection_penalty_for_microstructure_probability_edges")
    if patterns.get("single_snapshot_exit_risk"):
        recommendations.append("require_repeated_forward_observations_before_probability_edge_shadow_entry")
    if patterns.get("microstructure_probability_loss"):
        recommendations.append("keep_microstructure_probability_edges_watch_only_until_positive_shadow_pnl")
    recommendations.append("tiny_live_recommendation_NO")
    return recommendations


def summarize(dataset: list[dict[str, Any]], high_confidence_threshold: float) -> dict[str, Any]:
    closed = [row for row in dataset if row.get("is_closed")]
    returns = [safe_float(row.get("realized_return")) for row in closed]
    wins = [row for row in closed if row.get("is_win")]
    expected_edges = [safe_float(row.get("expected_edge")) for row in closed]
    calibrated_edges = [safe_float(row.get("calibrated_expected_edge")) for row in closed]
    confidence = [safe_float(row.get("confidence")) for row in closed]
    win_flags = [1.0 if row.get("is_win") else 0.0 for row in closed]
    false_positive_count = sum(1 for row in closed if safe_float(row.get("expected_edge")) > 0 and safe_float(row.get("realized_return")) < 0)
    high_confidence_loss_count = sum(
        1
        for row in closed
        if safe_float(row.get("confidence")) >= high_confidence_threshold and safe_float(row.get("realized_return")) < 0
    )
    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "trades_analyzed": len(closed),
        "edge_types_analyzed": sorted({str(row.get("edge_type") or "unknown") for row in closed}),
        "overall_win_rate": (len(wins) / len(closed)) if closed else 0.0,
        "overall_average_return": mean(returns) if returns else 0.0,
        "expected_edge_realized_return_correlation": pearson(expected_edges, returns),
        "calibrated_edge_realized_return_correlation": pearson(calibrated_edges, returns),
        "confidence_win_correlation": pearson(confidence, win_flags),
        "false_positive_count": false_positive_count,
        "high_confidence_loss_count": high_confidence_loss_count,
        "top_loss_patterns": top_loss_patterns(closed),
        "edge_type_performance": grouped_edge_performance(dataset),
        "tiny_live_recommendation": "NO",
        "safety_verification": verify_safety(),
    }
    summary["recommended_v3_filters"] = recommended_v3_filters(summary)
    return summary


def format_corr(value: Optional[float]) -> str:
    return "insufficient_data" if value is None else f"{value:.6f}"


def generate_report(summary: dict[str, Any]) -> str:
    expected_corr = summary.get("expected_edge_realized_return_correlation")
    confidence_corr = summary.get("confidence_win_correlation")
    positive_edge_corr = expected_corr is not None and expected_corr > 0
    positive_conf_corr = confidence_corr is not None and confidence_corr > 0
    lines = [
        "# Edge Feedback Calibration Report",
        "",
        "Shadow feedback is hypothetical and not a live trading result.",
        "",
        "## Summary",
        "",
        f"- trades_analyzed: {summary['trades_analyzed']}",
        f"- edge_types_analyzed: {', '.join(summary['edge_types_analyzed']) or 'none'}",
        f"- overall_win_rate: {summary['overall_win_rate']}",
        f"- overall_average_return: {summary['overall_average_return']}",
        f"- expected_edge_realized_return_correlation: {format_corr(expected_corr)}",
        f"- confidence_win_correlation: {format_corr(confidence_corr)}",
        f"- false_positive_count: {summary['false_positive_count']}",
        f"- high_confidence_loss_count: {summary['high_confidence_loss_count']}",
        "",
        "## Required Answers",
        "",
        f"- expected_edge and realized_return positive correlation: {'YES' if positive_edge_corr else 'NO'}",
        f"- confidence and win/loss positive correlation: {'YES' if positive_conf_corr else 'NO'}",
        f"- high confidence losing trades observed: {'YES' if summary['high_confidence_loss_count'] > 0 else 'NO'}",
        "- systematic loss patterns: "
        + (", ".join(f"{item['pattern']}={item['count']}" for item in summary["top_loss_patterns"]) or "none"),
        "- wide spread / weak bid / shallow depth still under-penalized: "
        + ("YES" if any(item["pattern"] in {"exit_bid_weakness", "exit_bid_penalty_underestimated", "wide_spread_loss", "shallow_depth_loss"} for item in summary["top_loss_patterns"]) else "NO"),
        "- side-specific exit bid risk underestimated: "
        + ("YES" if any(item["pattern"] in {"exit_bid_weakness", "exit_bid_penalty_underestimated"} for item in summary["top_loss_patterns"]) else "NO"),
        "- microstructure-only probability edge reliability: NOT PROVEN",
        "- v3 should exclude or quarantine: high-confidence single-snapshot probability edges, weak-exit-bid edges, and probability edges without positive realized feedback.",
        "- tiny live recommendation: NO",
        "",
        "## Recommended V3 Filters",
        "",
    ]
    lines.extend(f"- {item}" for item in summary["recommended_v3_filters"])
    lines.extend([
        "",
        "## Safety Verification",
        "",
    ])
    for key, value in summary["safety_verification"].items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DATASET_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in DATASET_FIELDS})


def run(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    shadow_dir = Path(args.shadow_dir)
    output_dir = Path(args.output_dir)
    dataset = build_dataset(runs_dir, shadow_dir)
    summary = summarize(dataset, args.high_confidence_threshold)

    if args.dry_run:
        print("DRY RUN: edge feedback calibration")
        print(f"runs_dir: {runs_dir}")
        print(f"shadow_dir: {shadow_dir}")
        print(f"trades_analyzed: {summary['trades_analyzed']}")
        print(f"edge_types_analyzed: {summary['edge_types_analyzed']}")
        print(f"overall_win_rate: {summary['overall_win_rate']}")
        print(f"overall_average_return: {summary['overall_average_return']}")
        print(f"expected_edge_realized_return_correlation: {format_corr(summary['expected_edge_realized_return_correlation'])}")
        print(f"confidence_win_correlation: {format_corr(summary['confidence_win_correlation'])}")
        print(f"false_positive_count: {summary['false_positive_count']}")
        print(f"high_confidence_loss_count: {summary['high_confidence_loss_count']}")
        print(f"tiny_live_recommendation: {summary['tiny_live_recommendation']}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / "edge_feedback_dataset.csv"
    summary_path = output_dir / "edge_feedback_calibration_summary.json"
    report_path = output_dir / "edge_feedback_calibration_report.md"
    write_csv(dataset_path, dataset)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    report_path.write_text(generate_report(summary))

    print("Edge feedback calibration")
    print(f"trades_analyzed: {summary['trades_analyzed']}")
    print(f"overall_win_rate: {summary['overall_win_rate']}")
    print(f"overall_average_return: {summary['overall_average_return']}")
    print(f"expected_edge_realized_return_correlation: {format_corr(summary['expected_edge_realized_return_correlation'])}")
    print(f"confidence_win_correlation: {format_corr(summary['confidence_win_correlation'])}")
    print(f"false_positive_count: {summary['false_positive_count']}")
    print(f"high_confidence_loss_count: {summary['high_confidence_loss_count']}")
    print(f"tiny_live_recommendation: {summary['tiny_live_recommendation']}")
    print(f"edge_feedback_dataset_csv: {dataset_path}")
    print(f"edge_feedback_calibration_summary_json: {summary_path}")
    print(f"edge_feedback_calibration_report_md: {report_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
