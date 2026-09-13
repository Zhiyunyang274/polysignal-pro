#!/usr/bin/env python3
"""
Phase 8C — Build offline tradable candidates for shadow trading.

This script only reads existing run artifacts and writes research outputs. It
does not call run_paper.py, real APIs, real LLM providers, or execution modules.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from polysignal.shadow.tradable_candidates import (
    TRADABLE_SCORE_DISCLAIMER,
    TradableCandidate,
    TradableCandidateBuilder,
    TradableCandidateBuilderConfig,
)
from polysignal.utils.time import utc_now

TRADABLE_CANDIDATE_FIELDS = [
    "market_id",
    "question",
    "category",
    "source",
    "combined_ask",
    "ambiguity_risk",
    "liquidity_score",
    "spread",
    "orderbook_depth",
    "near_miss_tier",
    "appearances",
    "evidence_level",
    "is_avoid_candidate",
    "near_miss_score",
    "liquidity_score_component",
    "ambiguity_penalty",
    "spread_penalty",
    "repeat_observation_score",
    "watchlist_persistence_score",
    "tradable_score",
    "entry_decision_hint",
    "reasons",
    "alpha_score",
    "run_ids",
    "yes_token_id",
    "no_token_id",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build offline tradable candidate pool")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--max_ambiguity_risk", type=float, default=30.0)
    parser.add_argument("--min_liquidity_score", type=float, default=1.0)
    parser.add_argument("--max_spread", type=float, default=0.05)
    parser.add_argument("--min_orderbook_depth", type=float, default=1.0)
    parser.add_argument("--top_n", type=int, default=50)
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_json(path: Path) -> Any:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def load_control_group_rows(runs_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(runs_dir.glob("run_*/control_group_samples.csv")):
        rows.extend(load_csv(path))
    return rows


def candidate_to_csv_row(candidate: TradableCandidate) -> dict[str, Any]:
    row = candidate.to_dict()
    row["reasons"] = "|".join(candidate.reasons)
    return {field: row.get(field, "") for field in TRADABLE_CANDIDATE_FIELDS}


def write_candidates_csv(path: Path, candidates: list[TradableCandidate]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADABLE_CANDIDATE_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate_to_csv_row(candidate))


def write_candidates_json(
    path: Path,
    candidates: list[TradableCandidate],
    summary: dict[str, Any],
) -> None:
    payload = {
        "generated_at": summary["generated_at"],
        "disclaimer": TRADABLE_SCORE_DISCLAIMER,
        "summary": summary,
        "tradable_candidates": [candidate.to_dict() for candidate in candidates],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def write_report(
    path: Path,
    candidates: list[TradableCandidate],
    summary: dict[str, Any],
) -> None:
    lines = [
        "# Tradable Candidate Report",
        "",
        f"Generated at: {summary['generated_at']}",
        "",
        f"Safety note: {TRADABLE_SCORE_DISCLAIMER}",
        "",
        "## Summary",
        "",
        f"- Candidates considered: {summary['candidates_considered']}",
        f"- Tradable candidates: {summary['tradable_candidates']}",
        f"- Excluded avoid candidates: {summary['excluded_avoid_candidates']}",
        "",
        "## Exclusion Summary",
        "",
    ]
    if summary["exclusion_summary"]:
        for reason, count in summary["exclusion_summary"].items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none: 0")
    lines.extend([
        "",
        "## Top Candidates",
        "",
    ])
    if not candidates:
        lines.append("No tradable candidates passed the conservative offline filters.")
    else:
        for candidate in candidates[:10]:
            lines.append(
                "- "
                f"{candidate.market_id} | {candidate.source} | score={candidate.tradable_score} | "
                f"hint={candidate.entry_decision_hint} | reasons={','.join(candidate.reasons)} | "
                f"{candidate.question}"
            )
    lines.extend([
        "",
        "## Safety Verification",
        "",
        "- This pool is for offline shadow trading only.",
        "- tradable_score is not a trading signal.",
        "- Candidates must still pass the Shadow Entry Filter.",
        "- Avoid candidates remain hard-excluded.",
        "- No live trading, API calls, LLM calls, or order placement are performed.",
    ])
    path.write_text("\n".join(lines) + "\n")


def build(args: argparse.Namespace) -> tuple[list[TradableCandidate], dict[str, Any]]:
    runs_dir = Path(args.runs_dir)
    builder = TradableCandidateBuilder(
        TradableCandidateBuilderConfig(
            max_ambiguity_risk=args.max_ambiguity_risk,
            min_liquidity_score=args.min_liquidity_score,
            max_spread=args.max_spread,
            min_orderbook_depth=args.min_orderbook_depth,
            top_n=args.top_n,
        )
    )
    trajectories = load_json(runs_dir / "market_trajectories.json")
    if not isinstance(trajectories, list):
        trajectories = []
    candidates = builder.build(
        watchlist_rows=load_csv(runs_dir / "persistent_watchlist.csv"),
        alpha_rows=load_csv(runs_dir / "alpha_candidates.csv"),
        avoid_rows=load_csv(runs_dir / "avoid_candidates.csv"),
        trajectory_items=trajectories,
        control_group_rows=load_control_group_rows(runs_dir),
        alpha_validation_rows=load_csv(runs_dir / "alpha_validation.csv"),
        watchlist_validation_rows=load_csv(runs_dir / "watchlist_validation.csv"),
    )
    exclusion_summary = dict(builder.exclusion_summary.most_common())
    summary = {
        "generated_at": utc_now().isoformat(),
        "runs_dir": str(runs_dir),
        "candidates_considered": builder.considered_count,
        "tradable_candidates": len(candidates),
        "excluded_avoid_candidates": exclusion_summary.get("avoid_candidate", 0),
        "exclusion_summary": exclusion_summary,
        "disclaimer": TRADABLE_SCORE_DISCLAIMER,
        "thresholds": {
            "max_ambiguity_risk": args.max_ambiguity_risk,
            "min_liquidity_score": args.min_liquidity_score,
            "max_spread": args.max_spread,
            "min_orderbook_depth": args.min_orderbook_depth,
            "top_n": args.top_n,
        },
        "safety_verification": {
            "offline_only": True,
            "run_paper_invoked": False,
            "real_api_calls": False,
            "llm_calls": False,
            "private_key_handling": False,
            "live_orders": False,
        },
    }
    return candidates, summary


def print_summary(candidates: list[TradableCandidate], summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: tradable candidate builder" if dry_run else "Tradable candidate builder")
    print(f"runs_dir: {summary['runs_dir']}")
    print(f"candidates_considered: {summary['candidates_considered']}")
    print(f"tradable_candidates_would_generate: {len(candidates)}" if dry_run else f"tradable_candidates: {len(candidates)}")
    print(f"excluded_avoid_candidates: {summary['excluded_avoid_candidates']}")
    print(f"exclusion_summary: {summary['exclusion_summary']}")
    print("top_candidates:")
    for candidate in candidates[:5]:
        print(
            f"- {candidate.market_id} score={candidate.tradable_score} "
            f"hint={candidate.entry_decision_hint} source={candidate.source}"
        )
    print(TRADABLE_SCORE_DISCLAIMER)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates, summary = build(args)
    print_summary(candidates, summary, args.dry_run)
    if args.dry_run:
        return 0

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "tradable_candidates.csv"
    json_path = output_dir / "tradable_candidates.json"
    report_path = output_dir / "tradable_candidate_report.md"
    write_candidates_csv(csv_path, candidates)
    write_candidates_json(json_path, candidates, summary)
    write_report(report_path, candidates, summary)
    print(f"tradable_candidates_csv: {csv_path}")
    print(f"tradable_candidates_json: {json_path}")
    print(f"tradable_candidate_report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
