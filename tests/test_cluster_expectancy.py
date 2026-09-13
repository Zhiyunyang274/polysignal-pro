"""
Tests for merged cluster expectancy (Iteration 025).

The verdict contract: expectancy statements require >= 20 closed positions
AND >= 5 independent clusters; otherwise "sample insufficient" with no
profitability claim.
"""

import json
from pathlib import Path

import pytest

from polysignal.research.cluster_expectancy import merge_expectancy


def write_summary(
    path: Path,
    *,
    total: int,
    closed: int,
    insufficient: int,
    pnl: float,
    win_rate: float,
    asset_perf: dict,
) -> Path:
    summary = {
        "cluster_policy": "asset_expiry_contract_kind_v1",
        "performance": {
            "total_positions": total,
            "closed_positions": closed,
            "insufficient_forward_data_positions": insufficient,
            "total_pnl_usd": pnl,
            "win_rate": win_rate,
            "asset_performance": asset_perf,
        },
    }
    path.write_text(json.dumps(summary), encoding="utf-8")
    return path


def asset_perf(asset: str, positions: int, closed: int, pnl: float) -> dict:
    return {asset: {"positions": positions, "closed_positions": closed, "total_pnl_usd": pnl}}


class TestMergeExpectancy:
    def test_sample_insufficient_with_few_clusters(self, tmp_path: Path):
        a = write_summary(
            tmp_path / "a.json", total=4, closed=0, insufficient=4, pnl=0.0,
            win_rate=0.0, asset_perf=asset_perf("ETH", 4, 0, 0.0),
        )
        merged = merge_expectancy({"v10": a})
        assert merged.verdict == "SAMPLE_INSUFFICIENT"
        assert merged.independent_cluster_count == 1
        assert merged.meets_sample_precondition is False
        assert merged.meets_cluster_precondition is False

    def test_five_clusters_but_under_20_closed(self, tmp_path: Path):
        summaries = {}
        perf = {
            "BTC": (4, 3, -1.0),
            "ETH": (4, 4, -2.0),
            "SOL": (4, 3, -0.5),
            "XRP": (2, 2, -0.4),
            "DOGE": (2, 1, -0.3),
        }
        total_closed = sum(c for _, c, _ in perf.values())
        for i, (asset, (total, closed, pnl)) in enumerate(perf.items()):
            summaries[f"run{i}"] = write_summary(
                tmp_path / f"run{i}.json", total=total, closed=closed,
                insufficient=total - closed, pnl=pnl, win_rate=0.3,
                asset_perf=asset_perf(asset, total, closed, pnl),
            )
        merged = merge_expectancy(summaries)
        assert merged.independent_cluster_count == 5
        assert merged.meets_cluster_precondition is True
        assert merged.closed_positions == total_closed
        assert merged.closed_positions < 20
        assert merged.verdict == "SAMPLE_INSUFFICIENT"
        assert any("closed positions" in note for note in merged.notes)

    def test_five_clusters_and_20_closed_permits_statement(self, tmp_path: Path):
        summaries = {}
        plan = {
            "BTC": (6, 6, -2.0),
            "ETH": (6, 5, -1.0),
            "SOL": (4, 3, -0.5),
            "XRP": (3, 2, -0.4),
            "DOGE": (3, 2, -0.3),
            "BNB": (2, 2, -0.2),
        }
        for i, (asset, (total, closed, pnl)) in enumerate(plan.items()):
            summaries[f"run{i}"] = write_summary(
                tmp_path / f"run{i}.json", total=total, closed=closed,
                insufficient=total - closed, pnl=pnl, win_rate=0.3,
                asset_perf=asset_perf(asset, total, closed, pnl),
            )
        merged = merge_expectancy(summaries)
        assert merged.independent_cluster_count == 6
        assert merged.closed_positions == 20
        assert merged.verdict == "STATEMENT_PERMITTED"

    def test_totals_accumulate_across_runs(self, tmp_path: Path):
        a = write_summary(
            tmp_path / "a.json", total=4, closed=2, insufficient=2, pnl=-1.5,
            win_rate=0.5, asset_perf=asset_perf("ETH", 4, 2, -1.5),
        )
        b = write_summary(
            tmp_path / "b.json", total=8, closed=6, insufficient=2, pnl=-2.8,
            win_rate=0.33, asset_perf=asset_perf("ETH", 8, 6, -2.8),
        )
        merged = merge_expectancy({"v7": a, "v10": b})
        assert merged.total_positions == 12
        assert merged.closed_positions == 8
        assert merged.total_pnl_usd == pytest.approx(-4.3)
        # same asset+expiry family across runs -> ONE cluster bucket
        assert merged.independent_cluster_count == 1

    def test_wins_derived_from_win_rate_times_closed(self, tmp_path: Path):
        a = write_summary(
            tmp_path / "a.json", total=6, closed=6, insufficient=0, pnl=1.0,
            win_rate=0.5, asset_perf=asset_perf("BTC", 6, 6, 1.0),
        )
        merged = merge_expectancy({"v7": a})
        assert merged.wins == 3
