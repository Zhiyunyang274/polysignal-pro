"""Calibrate crypto_price_threshold_v1 feedback from real cohort validations.

Reads the validation shadow_trades.csv artifacts of the given cohort runs and
computes the feedback-gate metrics in the same shape as the Step-7 edge
feedback calibration summary (edge_type_performance, false-positive and
high-confidence-loss counts, correlations). Read-only; writes one summary json.

Per the house contract, this is the input to the feedback gate (ADR-028
cohorts, Iteration 025 merged data): v7_reeval + v10 + v11 = 16 closed trades.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RUNS = {
    "v7_reeval": "runs/crypto_threshold_shadow/reevals/step12_v7_20260804_140305/shadow_trades.csv",
    "v10": "runs/crypto_threshold_shadow/step12_v10_20260912/validation/shadow_trades.csv",
    "v11": "runs/crypto_threshold_shadow/step12_v11_20260912/validation/shadow_trades.csv",
}
EDGE_TYPE = "crypto_price_threshold_v1"
OUTPUT_PATH = Path("runs/crypto_threshold_feedback_calibration_summary.json")
HIGH_CONFIDENCE_THRESHOLD = 0.9


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if std_x == 0 or std_y == 0:
        return None
    return cov / (std_x * std_y)


def collect_closed_trades(runs: dict[str, str]) -> list[dict[str, Any]]:
    """Collect closed crypto_price_threshold_v1 trades from cohort artifacts."""
    closed: list[dict[str, Any]] = []
    for run_label, csv_path in runs.items():
        path = Path(csv_path)
        if not path.is_file():
            continue
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("edge_type") or "").strip() != EDGE_TYPE:
                    continue
                # closed = has a realized return (exit_side_price recorded);
                # open/insufficient rows carry blank returns and are skipped —
                # missing data stays null, never fabricated.
                return_pct = _safe_float(row.get("return_pct"))
                if return_pct is None:
                    continue
                expected_edge = _safe_float(row.get("expected_edge")) or 0.0
                confidence = _safe_float(row.get("confidence")) or 0.0
                closed.append(
                    {
                        "run": run_label,
                        "market_id": row.get("market_id") or "",
                        "expected_edge": expected_edge,
                        "confidence": confidence,
                        "return_pct": return_pct,
                        "pnl": _safe_float(row.get("pnl")) or 0.0,
                    }
                )
    return closed


def calibrate(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the Step-7-shaped feedback metrics from closed trades."""
    closed_count = len(closed)
    wins = [t for t in closed if t["return_pct"] > 0]
    losses = [t for t in closed if t["return_pct"] <= 0]
    returns = [t["return_pct"] for t in closed]
    false_positives = [t for t in closed if t["expected_edge"] > 0 and t["return_pct"] <= 0]
    high_confidence_losses = [
        t for t in closed if t["confidence"] >= HIGH_CONFIDENCE_THRESHOLD and t["return_pct"] <= 0
    ]
    edge_correlation = _pearson(
        [t["expected_edge"] for t in closed], [t["return_pct"] for t in closed]
    )
    confidence_correlation = _pearson(
        [t["confidence"] for t in closed], [1.0 if t["return_pct"] > 0 else 0.0 for t in closed]
    )

    return {
        "schema_version": "crypto_threshold_feedback_calibration_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "edge_types_analyzed": [EDGE_TYPE],
        "edge_type_performance": {
            EDGE_TYPE: {
                "trades": closed_count,
                "closed_trades": closed_count,
                "win_rate": (len(wins) / closed_count) if closed_count else 0.0,
                "average_return": (sum(returns) / closed_count) if closed_count else 0.0,
                "total_pnl": sum(t["pnl"] for t in closed),
            }
        },
        "overall_win_rate": (len(wins) / closed_count) if closed_count else 0.0,
        "overall_average_return": (sum(returns) / closed_count) if closed_count else 0.0,
        "expected_edge_realized_return_correlation": edge_correlation,
        "confidence_win_correlation": confidence_correlation,
        "false_positive_count": len(false_positives),
        "high_confidence_loss_count": len(high_confidence_losses),
        "per_trade": closed,
        "notes": [
            "Merged from v7_reeval + v10 + v11 validation artifacts (ADR-028 cohorts).",
            "Dollar-anchored expected_edge values come from discovery titles;",
            "realized returns are side-ask-entry to side-bid-exit per the v7 contract.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        nargs=2,
        metavar=("LABEL", "CSV"),
        default=None,
        help="run label and shadow_trades.csv path (default: v7_reeval+v10+v11)",
    )
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args()

    runs = dict(args.run) if args.run else DEFAULT_RUNS
    closed = collect_closed_trades(runs)
    summary = calibrate(closed)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "closed_trades": summary["edge_type_performance"][EDGE_TYPE]["closed_trades"],
                "win_rate": summary["edge_type_performance"][EDGE_TYPE]["win_rate"],
                "average_return": summary["edge_type_performance"][EDGE_TYPE]["average_return"],
                "false_positive_count": summary["false_positive_count"],
                "high_confidence_loss_count": summary["high_confidence_loss_count"],
                "output": str(output_path),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
