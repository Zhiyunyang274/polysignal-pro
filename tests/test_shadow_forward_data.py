"""Tests for Phase 8F.1 offline shadow forward observation collection."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.collect_shadow_forward_data as collector
from polysignal.shadow.models import SHADOW_TRADE_FIELDS


def write_shadow_trade(path: Path, **overrides) -> dict[str, str]:
    row = {
        "shadow_trade_id": "shadow_1",
        "market_id": "m1",
        "question": "Will test happen?",
        "side": "YES",
        "entry_time": "2026-05-11T00:00:00",
        "entry_price": "1.0",
        "entry_reason": "tradable_candidate_evidence_passed",
        "tradable_score": "20",
        "alpha_score": "0",
        "combined_ask": "1.0",
        "liquidity_score": "3",
        "ambiguity_risk": "10",
        "risk_decision": "allow_shadow",
        "exit_time": "",
        "exit_price": "",
        "exit_reason": "open",
        "pnl": "0",
        "return_pct": "0",
        "status": "insufficient_forward_data",
        "run_id": "",
        "category": "Sports",
        "source": "control_group",
        "evidence_level": "control_group",
        "near_miss_tier": "",
        "orderbook_spread": "0.01",
        "orderbook_depth": "3",
        "max_adverse_excursion": "0",
        "max_favorable_excursion": "0",
        "holding_minutes": "0",
    }
    row.update(overrides)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHADOW_TRADE_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return row


def write_positions(path: Path) -> None:
    path.write_text(json.dumps({
        "generated_at": "2026-05-11T00:00:00",
        "open_positions": [],
        "closed_positions": [],
        "insufficient_forward_data_positions": [],
    }))


def setup_shadow_dir(tmp_path: Path) -> tuple[Path, Path]:
    runs_dir = tmp_path / "runs"
    shadow_dir = runs_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    write_shadow_trade(shadow_dir / "shadow_trades.csv")
    write_positions(shadow_dir / "shadow_positions.json")
    return runs_dir, shadow_dir


def write_trajectory(runs_dir: Path, price: float = 1.06, **obs_overrides) -> None:
    observation = {
        "timestamp": "2026-05-11T01:00:00",
        "combined_ask": price,
        "spread": 0.01,
        "liquidity": 3,
        "run_id": "run_a",
    }
    observation.update(obs_overrides)
    (runs_dir / "market_trajectories.json").write_text(json.dumps([
        {
            "market_id": "m1",
            "question": "Will test happen?",
            "category": "Sports",
            "trajectory": [observation],
        }
    ]))


def test_can_read_shadow_positions_json(tmp_path: Path):
    _, shadow_dir = setup_shadow_dir(tmp_path)

    payload = collector.load_json(shadow_dir / "shadow_positions.json")

    assert "insufficient_forward_data_positions" in payload


def test_can_read_shadow_trades_csv(tmp_path: Path):
    _, shadow_dir = setup_shadow_dir(tmp_path)

    trades = collector.load_shadow_trades(shadow_dir / "shadow_trades.csv")

    assert len(trades) == 1
    assert trades[0].shadow_trade_id == "shadow_1"


def test_can_read_market_trajectories_json(tmp_path: Path):
    runs_dir, _ = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir)

    index = collector.build_trajectory_index(collector.load_json(runs_dir / "market_trajectories.json"))

    assert "m1" in index
    assert index["m1"][0]["combined_ask"] == 1.06


def test_generates_forward_observations_jsonl(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir)

    rc = collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])

    assert rc == 0
    text = (shadow_dir / "forward_observations.jsonl").read_text()
    assert "observed_price" in text


def test_forward_data_closes_position(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir, price=1.06)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary = json.loads((shadow_dir / "paper_performance_summary.json").read_text())

    assert summary["closed_positions"] == 1
    assert summary["insufficient_forward_data_positions"] == 0
    assert summary["total_pnl"] > 0


def test_no_forward_data_remains_insufficient(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary = json.loads((shadow_dir / "paper_performance_summary.json").read_text())
    positions = json.loads((shadow_dir / "updated_shadow_positions.json").read_text())

    assert summary["closed_positions"] == 0
    assert summary["insufficient_forward_data_positions"] == 1
    assert positions["insufficient_forward_data_positions"][0]["exit_price"] is None


def test_no_forward_data_does_not_forge_exit_or_pnl(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    trade = json.loads((shadow_dir / "updated_shadow_positions.json").read_text())[
        "insufficient_forward_data_positions"
    ][0]

    assert trade["exit_price"] is None
    assert trade["pnl"] == 0.0
    assert trade["return_pct"] == 0.0


def test_fixed_horizon_exit(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir, price=1.01, timestamp="2026-05-11T05:00:00")

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    rows = list(csv.DictReader(open(shadow_dir / "updated_shadow_trades.csv")))

    assert rows[0]["exit_reason"] == "fixed_horizon"


def test_stop_loss_exit(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir, price=0.94)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    rows = list(csv.DictReader(open(shadow_dir / "updated_shadow_trades.csv")))

    assert rows[0]["exit_reason"] == "stop_loss"


def test_take_profit_exit(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir, price=1.06)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    rows = list(csv.DictReader(open(shadow_dir / "updated_shadow_trades.csv")))

    assert rows[0]["exit_reason"] == "take_profit"


def test_stale_data_exit(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir, price=1.01, stale=True)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    rows = list(csv.DictReader(open(shadow_dir / "updated_shadow_trades.csv")))

    assert rows[0]["exit_reason"] == "stale_data"


def test_market_close_exit(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir, price=1.01, market_closed=True)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    rows = list(csv.DictReader(open(shadow_dir / "updated_shadow_trades.csv")))

    assert rows[0]["exit_reason"] == "market_close"


def test_updated_shadow_outputs_format(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])

    assert "shadow_trade_id,market_id,question" in (shadow_dir / "updated_shadow_trades.csv").read_text()
    positions = json.loads((shadow_dir / "updated_shadow_positions.json").read_text())
    assert "closed_positions" in positions
    assert "insufficient_forward_data_positions" in positions


def test_summary_and_report_regenerated(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)

    collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary = json.loads((shadow_dir / "paper_performance_summary.json").read_text())
    report = (shadow_dir / "paper_performance_report.md").read_text()

    assert "forward_data_limitation" in summary
    assert "Forward data limitation" in report
    assert "Shadow performance is hypothetical" in report


def test_dry_run_does_not_write(tmp_path: Path, capsys):
    runs_dir, shadow_dir = setup_shadow_dir(tmp_path)
    write_trajectory(runs_dir)

    rc = collector.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--dry_run"])
    output = capsys.readouterr().out

    assert rc == 0
    assert "positions_would_close: 1" in output
    assert not (shadow_dir / "updated_shadow_trades.csv").exists()


def test_no_forbidden_trading_imports():
    files = [
        Path("polysignal/shadow/forward_observations.py"),
        Path("scripts/collect_shadow_forward_data.py"),
    ]
    forbidden = {"LiveTrader", "PaperTrader", "RiskGovernor"}

    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[-1] not in forbidden
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not any(name in node.module for name in forbidden)
                for alias in node.names:
                    assert alias.name not in forbidden


def test_live_trading_enabled_still_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
