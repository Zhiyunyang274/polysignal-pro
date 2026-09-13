#!/usr/bin/env python3
"""Trading MVP Step 9E — offline cross-market convergence dataset analysis.

This analyzer reads accumulated read-only convergence observations and
calculates per-pair gap time-series features. It does not call APIs, LLMs,
run_paper.py, or any execution path.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from polysignal.shadow.cross_market_convergence import CrossMarketConvergenceObservation
from scripts.discover_executable_edges import verify_safety

FEATURE_FIELDS = [
    "group_id",
    "market_id",
    "reference_market_id",
    "question",
    "reference_question",
    "side",
    "relationship_status",
    "relationship_confidence",
    "observation_count",
    "initial_gap",
    "final_gap",
    "gap_change",
    "gap_change_pct",
    "min_gap",
    "max_gap",
    "gap_volatility",
    "convergence_score",
    "avg_spread",
    "avg_depth",
    "avg_liquidity",
    "time_to_convergence_minutes",
    "stable_gap_count",
    "widening_gap_count",
    "shrinking_gap_count",
    "convergence_status",
    "future_recommendation",
    "future_shadow_candidate",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze cross-market convergence observations")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--min_observations", type=int, default=5)
    parser.add_argument("--min_convergence_score", type=float, default=0.5)
    parser.add_argument("--stable_gap_epsilon", type=float, default=0.001)
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def load_observations(path: Path) -> list[CrossMarketConvergenceObservation]:
    if not path.exists():
        return []
    observations: list[CrossMarketConvergenceObservation] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            observations.append(CrossMarketConvergenceObservation.from_dict(payload))
    return observations


def _pair_key(obs: CrossMarketConvergenceObservation) -> tuple[str, str, str, str]:
    return (obs.group_id, obs.market_id, obs.reference_market_id, obs.side.upper())


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _transition_counts(gaps: list[float], epsilon: float) -> tuple[int, int, int]:
    stable = widening = shrinking = 0
    for prev, cur in zip(gaps, gaps[1:], strict=False):
        delta = cur - prev
        if abs(delta) <= epsilon:
            stable += 1
        elif delta > 0:
            widening += 1
        else:
            shrinking += 1
    return stable, widening, shrinking


def compute_pair_features(
    observations: list[CrossMarketConvergenceObservation],
    min_observations: int = 5,
    min_convergence_score: float = 0.5,
    stable_gap_epsilon: float = 0.001,
) -> dict[str, Any]:
    ordered = sorted(observations, key=lambda obs: (obs.observation_index, obs.timestamp))
    valid = [obs for obs in ordered if not obs.stale and not obs.error]
    basis = valid or ordered
    first = basis[0]
    gaps = [obs.price_gap for obs in basis]
    initial = gaps[0]
    final = gaps[-1]
    gap_change = final - initial
    gap_change_pct = gap_change / initial if initial else 0.0
    min_gap = min(gaps) if gaps else 0.0
    max_gap = max(gaps) if gaps else 0.0
    gap_volatility = pstdev(gaps) if len(gaps) > 1 else 0.0
    convergence_score = max(0.0, (initial - final) / initial) if initial > 0 else 0.0
    stable_count, widening_count, shrinking_count = _transition_counts(gaps, stable_gap_epsilon)

    start_time = _parse_time(basis[0].timestamp)
    end_time = _parse_time(basis[-1].timestamp)
    time_to_convergence = 0.0
    if start_time and end_time:
        time_to_convergence = (end_time - start_time).total_seconds() / 60.0

    if len(valid) < min_observations:
        status = "insufficient_observations"
        recommendation = "watch_only"
        future_shadow = False
    elif widening_count > shrinking_count and final >= initial:
        status = "widening_gap"
        recommendation = "long_term_watch_or_reject"
        future_shadow = False
    elif abs(gap_change) <= stable_gap_epsilon:
        status = "stable_gap"
        recommendation = "watch_only"
        future_shadow = False
    elif final < initial and convergence_score >= min_convergence_score:
        status = "converging_gap"
        recommendation = "future_shadow_candidate"
        future_shadow = True
    elif final < initial:
        status = "weak_convergence"
        recommendation = "watch_only"
        future_shadow = False
    else:
        status = "non_converging_gap"
        recommendation = "watch_only"
        future_shadow = False

    return {
        "group_id": first.group_id,
        "market_id": first.market_id,
        "reference_market_id": first.reference_market_id,
        "question": first.question,
        "reference_question": first.reference_question,
        "side": first.side,
        "relationship_status": first.relationship_status,
        "relationship_confidence": first.relationship_confidence,
        "observation_count": len(valid),
        "initial_gap": initial,
        "final_gap": final,
        "gap_change": gap_change,
        "gap_change_pct": gap_change_pct,
        "min_gap": min_gap,
        "max_gap": max_gap,
        "gap_volatility": gap_volatility,
        "convergence_score": convergence_score,
        "avg_spread": mean([obs.spread for obs in basis]) if basis else 0.0,
        "avg_depth": mean([obs.depth for obs in basis]) if basis else 0.0,
        "avg_liquidity": mean([obs.liquidity for obs in basis]) if basis else 0.0,
        "time_to_convergence_minutes": time_to_convergence,
        "stable_gap_count": stable_count,
        "widening_gap_count": widening_count,
        "shrinking_gap_count": shrinking_count,
        "convergence_status": status,
        "future_recommendation": recommendation,
        "future_shadow_candidate": future_shadow,
    }


def build_features(
    observations: list[CrossMarketConvergenceObservation],
    min_observations: int,
    min_convergence_score: float,
    stable_gap_epsilon: float,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[CrossMarketConvergenceObservation]] = defaultdict(list)
    for obs in observations:
        grouped[_pair_key(obs)].append(obs)
    return [
        compute_pair_features(rows, min_observations, min_convergence_score, stable_gap_epsilon)
        for rows in grouped.values()
    ]


def build_summary(features: list[dict[str, Any]], total_observations: int) -> dict[str, Any]:
    gap_changes = [float(row.get("gap_change") or 0.0) for row in features]
    volatilities = [float(row.get("gap_volatility") or 0.0) for row in features]
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "groups_analyzed": len({row.get("group_id") for row in features if row.get("group_id")}),
        "pairs_analyzed": len(features),
        "total_observations": total_observations,
        "converging_pairs_count": sum(1 for row in features if row.get("convergence_status") == "converging_gap"),
        "non_converging_pairs_count": sum(1 for row in features if row.get("convergence_status") in {"non_converging_gap", "stable_gap", "weak_convergence"}),
        "widening_pairs_count": sum(1 for row in features if row.get("convergence_status") == "widening_gap"),
        "stable_pairs_count": sum(1 for row in features if row.get("convergence_status") == "stable_gap"),
        "avg_gap_change": mean(gap_changes) if gap_changes else 0.0,
        "avg_gap_volatility": mean(volatilities) if volatilities else 0.0,
        "best_convergence_score": max([float(row.get("convergence_score") or 0.0) for row in features], default=0.0),
        "candidates_recommended_for_future_shadow": sum(1 for row in features if row.get("future_shadow_candidate") is True),
        "safety_verification": {
            **verify_safety(),
            "api_calls": False,
            "llm_calls": False,
            "shadow_trades_generated": False,
            "entry_filter_modified": False,
        },
        "tiny_live_recommendation": "NO",
    }


def write_features_csv(path: Path, features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_FIELDS)
        writer.writeheader()
        for row in features:
            writer.writerow({field: row.get(field, "") for field in FEATURE_FIELDS})


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any], features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    top = sorted(features, key=lambda row: float(row.get("convergence_score") or 0.0), reverse=True)[:10]
    lines = [
        "# Cross-Market Convergence Dataset Report",
        "",
        "This report is offline analysis of read-only observations. It does not generate shadow trades or live signals.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "groups_analyzed",
        "pairs_analyzed",
        "total_observations",
        "converging_pairs_count",
        "non_converging_pairs_count",
        "widening_pairs_count",
        "stable_pairs_count",
        "avg_gap_change",
        "avg_gap_volatility",
        "best_convergence_score",
        "candidates_recommended_for_future_shadow",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        "## Top Convergence Scores",
        "",
        "| Market | Reference | Score | Status | Recommendation |",
        "| --- | --- | ---: | --- | --- |",
    ])
    for row in top:
        lines.append(
            f"| {row.get('market_id')} | {row.get('reference_market_id')} | "
            f"{row.get('convergence_score')} | {row.get('convergence_status')} | {row.get('future_recommendation')} |"
        )
    lines.extend([
        "",
        "## Gate Policy",
        "",
        "- price_gap alone is not a trading signal.",
        "- stable gaps remain watch_only.",
        "- widening gaps remain watch_only or reject candidates.",
        "- future_shadow_candidate is not live permission.",
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


def analyze_dataset(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runs_dir = Path(args.runs_dir)
    observations = load_observations(runs_dir / "cross_market_convergence_observations.jsonl")
    features = build_features(
        observations,
        min_observations=args.min_observations,
        min_convergence_score=args.min_convergence_score,
        stable_gap_epsilon=args.stable_gap_epsilon,
    )
    summary = build_summary(features, len(observations))
    return features, summary


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: cross-market convergence dataset analysis" if dry_run else "Cross-market convergence dataset analysis")
    for key in [
        "total_observations",
        "groups_analyzed",
        "pairs_analyzed",
        "converging_pairs_count",
        "non_converging_pairs_count",
        "widening_pairs_count",
        "stable_pairs_count",
        "avg_gap_change",
        "avg_gap_volatility",
        "best_convergence_score",
        "candidates_recommended_for_future_shadow",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    features, summary = analyze_dataset(args)
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    write_features_csv(output_dir / "cross_market_convergence_features.csv", features)
    write_summary(output_dir / "cross_market_convergence_dataset_summary.json", summary)
    write_report(output_dir / "cross_market_convergence_dataset_report.md", summary, features)
    print(f"cross_market_convergence_features_csv: {output_dir / 'cross_market_convergence_features.csv'}")
    print(f"cross_market_convergence_dataset_summary_json: {output_dir / 'cross_market_convergence_dataset_summary.json'}")
    print(f"cross_market_convergence_dataset_report_md: {output_dir / 'cross_market_convergence_dataset_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
