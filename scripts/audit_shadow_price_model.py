#!/usr/bin/env python3
"""
Phase 8I — Offline shadow price model audit.

This script audits existing shadow trades for legacy combined_ask-as-entry
usage. It does not modify trading logic, call APIs/LLMs, run run_paper.py, or
touch live trading configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit shadow trade price model")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--output_dir", type=str, default="runs/shadow")
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


def load_trades(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def audit_trade(row: dict[str, str]) -> dict[str, Any]:
    entry_price = safe_float(row.get("entry_price"))
    combined_ask = safe_float(row.get("combined_ask"))
    entry_side_price = optional_float(row.get("entry_side_price"))
    exit_side_price = optional_float(row.get("exit_side_price"))
    exit_price = optional_float(row.get("exit_price"))
    combined_entry = entry_price > 0 and combined_ask > 0 and abs(entry_price - combined_ask) < 1e-9
    missing_entry_side = entry_side_price is None or entry_side_price <= 0
    corrected_available = (
        entry_side_price is not None
        and entry_side_price > 0
        and ((exit_side_price is not None and exit_side_price > 0) or (exit_price is not None and exit_price > 0))
    )
    return {
        "shadow_trade_id": row.get("shadow_trade_id", ""),
        "market_id": row.get("market_id", ""),
        "combined_ask_entry_detected": combined_entry,
        "missing_entry_side_price": missing_entry_side,
        "invalid_entry_price_model": combined_entry or missing_entry_side,
        "corrected_pnl_available": corrected_available,
        "corrected_pnl_unavailable": not corrected_available,
        "price_interpretation_risk": combined_entry or missing_entry_side,
    }


def build_summary(trades: list[dict[str, str]], trade_file: Path) -> dict[str, Any]:
    audits = [audit_trade(row) for row in trades]
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "trade_file": str(trade_file),
        "trades_reviewed": len(trades),
        "combined_ask_entry_detected_count": sum(1 for row in audits if row["combined_ask_entry_detected"]),
        "invalid_entry_price_model_count": sum(1 for row in audits if row["invalid_entry_price_model"]),
        "missing_entry_side_price_count": sum(1 for row in audits if row["missing_entry_side_price"]),
        "corrected_pnl_available_count": sum(1 for row in audits if row["corrected_pnl_available"]),
        "corrected_pnl_unavailable_count": sum(1 for row in audits if row["corrected_pnl_unavailable"]),
        "price_interpretation_risk_count": sum(1 for row in audits if row["price_interpretation_risk"]),
        "recommendation": (
            "Treat legacy combined_ask-entry PnL as invalid. Require side-specific entry ask "
            "and side-specific exit bid before using shadow PnL."
        ),
        "tiny_live_recommendation": "NO",
        "safety_verification": verify_safety(),
        "trade_audits": audits,
    }


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Shadow Price Model Audit",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "combined_ask is a market-level feature, not a side-specific entry price.",
        "This audit is offline and shadow-only. It is not a live trading result.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Trades reviewed | {summary['trades_reviewed']} |",
        f"| combined_ask entry detected | {summary['combined_ask_entry_detected_count']} |",
        f"| invalid entry price model | {summary['invalid_entry_price_model_count']} |",
        f"| missing entry side price | {summary['missing_entry_side_price_count']} |",
        f"| corrected PnL available | {summary['corrected_pnl_available_count']} |",
        f"| corrected PnL unavailable | {summary['corrected_pnl_unavailable_count']} |",
        f"| price interpretation risk | {summary['price_interpretation_risk_count']} |",
        "",
        "## Recommendation",
        "",
        summary["recommendation"],
        "",
        f"Tiny live recommendation: **{summary['tiny_live_recommendation']}**",
        "",
        "## Safety Verification",
        "",
        json.dumps(summary["safety_verification"], indent=2),
        "",
    ]
    path.write_text("\n".join(lines))


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: shadow price model audit" if dry_run else "Shadow price model audit")
    for key in [
        "trades_reviewed",
        "combined_ask_entry_detected_count",
        "invalid_entry_price_model_count",
        "missing_entry_side_price_count",
        "corrected_pnl_available_count",
        "corrected_pnl_unavailable_count",
        "price_interpretation_risk_count",
        "tiny_live_recommendation",
    ]:
        print(f"{key}: {summary[key]}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    shadow_dir = Path(args.shadow_dir)
    output_dir = Path(args.output_dir)
    trade_file = select_trade_file(shadow_dir)
    summary = build_summary(load_trades(trade_file), trade_file)
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    write_summary(output_dir / "shadow_price_model_audit_summary.json", summary)
    write_report(output_dir / "shadow_price_model_audit.md", summary)
    print(f"shadow_price_model_audit_md: {output_dir / 'shadow_price_model_audit.md'}")
    print(f"shadow_price_model_audit_summary_json: {output_dir / 'shadow_price_model_audit_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
