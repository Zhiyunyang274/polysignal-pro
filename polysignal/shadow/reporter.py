"""Report writers for shadow paper trading."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from polysignal.shadow.models import SHADOW_TRADE_FIELDS, ShadowTrade, ShadowTradeStatus
from polysignal.shadow.pnl import summarize_performance
from polysignal.utils.time import utc_now

DIAGNOSTIC_FIELDS = [
    "market_id",
    "question",
    "alpha_score",
    "ambiguity_risk",
    "liquidity_score",
    "combined_ask",
    "expected_edge",
    "confidence",
    "edge_type",
    "evidence",
    "relationship_status",
    "relationship_confidence",
    "price_gap",
    "reference_market_id",
    "reference_price",
    "convergence_gate_passed",
    "convergence_score",
    "convergence_status",
    "convergence_reason",
    "convergence_observation_count",
    "initial_price_gap",
    "final_price_gap",
    "gap_change",
    "entry_side_price",
    "entry_yes_best_ask",
    "entry_no_best_ask",
    "entry_yes_best_bid",
    "entry_no_best_bid",
    "near_miss_tier",
    "is_avoid_candidate",
    "tradable_score",
    "tradable_source",
    "tradable_reasons",
    "evidence_level",
    "entry_decision",
    "reject_reasons",
    "watch_reasons",
]


def write_shadow_trades_csv(path: Path, trades: list[ShadowTrade]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHADOW_TRADE_FIELDS)
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.to_dict())


def write_shadow_positions_json(path: Path, trades: list[ShadowTrade]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    positions = {
        "generated_at": utc_now().isoformat(),
        "open_positions": [
            trade.to_dict() for trade in trades if trade.status == ShadowTradeStatus.OPEN
        ],
        "closed_positions": [
            trade.to_dict() for trade in trades if trade.status == ShadowTradeStatus.CLOSED
        ],
        "insufficient_forward_data_positions": [
            trade.to_dict() for trade in trades if trade.status == ShadowTradeStatus.INSUFFICIENT_FORWARD_DATA
        ],
    }
    path.write_text(json.dumps(positions, indent=2))


def build_performance_summary(
    trades: list[ShadowTrade],
    safety_verification: dict[str, Any],
    diagnostics_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summarize_performance(trades)
    summary.update({
        "generated_at": utc_now().isoformat(),
        "safety_verification": safety_verification,
    })
    if diagnostics_summary:
        summary["entry_diagnostics"] = diagnostics_summary
    return summary


def write_performance_summary_json(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))


def write_performance_report_md(path: Path, summary: dict[str, Any], trades: list[ShadowTrade]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Shadow Paper Performance Report",
        "",
        f"Generated at: `{summary.get('generated_at')}`",
        "",
        "Shadow performance is hypothetical and not a live trading result.",
        "Shadow trading is hypothetical research validation only. It is not PaperTrader,",
        "does not place orders, and must not enter the live execution path.",
        "combined_ask is a market-level feature, not a side-specific entry price.",
        "",
        "## Shadow Trading Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total shadow trades | {summary.get('total_shadow_trades')} |",
        f"| Closed positions | {summary.get('closed_positions')} |",
        f"| Open positions | {summary.get('open_positions')} |",
        f"| Insufficient forward data positions | {summary.get('insufficient_forward_data_positions', 0)} |",
        "",
        "## PnL Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Win rate | {summary.get('win_rate'):.4f} |",
        f"| Average return | {summary.get('average_return'):.4f} |",
        f"| Median return | {summary.get('median_return'):.4f} |",
        f"| Total PnL | {summary.get('total_pnl'):.4f} |",
        f"| Max drawdown | {summary.get('max_drawdown'):.4f} |",
        f"| Average holding minutes | {summary.get('avg_holding_minutes', 0.0):.4f} |",
        "",
        "## Entry Diagnostics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Candidates loaded | {summary.get('entry_diagnostics', {}).get('candidates_loaded', 0)} |",
        f"| Eligible shadow entry | {summary.get('entry_diagnostics', {}).get('eligible_shadow_entry', 0)} |",
        f"| Watch only | {summary.get('entry_diagnostics', {}).get('watch_only', 0)} |",
        f"| Rejected | {summary.get('entry_diagnostics', {}).get('rejected', 0)} |",
        "",
        "Top rejection reasons:",
        "",
        json.dumps(summary.get("entry_diagnostics", {}).get("top_rejection_reasons", {}), indent=2),
        "",
        "Top watch-only candidates:",
        "",
        json.dumps(summary.get("entry_diagnostics", {}).get("top_watch_only_candidates", []), indent=2),
        "",
        "## Entry Distribution",
        "",
        json.dumps(summary.get("entry_reason_distribution", {}), indent=2),
        "",
        "## Exit Distribution",
        "",
        json.dumps(summary.get("exit_reason_distribution", {}), indent=2),
        "",
        "## Open / Insufficient Data Positions",
        "",
        f"Open positions: {summary.get('open_positions', 0)}",
        "",
        f"Insufficient forward data positions: {summary.get('insufficient_forward_data_positions', 0)}",
        "",
        "Forward data limitation: trades without existing trajectory or forward observations remain unclosed and do not contribute to PnL.",
        "",
        "## Category Performance",
        "",
        json.dumps(summary.get("category_performance", {}), indent=2),
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
        "## Source Performance",
        "",
        json.dumps(summary.get("source_performance", {}), indent=2),
        "",
        "## Safety Verification",
        "",
        json.dumps(summary.get("safety_verification", {}), indent=2),
        "",
        "## Recent Trades",
        "",
        "| Market | Side | Entry | Exit | Return | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for trade in trades[:20]:
        lines.append(
            f"| {trade.question[:70].replace('|', '/')} | {trade.side.value} | "
            f"{trade.entry_price:.4f} | {trade.exit_price if trade.exit_price is not None else 'n/a'} | "
            f"{trade.return_pct:.4f} | {trade.exit_reason.value} |"
        )
    path.write_text("\n".join(lines) + "\n")


def write_all_reports(output_dir: Path, trades: list[ShadowTrade], safety: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_performance_summary(trades, safety)
    paths = {
        "shadow_trades_csv": output_dir / "shadow_trades.csv",
        "shadow_positions_json": output_dir / "shadow_positions.json",
        "paper_performance_report_md": output_dir / "paper_performance_report.md",
        "paper_performance_summary_json": output_dir / "paper_performance_summary.json",
    }
    write_shadow_trades_csv(paths["shadow_trades_csv"], trades)
    write_shadow_positions_json(paths["shadow_positions_json"], trades)
    write_performance_report_md(paths["paper_performance_report_md"], summary, trades)
    write_performance_summary_json(paths["paper_performance_summary_json"], summary)
    return {key: str(value) for key, value in paths.items()}


def write_entry_diagnostics_json(path: Path, diagnostics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diagnostics, indent=2))


def write_entry_diagnostics_csv(path: Path, diagnostics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DIAGNOSTIC_FIELDS)
        writer.writeheader()
        for row in diagnostics:
            payload = dict(row)
            payload["reject_reasons"] = "|".join(payload.get("reject_reasons", []))
            payload["watch_reasons"] = "|".join(payload.get("watch_reasons", []))
            payload["tradable_reasons"] = "|".join(payload.get("tradable_reasons", []))
            writer.writerow({field: payload.get(field, "") for field in DIAGNOSTIC_FIELDS})


def write_all_reports_with_diagnostics(
    output_dir: Path,
    trades: list[ShadowTrade],
    safety: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    diagnostics_summary: dict[str, Any],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_performance_summary(trades, safety, diagnostics_summary)
    paths = {
        "shadow_trades_csv": output_dir / "shadow_trades.csv",
        "shadow_positions_json": output_dir / "shadow_positions.json",
        "paper_performance_report_md": output_dir / "paper_performance_report.md",
        "paper_performance_summary_json": output_dir / "paper_performance_summary.json",
        "shadow_entry_diagnostics_json": output_dir / "shadow_entry_diagnostics.json",
        "shadow_entry_diagnostics_csv": output_dir / "shadow_entry_diagnostics.csv",
    }
    write_shadow_trades_csv(paths["shadow_trades_csv"], trades)
    write_shadow_positions_json(paths["shadow_positions_json"], trades)
    write_performance_report_md(paths["paper_performance_report_md"], summary, trades)
    write_performance_summary_json(paths["paper_performance_summary_json"], summary)
    write_entry_diagnostics_json(paths["shadow_entry_diagnostics_json"], diagnostics)
    write_entry_diagnostics_csv(paths["shadow_entry_diagnostics_csv"], diagnostics)
    return {key: str(value) for key, value in paths.items()}
