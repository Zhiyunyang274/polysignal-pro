"""Tests for Phase 7D daily report generation."""

from __future__ import annotations

import ast
import json
from argparse import Namespace
from pathlib import Path

import scripts.generate_daily_report as daily


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_run(runs_dir: Path, run_id: str, start_time: str, **overrides) -> Path:
    run_dir = runs_dir / run_id
    summary = {
        "run_id": run_id,
        "start_time": start_time,
        "status": "completed",
        "data_mode": "mock",
        "markets_checked": 10,
        "orderbooks_fetched": 9,
        "signals_generated": 1,
        "paper_trades_created": 0,
        "llm_calls": 2,
        "api_errors": 0,
        "websocket_messages": 3,
        "websocket_errors": 0,
    }
    summary.update(overrides)
    write_json(run_dir / "summary.json", summary)
    return run_dir


def make_args(runs_dir: Path, output_dir: Path, **overrides) -> Namespace:
    args = Namespace(
        runs_dir=str(runs_dir),
        output_dir=str(output_dir),
        latest_n=10,
        date=None,
        include_validation=True,
        include_intelligence=True,
        include_candidates=True,
        dry_run=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def seed_report_inputs(runs_dir: Path) -> None:
    make_run(runs_dir, "run_20260510_010000_a", "2026-05-10T01:00:00", markets_checked=5)
    make_run(runs_dir, "run_20260511_010000_b", "2026-05-11T01:00:00", markets_checked=15)
    write_json(
        runs_dir / "strategy_validation_summary.json",
        {
            "validation_timestamp": "2026-05-11T02:00:00",
            "q1_alpha_forward_change": {"conclusion_status": "preliminary_observed"},
            "q2_avoid_risk_validation": {
                "conclusion_status": "observed",
                "ambiguity_risk_delta": 9.0,
                "non_avoid_group_size": 21,
            },
        },
    )
    write_json(
        runs_dir / "intelligence_comparison_summary.json",
        {
            "summary_statistics": {
                "total_llm_samples": 8,
                "llm_success_rate": 0.875,
            }
        },
    )
    write_json(
        runs_dir / "validation_loop_summary.json",
        {
            "run_id": "run_20260511_010000_b",
            "run_success": True,
            "validation_success": True,
            "intelligence_success": True,
            "comparison_success": True,
        },
    )
    write_text(
        runs_dir / "alpha_candidates.csv",
        "market_id,question,category,appearances,alpha_score,evidence_level\n"
        "a1,Alpha one,Crypto,3,42.5,moderate\n"
        "a2,Alpha two,Sports,1,10.0,weak\n",
    )
    write_text(
        runs_dir / "avoid_candidates.csv",
        "market_id,question,category,appearances,avoid_score,evidence_level,reasons\n"
        "v1,Avoid one,Legal,4,55.0,strong,high_ambiguity\n",
    )
    write_text(
        runs_dir / "persistent_watchlist.csv",
        "market_id,question,category,appearances,suggested_mode_mode,evidence_level\n"
        "w1,Watch one,Gaming,5,research,strong\n",
    )


def test_discovers_recent_runs(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    make_run(runs_dir, "run_old", "2026-05-10T01:00:00")
    make_run(runs_dir, "run_new", "2026-05-11T01:00:00")

    runs = daily.discover_runs(runs_dir, latest_n=1)

    assert len(runs) == 1
    assert runs[0].run_id == "run_new"


def test_loads_summary_json(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    make_run(runs_dir, "run_a", "2026-05-11T01:00:00", markets_checked=12)

    runs = daily.discover_runs(runs_dir)

    assert runs[0].summary["markets_checked"] == 12


def test_loads_strategy_validation_summary(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    seed_report_inputs(runs_dir)

    data = daily.load_report_data(make_args(runs_dir, tmp_path / "out"))

    assert data.validation_summary["q1_alpha_forward_change"]["conclusion_status"] == "preliminary_observed"


def test_loads_intelligence_comparison_summary(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    seed_report_inputs(runs_dir)

    data = daily.load_report_data(make_args(runs_dir, tmp_path / "out"))

    assert data.intelligence_summary["summary_statistics"]["total_llm_samples"] == 8


def test_loads_candidate_csvs(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    seed_report_inputs(runs_dir)

    data = daily.load_report_data(make_args(runs_dir, tmp_path / "out"))

    assert data.alpha_candidates[0]["market_id"] == "a1"
    assert data.avoid_candidates[0]["market_id"] == "v1"
    assert data.watchlist[0]["market_id"] == "w1"


def test_missing_files_graceful_handling(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    make_run(runs_dir, "run_a", "2026-05-11T01:00:00")

    data = daily.load_report_data(make_args(runs_dir, tmp_path / "out"))
    summary = daily.aggregate_summary(data)

    assert summary["runs_analyzed"] == 1
    assert summary["q1_alpha_status"] is None
    assert summary["top_alpha_candidates"] == []


def test_daily_report_summary_json_format(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "out"
    seed_report_inputs(runs_dir)

    rc = daily.run(make_args(runs_dir, output_dir))
    payload = json.loads((output_dir / daily.DAILY_REPORT_JSON).read_text())

    assert rc == 0
    assert payload["runs_analyzed"] == 2
    assert payload["total_markets_checked"] == 20
    assert payload["q1_alpha_status"] == "preliminary_observed"
    assert "safety_verification" in payload


def test_daily_report_md_contains_safety_verification(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "out"
    seed_report_inputs(runs_dir)

    daily.run(make_args(runs_dir, output_dir))
    report = (output_dir / daily.DAILY_REPORT_MD).read_text()

    assert "## Safety Verification" in report
    assert "live_trading_enabled" in report


def test_alpha_disclaimer_exists(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "out"
    seed_report_inputs(runs_dir)

    daily.run(make_args(runs_dir, output_dir))
    report = (output_dir / daily.DAILY_REPORT_MD).read_text()

    assert "NOT trading signals" in report


def test_avoid_explanation_exists(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "out"
    seed_report_inputs(runs_dir)

    daily.run(make_args(runs_dir, output_dir))
    report = (output_dir / daily.DAILY_REPORT_MD).read_text()

    assert "NOT new hard rejects" in report


def test_no_forbidden_trading_imports():
    tree = ast.parse(Path(daily.__file__).read_text())
    forbidden = {"LiveTrader", "PaperTrader", "RiskGovernor"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[-1] not in forbidden
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or not any(name in node.module for name in forbidden)
            for alias in node.names:
                assert alias.name not in forbidden


def test_does_not_modify_config(tmp_path: Path):
    risk_path = Path("config/risk.yaml")
    llm_path = Path("config/llm.yaml")
    before = (risk_path.read_text(), llm_path.read_text())
    runs_dir = tmp_path / "runs"
    seed_report_inputs(runs_dir)

    daily.run(make_args(runs_dir, tmp_path / "out"))

    assert (risk_path.read_text(), llm_path.read_text()) == before


def test_dry_run_does_not_write_files(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "out"
    seed_report_inputs(runs_dir)

    rc = daily.run(make_args(runs_dir, output_dir, dry_run=True))

    assert rc == 0
    assert not (output_dir / daily.DAILY_REPORT_MD).exists()
    assert not (output_dir / daily.DAILY_REPORT_JSON).exists()


def test_date_filter(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    seed_report_inputs(runs_dir)

    data = daily.load_report_data(make_args(runs_dir, tmp_path / "out", date="2026-05-11"))

    assert len(data.runs) == 1
    assert data.runs[0].date == "2026-05-11"
