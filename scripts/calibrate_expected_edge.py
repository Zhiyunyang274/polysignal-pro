#!/usr/bin/env python3
"""
Trading MVP Step 2 — Expected Edge v1 calibration.

This script updates priced tradable candidates with a transparent orderbook-only
edge proxy. It does not call LLMs, run run_paper.py, modify Risk Governor, or
perform any trading action.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from polysignal.shadow.entry_filter import EntryFilterConfig, ShadowEntryFilter
from polysignal.utils.time import utc_now
from scripts.run_shadow_paper_loop import candidate_from_tradable, safe_float

REPO_ROOT = Path(__file__).resolve().parent.parent

EDGE_FIELDS = [
    "combined_ask_gap",
    "executable_edge",
    "expected_edge",
    "expected_edge_source",
    "expected_edge_status",
    "edge_pass",
    "edge_failure_reason",
    "edge_notes",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate orderbook-only expected edge for priced candidates")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--spread_buffer", type=float, default=0.01)
    parser.add_argument("--min_combined_ask_gap", type=float, default=0.005)
    parser.add_argument("--dry_run", action="store_true")
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
        "orderbook_only_edge": True,
        "llm_calls": False,
        "run_paper_invoked": False,
        "risk_governor_modified": False,
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "private_key_handling": False,
    }


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def has_price_fields(row: dict[str, Any]) -> bool:
    return all(
        safe_float(row.get(name), 0.0) > 0
        for name in ["yes_best_bid", "yes_best_ask", "no_best_bid", "no_best_ask"]
    )


def is_control_group_only(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or "")
    tier = str(row.get("near_miss_tier") or "").strip().lower()
    return source == "control_group" and tier not in {"tier1", "tier2", "tier1_mispricing", "tier2_strong_near_miss"}


def has_strong_near_miss(row: dict[str, Any]) -> bool:
    return str(row.get("near_miss_tier") or "").strip().lower() in {
        "tier1",
        "tier2",
        "tier1_mispricing",
        "tier2_strong_near_miss",
    }


def calibrate_row(row: dict[str, str], spread_buffer: float, min_combined_ask_gap: float) -> dict[str, Any]:
    payload: dict[str, Any] = dict(row)
    max_spread = safe_float(payload.get("max_spread"), safe_float(payload.get("spread"), 0.0))
    combined_ask = safe_float(payload.get("combined_ask"), 0.0)
    combined_ask_gap = max(0.0, 1.0 - combined_ask) if combined_ask > 0 else 0.0
    executable_edge = combined_ask_gap - max_spread - spread_buffer
    expected_edge = executable_edge
    edge_pass = executable_edge > 0 and combined_ask_gap >= min_combined_ask_gap

    status = "edge_positive" if edge_pass else "edge_too_low"
    failure_reason = ""
    notes: list[str] = []

    if not has_price_fields(payload):
        status = "missing_price_fields"
        failure_reason = "missing_price_fields"
        edge_pass = False
        expected_edge = 0.0
        executable_edge = 0.0
    elif combined_ask >= 1.0:
        status = "combined_ask_not_below_one"
        failure_reason = "combined_ask_not_below_one"
        edge_pass = False
    elif max_spread >= combined_ask_gap - spread_buffer:
        status = "spread_too_wide" if max_spread > combined_ask_gap else "edge_too_low"
        failure_reason = status
        edge_pass = False
    elif combined_ask_gap < min_combined_ask_gap:
        status = "edge_too_low"
        failure_reason = "edge_too_low"
        edge_pass = False

    if is_control_group_only(payload):
        notes.append("control_group_only_watch")
        if edge_pass and not has_strong_near_miss(payload):
            failure_reason = "control_group_only_watch"
            status = "control_group_only_watch"
            edge_pass = False

    if not has_strong_near_miss(payload):
        notes.append("insufficient_near_miss_evidence")
        if edge_pass and str(payload.get("source") or "") == "control_group":
            failure_reason = "insufficient_near_miss_evidence"
            status = "insufficient_near_miss_evidence"
            edge_pass = False

    payload.update({
        "combined_ask_gap": combined_ask_gap,
        "executable_edge": executable_edge,
        "expected_edge": expected_edge,
        "expected_edge_source": "orderbook_combined_ask_gap_minus_spread_buffer",
        "expected_edge_status": status,
        "edge_pass": edge_pass,
        "edge_failure_reason": failure_reason,
        "edge_notes": "|".join(notes),
    })
    return payload


def calibrate_rows(rows: list[dict[str, str]], spread_buffer: float, min_combined_ask_gap: float) -> list[dict[str, Any]]:
    return [calibrate_row(row, spread_buffer, min_combined_ask_gap) for row in rows]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    entry_filter = ShadowEntryFilter(EntryFilterConfig())
    eligible = 0
    for row in rows:
        if entry_filter.evaluate(candidate_from_tradable(row, set())).allowed:
            eligible += 1
    statuses = [str(row.get("expected_edge_status") or "") for row in rows]
    return {
        "generated_at": utc_now().isoformat(),
        "candidates_loaded": len(rows),
        "expected_edge_available_count": sum(1 for row in rows if safe_float(row.get("expected_edge"), 0.0) > 0),
        "executable_edge_positive_count": sum(1 for row in rows if safe_float(row.get("executable_edge"), 0.0) > 0),
        "expected_edge_pass_count": sum(1 for row in rows if str(row.get("edge_pass")).lower() == "true"),
        "combined_ask_below_one_count": sum(1 for row in rows if safe_float(row.get("combined_ask"), 0.0) < 1.0),
        "spread_too_wide_count": statuses.count("spread_too_wide"),
        "control_group_only_count": sum(1 for row in rows if is_control_group_only(row)),
        "control_group_executable_count": sum(
            1 for row in rows
            if str(row.get("source") or "") == "control_group" and str(row.get("edge_pass")).lower() == "true"
        ),
        "edge_too_low_count": statuses.count("edge_too_low"),
        "combined_ask_not_below_one_count": statuses.count("combined_ask_not_below_one"),
        "missing_price_fields_count": statuses.count("missing_price_fields"),
        "insufficient_near_miss_evidence_count": statuses.count("insufficient_near_miss_evidence"),
        "eligible_after_edge_calibration_count": eligible,
        "tiny_live_recommendation": "NO",
        "safety_verification": verify_safety(),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    for key in EDGE_FIELDS:
        if key not in fields:
            fields.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tradable_candidates_priced": rows}, indent=2))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Expected Edge Calibration Report",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "Expected edge v1 is orderbook-only: combined_ask_gap - max_spread - spread_buffer.",
        "It does not use LLM output, alpha_score, or tradable_score as edge.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "candidates_loaded",
        "expected_edge_available_count",
        "executable_edge_positive_count",
        "expected_edge_pass_count",
        "combined_ask_below_one_count",
        "spread_too_wide_count",
        "edge_too_low_count",
        "control_group_only_count",
        "control_group_executable_count",
        "eligible_after_edge_calibration_count",
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


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: expected edge calibration" if dry_run else "Expected edge calibration")
    for key in [
        "candidates_loaded",
        "expected_edge_available_count",
        "executable_edge_positive_count",
        "expected_edge_pass_count",
        "combined_ask_below_one_count",
        "spread_too_wide_count",
        "edge_too_low_count",
        "control_group_only_count",
        "control_group_executable_count",
        "eligible_after_edge_calibration_count",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


def run(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runs_dir = Path(args.runs_dir)
    rows = load_csv(runs_dir / "tradable_candidates_priced.csv")
    calibrated = calibrate_rows(rows, args.spread_buffer, args.min_combined_ask_gap)
    return calibrated, summarize(calibrated)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, summary = run(args)
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "tradable_candidates_priced.csv", rows)
    write_json(output_dir / "tradable_candidates_priced.json", rows)
    write_summary(output_dir / "expected_edge_calibration_summary.json", summary)
    write_report(output_dir / "expected_edge_calibration_report.md", summary)
    print(f"expected_edge_calibration_summary_json: {output_dir / 'expected_edge_calibration_summary.json'}")
    print(f"expected_edge_calibration_report_md: {output_dir / 'expected_edge_calibration_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
