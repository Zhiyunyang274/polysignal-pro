#!/usr/bin/env python3
"""
Phase 6 — Strategy Signal Validation

Offline analysis to validate whether alpha_candidates, avoid_candidates,
and persistent_watchlist have research value based on historical run data.

IMPORTANT SAFETY CONSTRAINTS:
- READ-ONLY: Does NOT trigger trades, modify config, or call real APIs
- Does NOT import LiveTrader, PaperTrader, RiskGovernor
- Does NOT access private keys or authenticated endpoints
- live_trading_enabled remains false
- All outputs are research annotations, NOT trading signals

Usage:
    python3 scripts/validate_strategy_signals.py --runs_dir runs --output_dir runs
    python3 scripts/validate_strategy_signals.py --min_appearances 3
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# =============================================================================
# SAFETY: This module does NOT import trading modules.
# The following are intentionally NOT imported:
# - polysignal.execution.live_trader
# - polysignal.execution.paper_trader
# - polysignal.risk.risk_governor
# - Any authenticated CLOB module
# - Any wallet / private key module
# =============================================================================

MIN_OBSERVATIONS_FOR_TREND = 3

# Alpha observation conclusion levels (Phase 6.5B)
# 1 observation: insufficient_data
# 2 observations: weak_descriptive
# 3-4 observations: preliminary_observed
# >=5 observations: stronger_observed


def _get_alpha_conclusion_status(num_observations: int) -> str:
    """
    Determine alpha conclusion status based on observation count.

    IMPORTANT: These are descriptive categories, NOT statistical proofs.
    """
    if num_observations < 1:
        return "insufficient_data"
    elif num_observations == 1:
        return "insufficient_data"
    elif num_observations == 2:
        return "weak_descriptive"
    elif num_observations <= 4:
        return "preliminary_observed"
    else:
        return "stronger_observed"

ALPHA_DISCLAIMER = (
    "Alpha score is a heuristic research ranking, NOT a trading signal. "
    "Candidates require further paper trading validation before any execution."
)

VALIDATION_DISCLAIMER = (
    "Phase 6 validation uses limited historical data (48h, ~20 markets). "
    "conclusion_status values are descriptive observations, not statistical proofs. "
    "No trading decisions should be based on these results."
)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AlphaForwardChange:
    """Forward change analysis for a single alpha candidate."""

    market_id: str
    question: str
    alpha_score: float
    evidence_level: str
    first_combined_ask: Optional[float] = None
    last_combined_ask: Optional[float] = None
    min_combined_ask: Optional[float] = None
    max_combined_ask: Optional[float] = None
    delta: Optional[float] = None
    slope: Optional[float] = None
    num_observations: int = 0
    conclusion_status: str = "insufficient_data"
    note: str = ""


@dataclass
class WatchlistPersistence:
    """Persistence analysis for a single watchlist market."""

    market_id: str
    question: str
    evidence_level: str
    total_appearances: int = 0
    near_miss_hits: int = 0
    persistence_score: float = 0.0
    avg_combined_ask: Optional[float] = None
    avg_event_score: Optional[float] = None
    conclusion_status: str = "insufficient_data"
    note: str = ""


@dataclass
class AvoidRiskValidation:
    """Risk validation for a single avoid candidate."""

    market_id: str
    question: str
    avoid_score: float
    reasons: str
    avg_ambiguity_risk: Optional[float] = None
    category_risk: Optional[float] = None
    avg_event_score: Optional[float] = None
    suggested_mode: str = ""
    conclusion_status: str = "insufficient_data"
    note: str = ""


@dataclass
class AvoidGroupComparison:
    """Comparison between avoid group and non-avoid control group."""

    avoid_group_size: int = 0
    non_avoid_group_size: int = 0
    avoid_avg_ambiguity_risk: Optional[float] = None
    non_avoid_avg_ambiguity_risk: Optional[float] = None
    ambiguity_risk_delta: Optional[float] = None
    avoid_avg_event_score: Optional[float] = None
    non_avoid_avg_event_score: Optional[float] = None
    conclusion_status: str = "insufficient_data"
    note: str = ""


@dataclass
class CategoryPerformance:
    """Per-category signal quality statistics."""

    category: str
    market_count: int = 0
    avg_alpha_score: Optional[float] = None
    avg_avoid_score: Optional[float] = None
    avg_ambiguity_risk: Optional[float] = None
    near_miss_frequency: float = 0.0
    conclusion_status: str = "insufficient_data"


# =============================================================================
# Data Loader
# =============================================================================


class ValidationDataLoader:
    """Load all data needed for strategy signal validation."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir

    def discover_runs(self) -> list[str]:
        """Discover all run directories with summary.json."""
        if not self.runs_dir.exists():
            return []
        run_ids = []
        for item in self.runs_dir.iterdir():
            if item.is_dir() and item.name.startswith("run_"):
                if (item / "summary.json").exists():
                    run_ids.append(item.name)
        run_ids.sort()
        return run_ids

    def load_run_summary(self, run_id: str) -> Optional[dict[str, Any]]:
        """Load summary.json for a run."""
        path = self.runs_dir / run_id / "summary.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def load_llm_sampling_events(self, run_id: str) -> list[dict[str, Any]]:
        """Load llm_sampling_assessment events from events.jsonl."""
        path = self.runs_dir / run_id / "events.jsonl"
        if not path.exists():
            return []
        events = []
        try:
            for line in path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                evt = json.loads(line)
                if evt.get("event_type") == "llm_sampling_assessment":
                    events.append(evt)
        except Exception:
            pass
        return events

    def load_all_llm_events(self) -> list[dict[str, Any]]:
        """Load all llm_sampling_assessment events across all runs."""
        all_events = []
        for run_id in self.discover_runs():
            all_events.extend(self.load_llm_sampling_events(run_id))
        return all_events

    def load_alpha_candidates(self) -> list[dict[str, Any]]:
        """Load alpha_candidates.csv."""
        path = self.runs_dir / "alpha_candidates.csv"
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception:
            return []

    def load_avoid_candidates(self) -> list[dict[str, Any]]:
        """Load avoid_candidates.csv."""
        path = self.runs_dir / "avoid_candidates.csv"
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception:
            return []

    def load_persistent_watchlist(self) -> list[dict[str, Any]]:
        """Load persistent_watchlist.csv."""
        path = self.runs_dir / "persistent_watchlist.csv"
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception:
            return []

    def load_trajectories(self) -> list[dict[str, Any]]:
        """Load market_trajectories.json."""
        path = self.runs_dir / "market_trajectories.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def load_comparison_summary(self) -> Optional[dict[str, Any]]:
        """Load intelligence_comparison_summary.json."""
        path = self.runs_dir / "intelligence_comparison_summary.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def load_control_group_samples(self) -> list[dict[str, Any]]:
        """Load control_group_samples.csv from all run directories."""
        all_samples: list[dict[str, Any]] = []
        for run_id in self.discover_runs():
            path = self.runs_dir / run_id / "control_group_samples.csv"
            if not path.exists():
                continue
            try:
                with open(path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        all_samples.append(row)
            except Exception:
                continue
        return all_samples


# =============================================================================
# Validators
# =============================================================================


class AlphaValidator:
    """Validate alpha candidates against trajectory data."""

    def validate(
        self,
        alpha_candidates: list[dict[str, Any]],
        trajectories: list[dict[str, Any]],
        llm_events: list[dict[str, Any]],
        min_appearances: int = 2,
    ) -> list[AlphaForwardChange]:
        """Compute forward change for each alpha candidate."""
        # Build trajectory lookup by market_id
        traj_by_id: dict[str, dict[str, Any]] = {}
        for t in trajectories:
            mid = str(t.get("market_id", ""))
            traj_by_id[mid] = t

        # Build LLM event lookup by market_id
        event_by_id: dict[str, list[dict[str, Any]]] = {}
        for evt in llm_events:
            details = evt.get("details") or {}
            mid = str(details.get("market_id", ""))
            if mid:
                event_by_id.setdefault(mid, []).append(evt)

        results: list[AlphaForwardChange] = []
        for cand in alpha_candidates:
            mid = str(cand.get("market_id", ""))
            question = cand.get("question", "")
            alpha_score = _safe_float(cand.get("alpha_score"), 0.0)
            evidence_level = cand.get("evidence_level", "unknown")

            result = AlphaForwardChange(
                market_id=mid,
                question=question,
                alpha_score=alpha_score,
                evidence_level=evidence_level,
            )

            # Try trajectory data first
            traj = traj_by_id.get(mid)
            if traj and traj.get("trajectory"):
                obs = traj["trajectory"]
                asks = [_safe_float(o.get("combined_ask")) for o in obs if o.get("combined_ask") is not None]
                if asks:
                    result.first_combined_ask = asks[0]
                    result.last_combined_ask = asks[-1]
                    result.min_combined_ask = min(asks)
                    result.max_combined_ask = max(asks)
                    result.delta = asks[-1] - asks[0]
                    result.num_observations = len(asks)
                    if len(asks) >= 2:
                        result.slope = _compute_slope(asks)
                    result.conclusion_status = _get_alpha_conclusion_status(len(asks))
                    if result.conclusion_status in ("preliminary_observed", "stronger_observed"):
                        result.note = f"Trend over {len(asks)} observations"
                    else:
                        result.note = f"Only {len(asks)} observations; descriptive tier={result.conclusion_status}"
            else:
                # Fallback: try LLM events
                events = event_by_id.get(mid, [])
                if events:
                    asks = []
                    for evt in events:
                        details = evt.get("details") or {}
                        ca = details.get("combined_ask")
                        if ca is not None:
                            asks.append(_safe_float(ca))
                    if asks:
                        result.first_combined_ask = asks[0]
                        result.last_combined_ask = asks[-1]
                        result.min_combined_ask = min(asks)
                        result.max_combined_ask = max(asks)
                        result.delta = asks[-1] - asks[0]
                        result.num_observations = len(asks)
                        if len(asks) >= 2:
                            result.slope = _compute_slope(asks)
                        result.conclusion_status = _get_alpha_conclusion_status(len(asks))
                        result.note = "LLM event observations only; descriptive, not statistical proof"
                else:
                    result.conclusion_status = "insufficient_data"
                    result.note = "No trajectory or LLM event data found"

            results.append(result)

        return results


class WatchlistValidator:
    """Validate watchlist markets for persistence."""

    def validate(
        self,
        watchlist: list[dict[str, Any]],
        trajectories: list[dict[str, Any]],
        min_appearances: int = 2,
    ) -> list[WatchlistPersistence]:
        """Compute persistence score for each watchlist market."""
        traj_by_id: dict[str, dict[str, Any]] = {}
        for t in trajectories:
            mid = str(t.get("market_id", ""))
            traj_by_id[mid] = t

        results: list[WatchlistPersistence] = []
        for wl in watchlist:
            mid = str(wl.get("market_id", ""))
            question = wl.get("question", "")
            evidence_level = wl.get("evidence_level", "unknown")

            result = WatchlistPersistence(
                market_id=mid,
                question=question,
                evidence_level=evidence_level,
            )

            traj = traj_by_id.get(mid)
            if traj and traj.get("trajectory"):
                obs = traj["trajectory"]
                result.total_appearances = len(obs)

                # Near-miss: combined_ask <= 1.03 (tier1-3 threshold)
                near_miss_count = sum(
                    1 for o in obs
                    if o.get("combined_ask") is not None
                    and _safe_float(o["combined_ask"]) <= 1.03
                )
                result.near_miss_hits = near_miss_count
                result.persistence_score = near_miss_count / len(obs) if obs else 0.0

                asks = [_safe_float(o["combined_ask"]) for o in obs if o.get("combined_ask") is not None]
                scores = [_safe_float(o["event_score"]) for o in obs if o.get("event_score") is not None]
                result.avg_combined_ask = sum(asks) / len(asks) if asks else None
                result.avg_event_score = sum(scores) / len(scores) if scores else None

                if len(obs) >= min_appearances:
                    result.conclusion_status = "observed"
                    result.note = f"Persistence {result.persistence_score:.0%} over {len(obs)} appearances"
                else:
                    result.conclusion_status = "insufficient_data"
                    result.note = f"Only {len(obs)} appearances, need >= {min_appearances}"
            else:
                result.conclusion_status = "insufficient_data"
                result.note = "No trajectory data found"

            results.append(result)

        return results


class AvoidValidator:
    """Validate avoid candidates against control group."""

    def validate_single(
        self,
        candidate: dict[str, Any],
        all_events: list[dict[str, Any]],
    ) -> AvoidRiskValidation:
        """Validate a single avoid candidate."""
        mid = str(candidate.get("market_id", ""))
        question = candidate.get("question", "")
        avoid_score = _safe_float(candidate.get("avoid_score"), 0.0)
        reasons = candidate.get("reasons", "")
        avg_ambiguity = _safe_float(candidate.get("avg_ambiguity_risk"))
        cat_risk = _safe_float(candidate.get("category_risk"))

        result = AvoidRiskValidation(
            market_id=mid,
            question=question,
            avoid_score=avoid_score,
            reasons=reasons,
            avg_ambiguity_risk=avg_ambiguity,
            category_risk=cat_risk,
        )

        # Find matching LLM events for this market
        matching = [
            evt.get("details", {})
            for evt in all_events
            if str((evt.get("details") or {}).get("market_id", "")) == mid
        ]
        if matching:
            scores = [_safe_float(d.get("event_score")) for d in matching if d.get("event_score") is not None]
            modes = [d.get("suggested_mode", "") for d in matching if d.get("suggested_mode")]
            result.avg_event_score = sum(scores) / len(scores) if scores else None
            result.suggested_mode = modes[0] if modes else ""
            result.conclusion_status = "observed"
            result.note = f"suggested_mode={result.suggested_mode}"
        else:
            result.conclusion_status = "insufficient_data"
            result.note = "No LLM event data for this market"

        return result

    def validate_group_comparison(
        self,
        avoid_candidates: list[dict[str, Any]],
        all_events: list[dict[str, Any]],
        control_group_samples: Optional[list[dict[str, Any]]] = None,
    ) -> AvoidGroupComparison:
        """Compare avoid group vs non-avoid control group.

        If control_group_samples is provided (from control_group_samples.csv),
        those are used as the non-avoid control group data. Otherwise, falls
        back to using LLM events not in avoid_candidates.
        """
        comparison = AvoidGroupComparison()

        # Build avoid market set
        avoid_ids = {str(c.get("market_id", "")) for c in avoid_candidates}
        comparison.avoid_group_size = len(avoid_ids)

        # Collect all market data from LLM events
        market_data: dict[str, dict[str, Any]] = {}
        for evt in all_events:
            details = evt.get("details") or {}
            mid = str(details.get("market_id", ""))
            if not mid:
                continue
            if mid not in market_data:
                market_data[mid] = {
                    "ambiguity_risks": [],
                    "event_scores": [],
                }
            ar = details.get("ambiguity_risk")
            if ar is not None:
                market_data[mid]["ambiguity_risks"].append(_safe_float(ar))
            es = details.get("event_score")
            if es is not None:
                market_data[mid]["event_scores"].append(_safe_float(es))

        # Split into avoid and non-avoid groups
        avoid_ambiguity = []
        avoid_escores = []
        non_avoid_ambiguity = []
        non_avoid_escores = []

        for mid, data in market_data.items():
            avg_ar = (
                sum(data["ambiguity_risks"]) / len(data["ambiguity_risks"])
                if data["ambiguity_risks"]
                else None
            )
            avg_es = (
                sum(data["event_scores"]) / len(data["event_scores"])
                if data["event_scores"]
                else None
            )
            if mid in avoid_ids:
                if avg_ar is not None:
                    avoid_ambiguity.append(avg_ar)
                if avg_es is not None:
                    avoid_escores.append(avg_es)
            else:
                # Non-avoid control group: observed markets not in avoid_candidates
                if avg_ar is not None:
                    non_avoid_ambiguity.append(avg_ar)
                if avg_es is not None:
                    non_avoid_escores.append(avg_es)

        # Phase 6.5A: Merge control_group_samples into non-avoid group
        if control_group_samples:
            cg_market_data: dict[str, dict[str, Any]] = {}
            for sample in control_group_samples:
                mid = str(sample.get("market_id", ""))
                if not mid or mid in avoid_ids:
                    continue
                if mid not in cg_market_data:
                    cg_market_data[mid] = {"ambiguity_risks": [], "event_scores": []}
                ar = sample.get("ambiguity_risk")
                if ar is not None:
                    cg_market_data[mid]["ambiguity_risks"].append(_safe_float(ar))
                es = sample.get("event_score")
                if es is not None:
                    cg_market_data[mid]["event_scores"].append(_safe_float(es))

            for mid, data in cg_market_data.items():
                avg_ar = (
                    sum(data["ambiguity_risks"]) / len(data["ambiguity_risks"])
                    if data["ambiguity_risks"]
                    else None
                )
                avg_es = (
                    sum(data["event_scores"]) / len(data["event_scores"])
                    if data["event_scores"]
                    else None
                )
                # Only add if not already in non_avoid from LLM events
                # (avoid double-counting markets that appear in both)
                if mid not in market_data:
                    if avg_ar is not None:
                        non_avoid_ambiguity.append(avg_ar)
                    if avg_es is not None:
                        non_avoid_escores.append(avg_es)

        comparison.non_avoid_group_size = len(non_avoid_ambiguity)

        if avoid_ambiguity:
            comparison.avoid_avg_ambiguity_risk = sum(avoid_ambiguity) / len(avoid_ambiguity)
        if non_avoid_ambiguity:
            comparison.non_avoid_avg_ambiguity_risk = sum(non_avoid_ambiguity) / len(non_avoid_ambiguity)
        if avoid_escores:
            comparison.avoid_avg_event_score = sum(avoid_escores) / len(avoid_escores)
        if non_avoid_escores:
            comparison.non_avoid_avg_event_score = sum(non_avoid_escores) / len(non_avoid_escores)

        if (
            comparison.avoid_avg_ambiguity_risk is not None
            and comparison.non_avoid_avg_ambiguity_risk is not None
        ):
            comparison.ambiguity_risk_delta = (
                comparison.avoid_avg_ambiguity_risk - comparison.non_avoid_avg_ambiguity_risk
            )

        # Determine conclusion
        if comparison.non_avoid_group_size < 3:
            comparison.conclusion_status = "insufficient_control_group"
            comparison.note = (
                f"Non-avoid control group size ({comparison.non_avoid_group_size}) "
                f"too small for comparison. Need >= 3."
            )
        elif not avoid_ambiguity:
            comparison.conclusion_status = "insufficient_data"
            comparison.note = "No ambiguity data available for avoid group"
        else:
            comparison.conclusion_status = "observed"
            comparison.note = (
                f"Avoid group ({comparison.avoid_group_size}) vs "
                f"non-avoid ({comparison.non_avoid_group_size}): "
                f"ambiguity delta = {comparison.ambiguity_risk_delta:+.1f}"
            )

        return comparison


class CategoryValidator:
    """Per-category signal quality analysis."""

    def validate(
        self,
        alpha_candidates: list[dict[str, Any]],
        avoid_candidates: list[dict[str, Any]],
        llm_events: list[dict[str, Any]],
    ) -> list[CategoryPerformance]:
        """Compute per-category performance metrics."""
        # Build category lookup from LLM events
        market_categories: dict[str, str] = {}
        market_ambiguity: dict[str, list[float]] = {}
        for evt in llm_events:
            details = evt.get("details") or {}
            mid = str(details.get("market_id", ""))
            # Category not in events, use question-based heuristic
            question = details.get("question", "")
            cat = _infer_category(question)
            if mid:
                market_categories[mid] = cat
                ar = details.get("ambiguity_risk")
                if ar is not None:
                    market_ambiguity.setdefault(mid, []).append(_safe_float(ar))

        # Aggregate by category
        cat_data: dict[str, dict[str, Any]] = {}
        for mid, cat in market_categories.items():
            if cat not in cat_data:
                cat_data[cat] = {
                    "market_ids": set(),
                    "alpha_scores": [],
                    "avoid_scores": [],
                    "ambiguity_risks": [],
                }
            cat_data[cat]["market_ids"].add(mid)
            if mid in market_ambiguity:
                cat_data[cat]["ambiguity_risks"].extend(market_ambiguity[mid])

        # Add alpha scores
        for cand in alpha_candidates:
            mid = str(cand.get("market_id", ""))
            cat = market_categories.get(mid, _infer_category(cand.get("question", "")))
            if cat not in cat_data:
                cat_data[cat] = {"market_ids": set(), "alpha_scores": [], "avoid_scores": [], "ambiguity_risks": []}
            cat_data[cat]["alpha_scores"].append(_safe_float(cand.get("alpha_score"), 0.0))

        # Add avoid scores
        for cand in avoid_candidates:
            mid = str(cand.get("market_id", ""))
            cat = market_categories.get(mid, _infer_category(cand.get("question", "")))
            if cat not in cat_data:
                cat_data[cat] = {"market_ids": set(), "alpha_scores": [], "avoid_scores": [], "ambiguity_risks": []}
            cat_data[cat]["avoid_scores"].append(_safe_float(cand.get("avoid_score"), 0.0))

        results: list[CategoryPerformance] = []
        for cat, data in sorted(cat_data.items()):
            perf = CategoryPerformance(category=cat)
            perf.market_count = len(data["market_ids"])
            if data["alpha_scores"]:
                perf.avg_alpha_score = sum(data["alpha_scores"]) / len(data["alpha_scores"])
            if data["avoid_scores"]:
                perf.avg_avoid_score = sum(data["avoid_scores"]) / len(data["avoid_scores"])
            if data["ambiguity_risks"]:
                perf.avg_ambiguity_risk = sum(data["ambiguity_risks"]) / len(data["ambiguity_risks"])
            if perf.market_count >= 2:
                perf.conclusion_status = "observed"
            else:
                perf.conclusion_status = "insufficient_data"
            results.append(perf)

        return results


class EventScoreCorrelationValidator:
    """Validate event_score forward correlation."""

    def validate(
        self,
        trajectories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute event_score vs forward combined_ask correlation."""
        # For each market with trajectory data, check if high event_score
        # correlates with lower combined_ask in subsequent observations
        pairs: list[tuple[float, float]] = []

        for traj in trajectories:
            obs = traj.get("trajectory", [])
            if len(obs) < 2:
                continue
            for i in range(len(obs) - 1):
                es = _safe_float(obs[i].get("event_score"))
                next_ask = _safe_float(obs[i + 1].get("combined_ask"))
                if es is not None and next_ask is not None:
                    pairs.append((es, next_ask))

        result: dict[str, Any] = {
            "num_pairs": len(pairs),
            "conclusion_status": "insufficient_data",
            "note": "",
        }

        if len(pairs) < 3:
            result["note"] = f"Only {len(pairs)} observation pairs, need >= 3 for correlation"
            return result

        # Compute Pearson correlation
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        correlation = _pearson_correlation(xs, ys)
        result["correlation"] = correlation
        result["conclusion_status"] = "observed"
        result["note"] = (
            f"Correlation between event_score and next combined_ask: "
            f"r={correlation:.3f} (n={len(pairs)}). "
            f"This is exploratory, not causal."
        )

        return result


# =============================================================================
# Report Generator
# =============================================================================


class ValidationReportGenerator:
    """Generate validation report and exports."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def generate_report(
        self,
        alpha_results: list[AlphaForwardChange],
        watchlist_results: list[WatchlistPersistence],
        avoid_results: list[AvoidRiskValidation],
        avoid_comparison: AvoidGroupComparison,
        category_results: list[CategoryPerformance],
        correlation_result: dict[str, Any],
        summary: dict[str, Any],
    ) -> str:
        """Generate markdown report."""
        lines: list[str] = []
        lines.append("# Strategy Signal Validation Report")
        lines.append("")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("")
        lines.append("## Disclaimers")
        lines.append("")
        lines.append(f"> **{ALPHA_DISCLAIMER}**")
        lines.append("")
        lines.append(f"> **{VALIDATION_DISCLAIMER}**")
        lines.append("")
        lines.append(f"> **live_trading_enabled: false** | **allow_auto_execution: false**")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Overview
        lines.append("## Overview")
        lines.append("")
        lines.append(f"- Alpha candidates analyzed: {len(alpha_results)}")
        lines.append(f"- Watchlist markets analyzed: {len(watchlist_results)}")
        lines.append(f"- Avoid candidates analyzed: {len(avoid_results)}")
        lines.append(f"- Categories analyzed: {len(category_results)}")
        lines.append(f"- Event-score pairs for correlation: {correlation_result.get('num_pairs', 0)}")
        lines.append("")

        # Q1: Alpha forward change
        lines.append("## Q1: Alpha Candidate Forward Change")
        lines.append("")
        lines.append("Do alpha_candidates show lower combined_ask in subsequent observations?")
        lines.append("")
        weak = [r for r in alpha_results if r.conclusion_status == "weak_descriptive"]
        preliminary = [r for r in alpha_results if r.conclusion_status == "preliminary_observed"]
        stronger = [r for r in alpha_results if r.conclusion_status == "stronger_observed"]
        insufficient = [r for r in alpha_results if r.conclusion_status == "insufficient_data"]
        lines.append(f"- weak_descriptive: {len(weak)}")
        lines.append(f"- preliminary_observed: {len(preliminary)}")
        lines.append(f"- stronger_observed: {len(stronger)}")
        lines.append(f"- insufficient_data: {len(insufficient)}")
        lines.append("")
        lines.append("Observation tiers are descriptive only: 3-4 observations are preliminary_observed, not a strong conclusion.")
        lines.append("")
        if alpha_results:
            lines.append("| Market | Alpha Score | First Ask | Last Ask | Delta | Slope | Obs | Status |")
            lines.append("|--------|------------|-----------|----------|-------|-------|-----|--------|")
            for r in alpha_results:
                first = f"{r.first_combined_ask:.4f}" if r.first_combined_ask else "N/A"
                last = f"{r.last_combined_ask:.4f}" if r.last_combined_ask else "N/A"
                delta = f"{r.delta:+.4f}" if r.delta is not None else "N/A"
                slope = f"{r.slope:+.6f}" if r.slope is not None else "N/A"
                lines.append(
                    f"| {r.question[:40]} | {r.alpha_score:.1f} | {first} | {last} | "
                    f"{delta} | {slope} | {r.num_observations} | {r.conclusion_status} |"
                )
            lines.append("")

        # Q2: Avoid risk validation
        lines.append("## Q2: Avoid Candidate Risk Validation")
        lines.append("")
        lines.append("Do avoid_candidates have higher ambiguity_risk than non-avoid markets?")
        lines.append("")
        lines.append(f"**Group comparison:** {avoid_comparison.note}")
        lines.append("")
        lines.append(f"- Avoid group size: {avoid_comparison.avoid_group_size}")
        lines.append(f"- Non-avoid control group size: {avoid_comparison.non_avoid_group_size}")
        lines.append(f"- conclusion_status: **{avoid_comparison.conclusion_status}**")
        lines.append("")
        if avoid_comparison.avoid_avg_ambiguity_risk is not None:
            lines.append(f"- Avoid avg ambiguity_risk: {avoid_comparison.avoid_avg_ambiguity_risk:.1f}")
        if avoid_comparison.non_avoid_avg_ambiguity_risk is not None:
            lines.append(f"- Non-avoid avg ambiguity_risk: {avoid_comparison.non_avoid_avg_ambiguity_risk:.1f}")
        if avoid_comparison.ambiguity_risk_delta is not None:
            lines.append(f"- Delta: {avoid_comparison.ambiguity_risk_delta:+.1f}")
        lines.append("")

        # Q3: Watchlist persistence
        lines.append("## Q3: Watchlist Persistence")
        lines.append("")
        lines.append("Do watchlist markets persist near near-miss thresholds?")
        lines.append("")
        obs_wl = [r for r in watchlist_results if r.conclusion_status == "observed"]
        lines.append(f"- observed: {len(obs_wl)}")
        lines.append(f"- insufficient_data: {len(watchlist_results) - len(obs_wl)}")
        lines.append("")
        if watchlist_results:
            lines.append("| Market | Appearances | Near-Miss Hits | Persistence | Avg Ask | Status |")
            lines.append("|--------|-------------|----------------|-------------|---------|--------|")
            for r in watchlist_results:
                avg_ask = f"{r.avg_combined_ask:.4f}" if r.avg_combined_ask else "N/A"
                lines.append(
                    f"| {r.question[:40]} | {r.total_appearances} | {r.near_miss_hits} | "
                    f"{r.persistence_score:.0%} | {avg_ask} | {r.conclusion_status} |"
                )
            lines.append("")

        # Q4: Event score correlation
        lines.append("## Q4: Event Score Forward Correlation")
        lines.append("")
        lines.append(f"conclusion_status: **{correlation_result['conclusion_status']}**")
        lines.append("")
        lines.append(f"- {correlation_result['note']}")
        lines.append("")

        # Q5: Category performance
        lines.append("## Q5: Category-Level Performance")
        lines.append("")
        if category_results:
            lines.append("| Category | Markets | Avg Alpha | Avg Avoid | Avg Ambiguity | Status |")
            lines.append("|----------|---------|-----------|-----------|---------------|--------|")
            for r in category_results:
                alpha = f"{r.avg_alpha_score:.1f}" if r.avg_alpha_score else "N/A"
                avoid = f"{r.avg_avoid_score:.1f}" if r.avg_avoid_score else "N/A"
                amb = f"{r.avg_ambiguity_risk:.1f}" if r.avg_ambiguity_risk else "N/A"
                lines.append(
                    f"| {r.category} | {r.market_count} | {alpha} | {avoid} | "
                    f"{amb} | {r.conclusion_status} |"
                )
            lines.append("")

        # Summary
        lines.append("## Conclusion Status Summary")
        lines.append("")
        lines.append("| Research Question | conclusion_status |")
        lines.append("|-------------------|-------------------|")
        lines.append(f"| Q1: Alpha forward change | {self._overall_status(alpha_results)} |")
        lines.append(f"| Q2: Avoid risk validation | {avoid_comparison.conclusion_status} |")
        lines.append(f"| Q3: Watchlist persistence | {self._overall_status(watchlist_results)} |")
        lines.append(f"| Q4: Event score correlation | {correlation_result['conclusion_status']} |")
        lines.append(f"| Q5: Category performance | {self._overall_status(category_results)} |")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Safety Verification")
        lines.append("")
        lines.append("- live_trading_enabled: **false**")
        lines.append("- allow_auto_execution: **false**")
        lines.append("- No real API calls made")
        lines.append("- No LLM calls made")
        lines.append("- No trading actions triggered")
        lines.append("- All data read from existing runs/ files")

        return "\n".join(lines)

    def generate_summary_json(
        self,
        alpha_results: list[AlphaForwardChange],
        watchlist_results: list[WatchlistPersistence],
        avoid_results: list[AvoidRiskValidation],
        avoid_comparison: AvoidGroupComparison,
        category_results: list[CategoryPerformance],
        correlation_result: dict[str, Any],
        num_runs: int,
    ) -> dict[str, Any]:
        """Generate machine-readable summary."""
        return {
            "validation_timestamp": datetime.now().isoformat(),
            "num_runs_analyzed": num_runs,
            "alpha_disclaimer": ALPHA_DISCLAIMER,
            "validation_disclaimer": VALIDATION_DISCLAIMER,
            "safety_verification": {
                "live_trading_enabled": False,
                "allow_auto_execution": False,
                "real_api_calls": False,
                "llm_calls": False,
                "trading_actions": False,
            },
            "q1_alpha_forward_change": {
                "total_candidates": len(alpha_results),
                "weak_descriptive": sum(1 for r in alpha_results if r.conclusion_status == "weak_descriptive"),
                "preliminary_observed": sum(1 for r in alpha_results if r.conclusion_status == "preliminary_observed"),
                "stronger_observed": sum(1 for r in alpha_results if r.conclusion_status == "stronger_observed"),
                "insufficient_data": sum(1 for r in alpha_results if r.conclusion_status == "insufficient_data"),
                "conclusion_status": self._overall_status(alpha_results),
            },
            "q2_avoid_risk_validation": {
                "avoid_group_size": avoid_comparison.avoid_group_size,
                "non_avoid_group_size": avoid_comparison.non_avoid_group_size,
                "avoid_avg_ambiguity_risk": avoid_comparison.avoid_avg_ambiguity_risk,
                "non_avoid_avg_ambiguity_risk": avoid_comparison.non_avoid_avg_ambiguity_risk,
                "ambiguity_risk_delta": avoid_comparison.ambiguity_risk_delta,
                "conclusion_status": avoid_comparison.conclusion_status,
                "note": avoid_comparison.note,
            },
            "q3_watchlist_persistence": {
                "total_markets": len(watchlist_results),
                "observed": sum(1 for r in watchlist_results if r.conclusion_status == "observed"),
                "conclusion_status": self._overall_status(watchlist_results),
            },
            "q4_event_score_correlation": correlation_result,
            "q5_category_performance": {
                "num_categories": len(category_results),
                "conclusion_status": self._overall_status(category_results),
                "categories": [
                    {
                        "category": r.category,
                        "market_count": r.market_count,
                        "avg_alpha_score": r.avg_alpha_score,
                        "avg_avoid_score": r.avg_avoid_score,
                        "avg_ambiguity_risk": r.avg_ambiguity_risk,
                        "conclusion_status": r.conclusion_status,
                    }
                    for r in category_results
                ],
            },
        }

    def export_alpha_csv(self, results: list[AlphaForwardChange]) -> Path:
        """Export alpha validation CSV."""
        path = self.output_dir / "alpha_validation.csv"
        fields = [
            "market_id", "question", "alpha_score", "evidence_level",
            "first_combined_ask", "last_combined_ask", "min_combined_ask",
            "max_combined_ask", "delta", "slope", "num_observations",
            "conclusion_status", "note",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "market_id": r.market_id,
                    "question": r.question,
                    "alpha_score": r.alpha_score,
                    "evidence_level": r.evidence_level,
                    "first_combined_ask": r.first_combined_ask,
                    "last_combined_ask": r.last_combined_ask,
                    "min_combined_ask": r.min_combined_ask,
                    "max_combined_ask": r.max_combined_ask,
                    "delta": r.delta,
                    "slope": r.slope,
                    "num_observations": r.num_observations,
                    "conclusion_status": r.conclusion_status,
                    "note": r.note,
                })
        return path

    def export_avoid_csv(self, results: list[AvoidRiskValidation]) -> Path:
        """Export avoid validation CSV."""
        path = self.output_dir / "avoid_validation.csv"
        fields = [
            "market_id", "question", "avoid_score", "reasons",
            "avg_ambiguity_risk", "category_risk", "avg_event_score",
            "suggested_mode", "conclusion_status", "note",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "market_id": r.market_id,
                    "question": r.question,
                    "avoid_score": r.avoid_score,
                    "reasons": r.reasons,
                    "avg_ambiguity_risk": r.avg_ambiguity_risk,
                    "category_risk": r.category_risk,
                    "avg_event_score": r.avg_event_score,
                    "suggested_mode": r.suggested_mode,
                    "conclusion_status": r.conclusion_status,
                    "note": r.note,
                })
        return path

    def export_watchlist_csv(self, results: list[WatchlistPersistence]) -> Path:
        """Export watchlist validation CSV."""
        path = self.output_dir / "watchlist_validation.csv"
        fields = [
            "market_id", "question", "evidence_level", "total_appearances",
            "near_miss_hits", "persistence_score", "avg_combined_ask",
            "avg_event_score", "conclusion_status", "note",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "market_id": r.market_id,
                    "question": r.question,
                    "evidence_level": r.evidence_level,
                    "total_appearances": r.total_appearances,
                    "near_miss_hits": r.near_miss_hits,
                    "persistence_score": r.persistence_score,
                    "avg_combined_ask": r.avg_combined_ask,
                    "avg_event_score": r.avg_event_score,
                    "conclusion_status": r.conclusion_status,
                    "note": r.note,
                })
        return path

    @staticmethod
    def _overall_status(results: list) -> str:
        """Determine overall conclusion status from a list of results."""
        statuses = [r.conclusion_status for r in results]
        if not statuses:
            return "insufficient_data"
        if all(s == "insufficient_data" for s in statuses):
            return "insufficient_data"
        if len(set(statuses)) == 1:
            return statuses[0]
        return "inconclusive"


