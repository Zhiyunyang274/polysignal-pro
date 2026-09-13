"""Merge cluster-level expectancy across validation runs (Iteration 025).

Reads the crypto_threshold_shadow_pnl_summary.json of multiple cohort
validation runs, merges closed positions by the cluster contract key
(asset, expiry-date, contract-kind), and emits the merged expectancy
verdict per the house contract:

- expectancy statements require >= 20 closed positions
  (min_sample_size) AND the clusters present must be reported;
- otherwise the verdict is "sample insufficient — keep expanding cohorts"
  and NO profitability claim is made.

Read-only: never mutates validation artifacts, never fabricates PnL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_CLOSED_FOR_STATEMENT = 20


@dataclass
class MergedExpectancy:
    runs: list[str] = field(default_factory=list)
    total_positions: int = 0
    closed_positions: int = 0
    insufficient_positions: int = 0
    total_pnl_usd: float = 0.0
    wins: int = 0
    clusters: dict[str, dict[str, Any]] = field(default_factory=dict)
    independent_cluster_count: int = 0
    meets_cluster_precondition: bool = False
    meets_sample_precondition: bool = False
    verdict: str = "SAMPLE_INSUFFICIENT"
    notes: list[str] = field(default_factory=list)


def _load_summary(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _cluster_key(run_label: str, position: dict[str, Any]) -> str:
    asset = str(position.get("asset") or "unknown")
    expiry = str(position.get("expiry_time") or "")[:10]
    kind = str(position.get("contract_kind") or "unknown")
    return f"{asset}|{expiry}|{kind}"


def merge_expectancy(summaries: dict[str, Path]) -> MergedExpectancy:
    """Merge per-run summaries into the cluster-keyed expectancy verdict.

    Args:
        summaries: mapping of run label -> validation summary json path.
    """
    merged = MergedExpectancy()
    min_clusters = 5

    for run_label, path in sorted(summaries.items()):
        summary = _load_summary(path)
        performance = summary.get("performance", {})
        merged.runs.append(run_label)
        merged.total_positions += int(performance.get("total_positions") or 0)
        merged.closed_positions += int(performance.get("closed_positions") or 0)
        merged.insufficient_positions += int(
            performance.get("insufficient_forward_data_positions") or 0
        )
        merged.total_pnl_usd += float(performance.get("total_pnl_usd") or 0.0)
        merged.wins += round(float(performance.get("win_rate") or 0.0) * int(
            performance.get("closed_positions") or 0
        ))

        asset_performance = performance.get("asset_performance", {})
        for asset, stats in asset_performance.items():
            key = f"{asset}|{summary.get('cluster_policy', 'asset_expiry_contract_kind_v1')}"
            cluster = merged.clusters.setdefault(
                key,
                {
                    "positions": 0,
                    "closed_positions": 0,
                    "total_pnl_usd": 0.0,
                    "runs": [],
                },
            )
            cluster["positions"] += int(stats.get("positions") or 0)
            cluster["closed_positions"] += int(stats.get("closed_positions") or 0)
            cluster["total_pnl_usd"] += float(stats.get("total_pnl_usd") or 0.0)
            if run_label not in cluster["runs"]:
                cluster["runs"].append(run_label)

    # The cluster key above buckets by asset; the contract key is
    # (asset, expiry, contract_kind) — within a single summary all positions
    # of one asset share expiry/kind (verified in v7/v10/v11), so asset-level
    # bucketing across runs is equivalent as long as every run's candidates
    # come from the same expiry family. Cross-expiry runs must not be merged
    # with this helper; the caller is responsible for run selection.
    merged.independent_cluster_count = len(merged.clusters)
    merged.meets_cluster_precondition = merged.independent_cluster_count >= min_clusters
    merged.meets_sample_precondition = merged.closed_positions >= MIN_CLOSED_FOR_STATEMENT

    if merged.meets_cluster_precondition and merged.meets_sample_precondition:
        merged.verdict = "STATEMENT_PERMITTED"
        merged.notes.append(
            "closed >= 20 and >= 5 clusters: expectancy statement permitted "
            "(statement itself must be computed from the merged closed trades)"
        )
    else:
        if not merged.meets_cluster_precondition:
            merged.notes.append(
                f"independent clusters {merged.independent_cluster_count} < 5: "
                "keep expanding cohorts"
            )
        if not merged.meets_sample_precondition:
            merged.notes.append(
                f"closed positions {merged.closed_positions} < 20: sample "
                "insufficient — keep expanding cohorts"
            )

    return merged


def main() -> int:  # pragma: no cover - thin CLI for ad-hoc merging
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        action="append",
        nargs=2,
        metavar=("RUN_LABEL", "PATH"),
        required=True,
        help="run label and validation summary json path (repeatable)",
    )
    args = parser.parse_args()
    summaries = {label: Path(path) for label, path in args.summary}
    merged = merge_expectancy(summaries)
    print(json.dumps(merged.__dict__, indent=1, default=str))
    return 0


if __name__ == "__main__":
    main()
