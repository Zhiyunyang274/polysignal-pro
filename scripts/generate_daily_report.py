#!/usr/bin/env python3
"""
Phase 7D — Daily Report Generator.

Offline-only research report aggregation for recent PolySignal Pro runs.

IMPORTANT SAFETY CONSTRAINTS:
- Does NOT run run_paper.py
- Does NOT call real APIs
- Does NOT call real LLM providers
- Does NOT import LiveTrader, PaperTrader, RiskGovernor, or strategies
- Does NOT modify config
- Does NOT place orders
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runs"
DAILY_REPORT_MD = "daily_report.md"
DAILY_REPORT_JSON = "daily_report_summary.json"

ALPHA_DISCLAIMER = (
    "Alpha candidates are heuristic research rankings, NOT trading signals. "
    "They must not trigger PaperTrader, Risk Governor score changes, or live execution."
)
AVOID_EXPLANATION = (
    "Avoid candidates are descriptive risk flags for research triage. "
    "They are NOT new hard rejects and do not modify Risk Governor behavior."
)


def parse_bool(value: str) -> bool:
    return value.lower() in ("true", "1", "yes", "y", "on")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an offline daily research report from existing runs",
    )
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--latest_n", type=int, default=10)
    parser.add_argument("--date", type=str, default=None, help="Optional YYYY-MM-DD filter")
    parser.add_argument("--include_validation", type=parse_bool, default=True)
    parser.add_argument("--include_intelligence", type=parse_bool, default=True)
    parser.add_argument("--include_candidates", type=parse_bool, default=True)
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


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def numeric(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    return int(numeric(value, float(default)))


@dataclass
class RunRecord:
    run_dir: Path
    summary: dict[str, Any]

    @property
    def run_id(self) -> str:
        return str(self.summary.get("run_id") or self.run_dir.name)

    @property
    def start_time(self) -> str:
        return str(self.summary.get("start_time") or "")

    @property
    def date(self) -> str:
        return self.start_time[:10] if self.start_time else ""


@dataclass
class DailyReportData:
    runs_dir: Path
    output_dir: Path
    latest_n: int
    date_filter: Optional[str]
    runs: list[RunRecord] = field(default_factory=list)
    validation_summary: dict[str, Any] = field(default_factory=dict)
    intelligence_summary: dict[str, Any] = field(default_factory=dict)
    validation_loop_summary: dict[str, Any] = field(default_factory=dict)
    alpha_candidates: list[dict[str, str]] = field(default_factory=list)
    avoid_candidates: list[dict[str, str]] = field(default_factory=list)
    watchlist: list[dict[str, str]] = field(default_factory=list)
    safety_verification: dict[str, Any] = field(default_factory=dict)


def discover_runs(runs_dir: Path, latest_n: int = 10, date_filter: Optional[str] = None) -> list[RunRecord]:
    records: list[RunRecord] = []
    if not runs_dir.exists():
        return records

    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
            continue
        summary = load_json(run_dir / "summary.json")
        if not summary:
            continue
        record = RunRecord(run_dir=run_dir, summary=summary)
        if date_filter and record.date != date_filter:
            continue
        records.append(record)

    records.sort(key=lambda r: (r.start_time, r.run_id), reverse=True)
    return records[:latest_n]


def verify_safety(
    risk_config_path: Path = REPO_ROOT / "config" / "risk.yaml",
    llm_config_path: Path = REPO_ROOT / "config" / "llm.yaml",
) -> dict[str, Any]:
    risk = load_yaml(risk_config_path)
    llm = load_yaml(llm_config_path)
    return {
        "live_trading_enabled": bool(risk.get("live_trading_enabled")),
        "allow_auto_execution": bool(risk.get("allow_auto_execution")),
        "paper_trading_enabled": bool(risk.get("paper_trading_enabled")),
        "default_llm_provider": llm.get("provider"),
        "offline_only": True,
        "real_api_calls": False,
        "llm_calls": False,
        "trading_actions": False,
        "config_modified": False,
        "safe_to_report": (
            bool(risk.get("live_trading_enabled")) is False
            and bool(risk.get("allow_auto_execution")) is False
            and bool(risk.get("paper_trading_enabled")) is True
            and llm.get("provider") == "mock"
        ),
    }


def load_report_data(args: argparse.Namespace) -> DailyReportData:
    runs_dir = Path(args.runs_dir)
    output_dir = Path(args.output_dir)
    data = DailyReportData(
        runs_dir=runs_dir,
        output_dir=output_dir,
        latest_n=args.latest_n,
        date_filter=args.date,
    )
    data.runs = discover_runs(runs_dir, latest_n=args.latest_n, date_filter=args.date)
    data.validation_loop_summary = load_json(runs_dir / "validation_loop_summary.json")

    if args.include_validation:
        data.validation_summary = load_json(runs_dir / "strategy_validation_summary.json")
    if args.include_intelligence:
        data.intelligence_summary = load_json(runs_dir / "intelligence_comparison_summary.json")
    if args.include_candidates:
        data.alpha_candidates = load_csv_rows(runs_dir / "alpha_candidates.csv")
        data.avoid_candidates = load_csv_rows(runs_dir / "avoid_candidates.csv")
        data.watchlist = load_csv_rows(runs_dir / "persistent_watchlist.csv")

    data.safety_verification = verify_safety()
    return data


def date_range_for_runs(runs: list[RunRecord]) -> dict[str, Optional[str]]:
    dates = [r.date for r in runs if r.date]
    if not dates:
        return {"earliest": None, "latest": None}
    return {"earliest": min(dates), "latest": max(dates)}


def candidate_snapshot(rows: list[dict[str, str]], score_field: str, limit: int = 5) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda r: numeric(r.get(score_field)), reverse=True)
    snapshot: list[dict[str, Any]] = []
    for row in sorted_rows[:limit]:
        snapshot.append({
            "market_id": row.get("market_id", ""),
            "question": row.get("question", ""),
            "category": row.get("category", ""),
            "appearances": integer(row.get("appearances")),
            score_field: numeric(row.get(score_field)),
            "evidence_level": row.get("evidence_level", ""),
            "reasons": row.get("reasons", ""),
        })
    return snapshot


def aggregate_summary(data: DailyReportData) -> dict[str, Any]:
    runs = data.runs
    validation = data.validation_summary
    q1 = validation.get("q1_alpha_forward_change", {}) if validation else {}
    q2 = validation.get("q2_avoid_risk_validation", {}) if validation else {}

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "date_range": date_range_for_runs(runs),
        "runs_analyzed": len(runs),
        "run_ids": [r.run_id for r in runs],
        "total_markets_checked": sum(integer(r.summary.get("markets_checked")) for r in runs),
        "total_orderbooks_fetched": sum(integer(r.summary.get("orderbooks_fetched")) for r in runs),
        "total_signals_generated": sum(integer(r.summary.get("signals_generated")) for r in runs),
        "total_paper_trades_created": sum(integer(r.summary.get("paper_trades_created")) for r in runs),
        "total_llm_calls": sum(integer(r.summary.get("llm_calls")) for r in runs),
        "total_api_errors": sum(integer(r.summary.get("api_errors")) for r in runs),
        "total_websocket_messages": sum(integer(r.summary.get("websocket_messages")) for r in runs),
        "total_websocket_errors": sum(integer(r.summary.get("websocket_errors")) for r in runs),
        "latest_strategy_validation_status": validation.get("validation_timestamp") if validation else None,
        "q1_alpha_status": q1.get("conclusion_status"),
        "q2_avoid_status": q2.get("conclusion_status"),
        "top_alpha_candidates": candidate_snapshot(data.alpha_candidates, "alpha_score"),
        "top_avoid_candidates": candidate_snapshot(data.avoid_candidates, "avoid_score"),
        "persistent_watchlist_count": len(data.watchlist),
        "validation_loop": {
            "run_id": data.validation_loop_summary.get("run_id"),
            "run_success": data.validation_loop_summary.get("run_success"),
            "validation_success": data.validation_loop_summary.get("validation_success"),
            "intelligence_success": data.validation_loop_summary.get("intelligence_success"),
            "comparison_success": data.validation_loop_summary.get("comparison_success"),
        } if data.validation_loop_summary else {},
        "safety_verification": data.safety_verification,
        "alpha_disclaimer": ALPHA_DISCLAIMER,
        "avoid_explanation": AVOID_EXPLANATION,
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value)


def markdown_table(rows: list[list[Any]]) -> str:
    if not rows:
        return "No data available.\n"
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|")

    header = rows[0]
    lines = [
        "| " + " | ".join(cell(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(cell(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def generate_markdown(data: DailyReportData, summary: dict[str, Any]) -> str:
    validation = data.validation_summary
    intelligence = data.intelligence_summary
    q1 = validation.get("q1_alpha_forward_change", {}) if validation else {}
    q2 = validation.get("q2_avoid_risk_validation", {}) if validation else {}

    run_rows = [["Run ID", "Start", "Mode", "Markets", "Orderbooks", "Signals", "Paper Trades", "API Errors"]]
    for run in data.runs:
        s = run.summary
        run_rows.append([
            run.run_id,
            fmt(s.get("start_time")),
            fmt(s.get("data_mode")),
            integer(s.get("markets_checked")),
            integer(s.get("orderbooks_fetched")),
            integer(s.get("signals_generated")),
            integer(s.get("paper_trades_created")),
            integer(s.get("api_errors")),
        ])

    alpha_rows = [["Market", "Category", "Appearances", "Alpha Score", "Evidence"]]
    for item in summary["top_alpha_candidates"]:
        alpha_rows.append([
            item["question"][:80],
            item["category"],
            item["appearances"],
            round(item["alpha_score"], 2),
            item["evidence_level"],
        ])

    avoid_rows = [["Market", "Category", "Appearances", "Avoid Score", "Evidence", "Reasons"]]
    for item in summary["top_avoid_candidates"]:
        avoid_rows.append([
            item["question"][:70],
            item["category"],
            item["appearances"],
            round(item["avoid_score"], 2),
            item["evidence_level"],
            item["reasons"],
        ])

    watchlist_rows = [["Market", "Category", "Appearances", "Mode", "Evidence"]]
    for row in data.watchlist[:10]:
        watchlist_rows.append([
            row.get("question", "")[:80],
            row.get("category", ""),
            row.get("appearances", ""),
            row.get("suggested_mode_mode", ""),
            row.get("evidence_level", ""),
        ])

    safety = data.safety_verification
    safety_rows = [["Check", "Value"]]
    for key in [
        "live_trading_enabled",
        "allow_auto_execution",
        "paper_trading_enabled",
        "default_llm_provider",
        "offline_only",
        "real_api_calls",
        "llm_calls",
        "trading_actions",
        "config_modified",
        "safe_to_report",
    ]:
        safety_rows.append([key, fmt(safety.get(key))])

    return f"""# PolySignal Pro Daily Research Report