# =============================================================================
# Utility Functions
# =============================================================================


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely convert to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _compute_slope(values: list[float]) -> float:
    """Compute simple linear regression slope."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Compute Pearson correlation coefficient."""
    n = len(xs)
    if n < 2:
        return 0.0
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    sx = sum((x - x_mean) ** 2 for x in xs) ** 0.5
    sy = sum((y - y_mean) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def _infer_category(question: str) -> str:
    """Infer market category from question text (keyword heuristic)."""
    q = question.lower()

    # Politics (check before sports to avoid "win the" collision)
    if any(kw in q for kw in [
        "presidential nomination", "nomination", "primary", "election",
        "president", "senate", "congress", "governor", "mayor",
        "democrat", "republican", "trump", "biden",
        "vote", "polling", "candidate",
    ]):
        return "Politics"

    # Crypto
    if any(kw in q for kw in [
        "bitcoin", "btc", "ethereum", "crypto",
        "solana", "token", "hit $", "market cap", "defi", "nft",
    ]):
        return "Crypto"
    if " eth" in q or q.startswith("eth") or "eth " in q:
        return "Crypto"

    # Sports
    if any(kw in q for kw in [
        "fifa", "world cup", "soccer", "football",
        "uefa", "champions league", "premier league",
        "olympics", "olympic", "tennis", "golf",
        "nhl", "nba", "nfl", "mlb",
        "stanley cup", "super bowl", "championship", "playoff",
    ]):
        return "Sports"

    # Gaming
    if any(kw in q for kw in [
        "gta", "game", "release", "playstation", "xbox", "nintendo",
        "video game", "steam", "esports",
    ]):
        return "Gaming"

    # Entertainment
    if any(kw in q for kw in [
        "movie", "film", "oscar", "emmy", "grammy",
        "celebrity", "actor", "actress", "netflix", "disney",
    ]):
        return "Entertainment"

    # Geopolitics
    if any(kw in q for kw in [
        "china", "taiwan", "russia", "ukraine", "war",
        "invasion", "military", "nato", "sanctions",
    ]):
        return "Geopolitics"

    # Legal
    if any(kw in q for kw in [
        "sentenced", "sentencing", "prison", "trial", "court", "lawsuit", "conviction",
        "judge", "supreme court", "indicted", "convicted", "verdict",
    ]):
        return "Legal"

    return "Other"


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 6 — Strategy Signal Validation (offline, read-only)",
    )
    parser.add_argument("--runs_dir", type=str, default="runs", help="Runs directory")
    parser.add_argument("--output_dir", type=str, default="runs", help="Output directory")
    parser.add_argument(
        "--min_appearances", type=int, default=2,
        help="Minimum appearances for 'observed' status",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Phase 6 — Strategy Signal Validation")
    print("=" * 60)
    print(f"Runs dir: {runs_dir}")
    print(f"Output dir: {output_dir}")
    print(f"Min appearances: {args.min_appearances}")
    print()

    # Load data
    loader = ValidationDataLoader(runs_dir)
    run_ids = loader.discover_runs()
    print(f"Runs discovered: {len(run_ids)}")

    alpha_candidates = loader.load_alpha_candidates()
    print(f"Alpha candidates: {len(alpha_candidates)}")

    avoid_candidates = loader.load_avoid_candidates()
    print(f"Avoid candidates: {len(avoid_candidates)}")

    watchlist = loader.load_persistent_watchlist()
    print(f"Watchlist markets: {len(watchlist)}")

    trajectories = loader.load_trajectories()
    print(f"Trajectories: {len(trajectories)}")

    all_events = loader.load_all_llm_events()
    print(f"LLM sampling events: {len(all_events)}")

    control_group_samples = loader.load_control_group_samples()
    print(f"Control group samples: {len(control_group_samples)}")
    print()

    # Run validators
    print("Running validators...")

    alpha_validator = AlphaValidator()
    alpha_results = alpha_validator.validate(
        alpha_candidates, trajectories, all_events, args.min_appearances
    )
    print(f"  Q1 alpha_forward_change: {len(alpha_results)} candidates")

    avoid_validator = AvoidValidator()
    avoid_results = [avoid_validator.validate_single(c, all_events) for c in avoid_candidates]
    avoid_comparison = avoid_validator.validate_group_comparison(
        avoid_candidates, all_events, control_group_samples
    )
    print(f"  Q2 avoid_risk_validation: {len(avoid_results)} candidates, group comparison: {avoid_comparison.conclusion_status}")

    watchlist_validator = WatchlistValidator()
    watchlist_results = watchlist_validator.validate(
        watchlist, trajectories, args.min_appearances
    )
    print(f"  Q3 watchlist_persistence: {len(watchlist_results)} markets")

    correlation_validator = EventScoreCorrelationValidator()
    correlation_result = correlation_validator.validate(trajectories)
    print(f"  Q4 event_score_correlation: {correlation_result['conclusion_status']}")

    category_validator = CategoryValidator()
    category_results = category_validator.validate(
        alpha_candidates, avoid_candidates, all_events
    )
    print(f"  Q5 category_performance: {len(category_results)} categories")
    print()

    # Generate outputs
    print("Generating outputs...")
    generator = ValidationReportGenerator(output_dir)

    report = generator.generate_report(
        alpha_results, watchlist_results, avoid_results,
        avoid_comparison, category_results, correlation_result,
        {"num_runs": len(run_ids)},
    )
    report_path = output_dir / "strategy_validation_report.md"
    report_path.write_text(report)
    print(f"  {report_path}")

    summary = generator.generate_summary_json(
        alpha_results, watchlist_results, avoid_results,
        avoid_comparison, category_results, correlation_result,
        len(run_ids),
    )
    summary_path = output_dir / "strategy_validation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"  {summary_path}")

    alpha_csv = generator.export_alpha_csv(alpha_results)
    print(f"  {alpha_csv}")

    avoid_csv = generator.export_avoid_csv(avoid_results)
    print(f"  {avoid_csv}")

    wl_csv = generator.export_watchlist_csv(watchlist_results)
    print(f"  {wl_csv}")
    print()

    print("=" * 60)
    print("VALIDATION COMPLETE")
    print(f"live_trading_enabled: false (unchanged)")
    print(f"allow_auto_execution: false (unchanged)")
    print("=" * 60)


if __name__ == "__main__":
    main()
