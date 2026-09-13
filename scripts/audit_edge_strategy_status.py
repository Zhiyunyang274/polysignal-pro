#!/usr/bin/env python3
"""Trading MVP Step 9F — offline edge strategy status audit.

This script reads prior shadow validation artifacts and produces a registry of
tested edge types. It does not call APIs, LLMs, run_paper.py, or execution code.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.discover_executable_edges import verify_safety

REGISTRY_FIELDS = [
    "edge_type",
    "tests_run",
    "trades_analyzed",
    "observations_analyzed",
    "win_rate",
    "average_return",
    "total_pnl",
    "convergence_score",
    "feedback_status",
    "recommended_status",
    "reason",
    "tiny_live_allowed",
]


NEXT_EDGE_SOURCE_COMPARISON = [
    {
        "source": "External Event-Driven Edge",
        "priority": 2,
        "pros": "May provide real informational edge from external events.",
        "cons": "Requires reliable data sources, latency handling, event parsing, and market-rule mapping.",
        "recommendation": "Promising later, but too broad for the fastest next MVP step.",
    },
    {
        "source": "Crypto Price Threshold Edge",
        "priority": 1,
        "pros": "Read-only spot prices are easy to fetch, BTC/ETH/SOL markets are common, rules are objective, and no LLM is required.",
        "cons": "Must handle barrier distance, expiry, oracle/timezone details, and close-time risk.",
        "recommendation": "Recommended for Trading MVP Step 10.",
    },
    {
        "source": "Sports Live Score Lag Edge",
        "priority": 3,
        "pros": "Real event-driven signal with possible market-lag opportunities.",
        "cons": "Needs dependable live score data, game state handling, and complex market rule interpretation.",
        "recommendation": "Defer until data-source reliability is solved.",
    },
    {
        "source": "Closing Market Convergence Edge",
        "priority": 4,
        "pros": "Uncertainty is lower near resolution.",
        "cons": "Requires strong outcome tracking, close-time guards, and resolution-risk handling.",
        "recommendation": "Useful later after lifecycle/outcome tracking is stronger.",
    },
    {
        "source": "Cross-Market Edge",
        "priority": 5,
        "pros": "Uses internal Polymarket relationships and needs no external feed.",
        "cons": "Current observations did not converge and high-confidence duplicate PnL was negative.",
        "recommendation": "Keep research/watch-only unless future data proves convergence.",
    },
    {
        "source": "Microstructure Probability Edge",
        "priority": 6,
        "pros": "Easy to compute from orderbooks.",
        "cons": "v1/v2 showed negative shadow PnL and non-predictive confidence.",
        "recommendation": "Keep quarantined; do not make executable.",
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit tested edge strategy status")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def registry_row(
    edge_type: str,
    tests_run: str,
    trades_analyzed: int = 0,
    observations_analyzed: int = 0,
    win_rate: float = 0.0,
    average_return: float = 0.0,
    total_pnl: float = 0.0,
    convergence_score: float = 0.0,
    feedback_status: str = "insufficient_data",
    recommended_status: str = "watch_only",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "edge_type": edge_type,
        "tests_run": tests_run,
        "trades_analyzed": trades_analyzed,
        "observations_analyzed": observations_analyzed,
        "win_rate": win_rate,
        "average_return": average_return,
        "total_pnl": total_pnl,
        "convergence_score": convergence_score,
        "feedback_status": feedback_status,
        "recommended_status": recommended_status,
        "reason": reason,
        "tiny_live_allowed": False,
    }


def build_registry(runs_dir: Path, shadow_dir: Path) -> list[dict[str, Any]]:
    feedback = load_json(runs_dir / "edge_feedback_calibration_summary.json")
    gate = load_json(runs_dir / "edge_feedback_gate_summary.json")
    convergence = load_json(runs_dir / "cross_market_convergence_dataset_summary.json")
    review = load_json(shadow_dir / "shadow_performance_review_summary.json")
    multi_v1 = load_json(runs_dir / "multi_edge_discovery_summary.json")
    executable = load_json(runs_dir / "executable_edge_discovery_summary.json")

    rows: list[dict[str, Any]] = []

    edge_count = int(safe_float(executable.get("edge_candidates_count")))
    combined_count = int(safe_float(multi_v1.get("combined_ask_arbitrage_count")))
    rows.append(registry_row(
        "combined_ask_arbitrage",
        tests_run="executable_edge_discovery|multi_edge_discovery",
        observations_analyzed=int(safe_float(executable.get("orderbooks_fetched")) or safe_float(multi_v1.get("orderbooks_fetched"))),
        feedback_status="rare_opportunity" if edge_count == 0 else "needs_shadow_validation",
        recommended_status="enabled",
        reason=(
            "Direct combined-ask dislocation remains logically valid, but scanned batches found "
            f"{edge_count} executable candidates from {combined_count} combined-ask observations; no positive PnL proof yet."
        ),
    ))

    gates = gate.get("feedback_gates", {}) if isinstance(gate.get("feedback_gates"), dict) else {}
    v1_gate = gates.get("price_dislocation_probability_v1", {})
    rows.append(registry_row(
        "price_dislocation_probability_v1",
        tests_run="multi_edge_discovery|feedback_gate",
        trades_analyzed=int(safe_float(v1_gate.get("trades_analyzed"))),
        win_rate=safe_float(v1_gate.get("win_rate")),
        average_return=safe_float(v1_gate.get("average_return")),
        feedback_status=str(v1_gate.get("status") or "watch_only"),
        recommended_status="quarantined",
        reason=(
            "Microstructure probability v1 produced many candidates but feedback gate shows insufficient or negative evidence; "
            "do not allow executable shadow entries."
        ),
    ))

    perf = feedback.get("edge_type_performance", {}) if isinstance(feedback.get("edge_type_performance"), dict) else {}
    v2_perf = perf.get("price_dislocation_probability_v2", {})
    v2_gate = gates.get("price_dislocation_probability_v2", {})
    rows.append(registry_row(
        "price_dislocation_probability_v2",
        tests_run="multi_edge_discovery_v2|shadow_pnl|feedback_calibration|feedback_gate",
        trades_analyzed=int(safe_float(v2_perf.get("closed_trades") or v2_gate.get("trades_analyzed"))),
        win_rate=safe_float(v2_perf.get("win_rate") or v2_gate.get("win_rate")),
        average_return=safe_float(v2_perf.get("average_return") or v2_gate.get("average_return")),
        total_pnl=safe_float(v2_perf.get("total_return")) or (
            safe_float(v2_perf.get("average_return") or v2_gate.get("average_return"))
            * int(safe_float(v2_perf.get("closed_trades") or v2_gate.get("trades_analyzed")))
        ),
        feedback_status=str(v2_gate.get("status") or "quarantined"),
        recommended_status="quarantined",
        reason=(
            "v2 is more conservative than v1 but still had negative return, negative expected_edge correlation, "
            "non-predictive confidence, high false positives, and high confidence losses."
        ),
    ))

    cross_perf = {}
    if isinstance(review.get("edge_type_performance"), dict):
        cross_perf = review["edge_type_performance"].get("cross_market_consistency_v1", {})
    rows.append(registry_row(
        "cross_market_consistency_v1",
        tests_run="cross_market_discovery|relationship_calibration|shadow_pnl_review",
        trades_analyzed=int(safe_float(cross_perf.get("trades") or review.get("trades_reviewed"))),
        win_rate=safe_float(cross_perf.get("win_rate") or review.get("win_rate")),
        average_return=safe_float(cross_perf.get("average_return") or review.get("average_return")),
        total_pnl=safe_float(cross_perf.get("total_return") or review.get("total_pnl")),
        feedback_status="negative_shadow_pnl",
        recommended_status="research_only",
        reason=(
            "High-confidence duplicate sample closed 10/10 losing; price gap did not converge and exit bid weakness was observed."
        ),
    ))

    rows.append(registry_row(
        "cross_market_convergence",
        tests_run="convergence_monitor|dataset_analysis",
        observations_analyzed=int(safe_float(convergence.get("total_observations"))),
        convergence_score=safe_float(convergence.get("best_convergence_score")),
        feedback_status="no_convergence_pattern",
        recommended_status="research_only",
        reason=(
            f"Dataset analyzed {int(safe_float(convergence.get('pairs_analyzed')))} pairs with "
            f"{int(safe_float(convergence.get('converging_pairs_count')))} converging pairs; "
            f"best score {safe_float(convergence.get('best_convergence_score')):.6f}; no future shadow candidates."
        ),
    ))

    return rows


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, list[str]] = {}
    for row in rows:
        by_status.setdefault(str(row.get("recommended_status")), []).append(str(row.get("edge_type")))
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "edge_types_reviewed": len(rows),
        "quarantined_edges": by_status.get("quarantined", []),
        "watch_only_edges": by_status.get("watch_only", []),
        "research_only_edges": by_status.get("research_only", []),
        "enabled_edges": by_status.get("enabled", []),
        "discontinued_edges": by_status.get("discontinued", []),
        "tiny_live_recommendation": "NO",
        "any_edge_supports_tiny_live": False,
        "recommended_next_edge_source": "Crypto Price Threshold Edge",
        "recommended_step_10": "Trading MVP Step 10 — Crypto Price Threshold Edge v1",
        "safety_verification": {
            **verify_safety(),
            "api_calls": False,
            "llm_calls": False,
            "shadow_trades_generated": False,
            "strategy_modified": False,
        },
    }


def write_registry_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in REGISTRY_FIELDS})


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Edge Strategy Status Report",
        "",
        "This is an offline audit of tested edge types. It does not generate trades or change strategy logic.",
        "",
        "## Registry",
        "",
        "| Edge Type | Status | Trades | Observations | Win Rate | Avg Return | Total PnL | Convergence | Reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['edge_type']} | {row['recommended_status']} | {row['trades_analyzed']} | "
            f"{row['observations_analyzed']} | {row['win_rate']} | {row['average_return']} | "
            f"{row['total_pnl']} | {row['convergence_score']} | {row['reason']} |"
        )

    lines.extend([
        "",
        "## Required Conclusions",
        "",
        "- Negative expectancy evidence: `price_dislocation_probability_v1`, `price_dislocation_probability_v2`, and the current `cross_market_consistency_v1` sample.",
        "- Rare but logically valid edge: `combined_ask_arbitrage`; it remains enabled/watchable but lacks positive PnL proof.",
        "- Insufficient data: `combined_ask_arbitrage` and longer-window `cross_market_convergence` still need more evidence before any promotion.",
        "- Quarantined edges: `price_dislocation_probability_v1`, `price_dislocation_probability_v2`.",
        "- Watch/research-only edges: `cross_market_consistency_v1`, `cross_market_convergence`, and `combined_ask_arbitrage` until positive shadow evidence exists.",
        "- Tiny live recommendation: **NO**.",
        "",
        "## Next Edge Source Comparison",
        "",
        "| Priority | Source | Pros | Cons | Recommendation |",
        "| ---: | --- | --- | --- | --- |",
    ])
    for item in sorted(NEXT_EDGE_SOURCE_COMPARISON, key=lambda value: value["priority"]):
        lines.append(
            f"| {item['priority']} | {item['source']} | {item['pros']} | {item['cons']} | {item['recommendation']} |"
        )

    lines.extend([
        "",
        "## Recommended Step 10",
        "",
        "**Trading MVP Step 10 — Crypto Price Threshold Edge v1**",
        "",
        "Rationale:",
        "",
        "- External spot price data is easy to collect read-only.",
        "- BTC / ETH / SOL threshold markets are common.",
        "- Rules are more objective than broad event interpretation.",
        "- No LLM is required.",
        "- The system can compute distance_to_threshold, time_to_expiry, and a simple baseline probability.",
        "- This is closer to a real information edge than continuing to mine Polymarket-only microstructure.",
        "",
        "Initial scope:",
        "",
        "- Identify BTC / ETH / SOL threshold markets.",
        "- Read spot price.",
        "- Parse threshold and expiry.",
        "- Calculate distance_to_barrier and time_to_expiry.",
        "- Estimate simple baseline probability.",
        "- Output watch_only / shadow_candidate only.",
        "- No live trading or order placement.",
        "",
        "## Safety Verification",
        "",
        "```json",
        json.dumps(summary.get("safety_verification", {}), indent=2, sort_keys=True),
        "```",
        "",
    ])
    path.write_text("\n".join(lines))


def audit_edge_status(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = build_registry(Path(args.runs_dir), Path(args.shadow_dir))
    summary = build_summary(rows)
    return rows, summary


def print_summary(summary: dict[str, Any], rows: list[dict[str, Any]], dry_run: bool) -> None:
    print("DRY RUN: edge strategy status audit" if dry_run else "Edge strategy status audit")
    print(f"edge_types_reviewed: {summary.get('edge_types_reviewed')}")
    print(f"quarantined_edges: {summary.get('quarantined_edges')}")
    print(f"watch_only_edges: {summary.get('watch_only_edges')}")
    print(f"research_only_edges: {summary.get('research_only_edges')}")
    print(f"enabled_edges: {summary.get('enabled_edges')}")
    print(f"discontinued_edges: {summary.get('discontinued_edges')}")
    print(f"any_edge_supports_tiny_live: {summary.get('any_edge_supports_tiny_live')}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation')}")
    print(f"recommended_next_edge_source: {summary.get('recommended_next_edge_source')}")
    for row in rows:
        print(f"{row['edge_type']}: {row['recommended_status']} — {row['reason']}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, summary = audit_edge_status(args)
    print_summary(summary, rows, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    write_registry_csv(output_dir / "edge_strategy_registry.csv", rows)
    write_summary(output_dir / "edge_strategy_status_summary.json", summary)
    write_report(output_dir / "edge_strategy_status_report.md", rows, summary)
    print(f"edge_strategy_registry_csv: {output_dir / 'edge_strategy_registry.csv'}")
    print(f"edge_strategy_status_summary_json: {output_dir / 'edge_strategy_status_summary.json'}")
    print(f"edge_strategy_status_report_md: {output_dir / 'edge_strategy_status_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