Generated at: `{summary["generated_at"]}`

## Daily Summary

{markdown_table([
    ["Metric", "Value"],
    ["Date range", f'{fmt(summary["date_range"]["earliest"])} to {fmt(summary["date_range"]["latest"])}'],
    ["Runs analyzed", summary["runs_analyzed"]],
    ["Markets checked", summary["total_markets_checked"]],
    ["Orderbooks fetched", summary["total_orderbooks_fetched"]],
    ["Signals generated", summary["total_signals_generated"]],
    ["Paper trades created", summary["total_paper_trades_created"]],
])}

## Run Activity

{markdown_table(run_rows)}

## LLM Activity

{markdown_table([
    ["Metric", "Value"],
    ["Total LLM calls", summary["total_llm_calls"]],
    ["Comparison total LLM samples", intelligence.get("summary_statistics", {}).get("total_llm_samples", "n/a") if intelligence else "n/a"],
    ["Comparison LLM success rate", intelligence.get("summary_statistics", {}).get("llm_success_rate", "n/a") if intelligence else "n/a"],
])}

## Strategy Validation Snapshot

{markdown_table([
    ["Metric", "Value"],
    ["Validation timestamp", fmt(summary["latest_strategy_validation_status"])],
    ["Q1 alpha forward change", fmt(summary["q1_alpha_status"])],
    ["Q2 avoid risk validation", fmt(summary["q2_avoid_status"])],
    ["Q2 ambiguity delta", fmt(q2.get("ambiguity_risk_delta"))],
    ["Q2 non-avoid group size", fmt(q2.get("non_avoid_group_size"))],
    ["Q1 total candidates", fmt(q1.get("total_candidates"))],
])}

