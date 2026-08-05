"""Tests for Phase 8I shadow price model audit."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.audit_shadow_price_model as audit
from polysignal.shadow.models import SHADOW_TRADE_FIELDS


def write_trade(path: Path, **overrides) -> None:
    row = {field: "" for field in SHADOW_TRADE_FIELDS}
    row.update({
        "shadow_trade_id": "shadow_1",
        "market_id": "m1",
        "question": "Will test happen?",
        "side": "YES",
        "entry_price": "1.001",
        "entry_reason": "legacy",
        "combined_ask": "1.001",
        "exit_price": "0.10",
        "pnl": "-0.9",
        "return_pct": "-0.9",
        "status": "closed",
    })
    row.update(overrides)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHADOW_TRADE_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def setup_shadow_dir(tmp_path: Path, **overrides) -> Path:
    shadow_dir = tmp_path / "runs" / "shadow"
    shadow_dir.mkdir(parents=True)
    write_trade(shadow_dir / "updated_shadow_trades.csv", **overrides)
    return shadow_dir


def test_old_combined_ask_entry_trades_are_marked(tmp_path: Path):
    shadow_dir = setup_shadow_dir(tmp_path)

    summary = audit.build_summary(audit.load_trades(shadow_dir / "updated_shadow_trades.csv"), shadow_dir / "updated_shadow_trades.csv")

    assert summary["combined_ask_entry_detected_count"] == 1
    assert summary["invalid_entry_price_model_count"] == 1
    assert summary["price_interpretation_risk_count"] == 1


def test_corrected_pnl_available_when_side_prices_exist(tmp_path: Path):
    shadow_dir = setup_shadow_dir(
        tmp_path,
        entry_price="0.50",
        combined_ask="1.001",
        entry_side_price="0.50",
        exit_side_price="0.55",
    )

    summary = audit.build_summary(audit.load_trades(shadow_dir / "updated_shadow_trades.csv"), shadow_dir / "updated_shadow_trades.csv")

    assert summary["corrected_pnl_available_count"] == 1
    assert summary["corrected_pnl_unavailable_count"] == 0


def test_missing_entry_side_price_count(tmp_path: Path):
    shadow_dir = setup_shadow_dir(tmp_path, entry_price="0.50", combined_ask="1.001")

    summary = audit.build_summary(audit.load_trades(shadow_dir / "updated_shadow_trades.csv"), shadow_dir / "updated_shadow_trades.csv")

    assert summary["missing_entry_side_price_count"] == 1


def test_price_model_audit_outputs_format(tmp_path: Path):
    shadow_dir = setup_shadow_dir(tmp_path)

    rc = audit.main(["--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    payload = json.loads((shadow_dir / "shadow_price_model_audit_summary.json").read_text())
    assert rc == 0
    assert "trades_reviewed" in payload
    assert payload["tiny_live_recommendation"] == "NO"
    assert (shadow_dir / "shadow_price_model_audit.md").exists()


def test_dry_run_does_not_write_files(tmp_path: Path):
    shadow_dir = setup_shadow_dir(tmp_path)

    rc = audit.main(["--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir), "--dry_run"])

    assert rc == 0
    assert not (shadow_dir / "shadow_price_model_audit_summary.json").exists()
    assert not (shadow_dir / "shadow_price_model_audit.md").exists()


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/audit_shadow_price_model.py").read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")

    assert not any("live_trader" in name.lower() for name in imports)
    assert not any("paper_trader" in name.lower() for name in imports)
    assert not any("risk_governor" in name.lower() for name in imports)


def test_live_trading_enabled_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