## Alpha Candidates Snapshot

{ALPHA_DISCLAIMER}

{markdown_table(alpha_rows)}

## Avoid Candidates Snapshot

{AVOID_EXPLANATION}

{markdown_table(avoid_rows)}

## Watchlist Snapshot

Persistent watchlist count: `{summary["persistent_watchlist_count"]}`

{markdown_table(watchlist_rows)}

## API/WebSocket Health

{markdown_table([
    ["Metric", "Value"],
    ["Total API errors", summary["total_api_errors"]],
    ["Total WebSocket messages", summary["total_websocket_messages"]],
    ["Total WebSocket errors", summary["total_websocket_errors"]],
])}

## Safety Verification

{markdown_table(safety_rows)}

## Recommended Next Actions

- Keep long data collection on the cloud host, not as a local development blocker.
- Review alpha candidates as research observations only; do not treat alpha_score as a signal.
- Review avoid candidates as risk triage only; do not convert avoid_score into a hard reject.
- Keep `live_trading_enabled=false` and `allow_auto_execution=false`.
- Proceed to Phase 7E only for cloud overnight data collection after smoke tests pass.
"""


def write_outputs(output_dir: Path, summary: dict[str, Any], markdown: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / DAILY_REPORT_JSON
    report_path = output_dir / DAILY_REPORT_MD
    summary_path.write_text(json.dumps(summary, indent=2))
    report_path.write_text(markdown)
    return report_path, summary_path


def run(args: argparse.Namespace) -> int:
    data = load_report_data(args)
    summary = aggregate_summary(data)
    markdown = generate_markdown(data, summary)

    if args.dry_run:
        print("DRY RUN: daily report would be generated")
        print(f"runs_dir: {data.runs_dir}")
        print(f"output_dir: {data.output_dir}")
        print(f"runs_analyzed: {summary['runs_analyzed']}")
        print(f"date_range: {summary['date_range']}")
        print(f"top_alpha_candidates: {len(summary['top_alpha_candidates'])}")
        print(f"top_avoid_candidates: {len(summary['top_avoid_candidates'])}")
        print(f"persistent_watchlist_count: {summary['persistent_watchlist_count']}")
        print(f"safe_to_report: {summary['safety_verification'].get('safe_to_report')}")
        return 0

    report_path, summary_path = write_outputs(data.output_dir, summary, markdown)
    print(f"Daily report: {report_path}")
    print(f"Daily report summary: {summary_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
