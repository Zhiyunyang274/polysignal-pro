#!/usr/bin/env python3
"""
Multi-Run Intelligence Comparison - Phase 5F

Compare multiple runs to generate Market Intelligence Comparison Report
for alpha discovery and persistent watchlist identification.

IMPORTANT:
- This is an OFFLINE analysis tool
- No real-time API calls
- No trading execution
- live_trading_enabled must remain false

Alpha score is a HEURISTIC RESEARCH RANKING, NOT a trading signal.
Candidates require further paper trading validation before any execution.

Usage:
    python3 scripts/compare_run_intelligence.py --runs_dir runs --latest_n 5
    python3 scripts/compare_run_intelligence.py --run_ids run_20260509_112002_8977ca4e,run_20260508_155427_612f24ff
    python3 scripts/compare_run_intelligence.py --runs_dir runs --since 2026-05-01 --top_n 20 --export_csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Evidence level thresholds
EVIDENCE_LEVELS = {
    "weak": {"min_appearances": 1, "min_total_runs": 1},  # appearances < 2 or total_runs < 3
    "moderate": {"min_appearances": 2, "min_total_runs": 3},  # appearances >= 2 and total_runs >= 3
    "strong": {"min_appearances": 3, "min_total_runs": 5},  # appearances >= 3 and total_runs >= 5
}


def calculate_evidence_level(appearances: int, total_runs: int) -> str:
    """Calculate evidence level based on appearances and total runs"""
    if appearances >= 3 and total_runs >= 5:
        return "strong"
    elif appearances >= 2 and total_runs >= 3:
        return "moderate"
    else:
        return "weak"


def normalize_question(question: str) -> str:
    """Normalize question for fallback matching"""
    if not question:
        return ""
    # Lowercase, remove punctuation, collapse whitespace
    normalized = question.lower()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized[:100]  # Truncate for consistency


def infer_market_category(question: str) -> str:
    """
    Infer market category from question text.

    NOTE: This is a HEURISTIC classification based on keywords.
    """
    question_lower = question.lower()

    # Politics keywords (check before sports to avoid "win the" collision)
    politics_keywords = [
        "presidential nomination", "nomination", "primary", "election",
        "president", "senate", "congress", "governor", "mayor",
        "democrat", "republican", "trump", "biden",
        "vote", "polling", "candidate",
    ]
    for kw in politics_keywords:
        if kw in question_lower:
            return "Politics"

    # Crypto keywords
    crypto_keywords = [
        "bitcoin", "btc", "ethereum", "crypto",
        "solana", "token", "hit $", "market cap", "defi", "nft",
    ]
    for kw in crypto_keywords:
        if kw in question_lower:
            return "Crypto"
    if " eth" in question_lower or question_lower.startswith("eth") or "eth " in question_lower:
        return "Crypto"

    # Sports keywords
    sports_keywords = [
        "fifa", "world cup", "soccer", "football",
        "uefa", "champions league", "premier league",
        "olympics", "olympic", "tennis", "golf",
        "nhl", "nba", "nfl", "mlb",
        "stanley cup", "super bowl", "championship", "playoff",
    ]
    for kw in sports_keywords:
        if kw in question_lower:
            return "Sports"

    # Gaming keywords
    gaming_keywords = [
        "gta", "game", "release", "playstation", "xbox", "nintendo",
        "video game", "steam", "esports",
    ]
    for kw in gaming_keywords:
        if kw in question_lower:
            return "Gaming"

    # Entertainment keywords
    entertainment_keywords = [
        "movie", "film", "oscar", "emmy", "grammy",
        "celebrity", "actor", "actress", "netflix", "disney",
    ]
    for kw in entertainment_keywords:
        if kw in question_lower:
            return "Entertainment"

    # Geopolitics keywords
    geopolitics_keywords = [
        "china", "taiwan", "russia", "ukraine", "war",
        "invasion", "military", "nato", "sanctions",
    ]
    for kw in geopolitics_keywords:
        if kw in question_lower:
            return "Geopolitics"

    # Legal keywords
    legal_keywords = [
        "sentenced", "sentencing", "prison", "trial", "court", "lawsuit", "conviction",
        "judge", "supreme court", "indicted", "convicted", "verdict",
    ]
    for kw in legal_keywords:
        if kw in question_lower:
            return "Legal"

    return "Other"


def get_category_risk_score(category: str) -> float:
    """
    Get category risk score (NOT hard forbidden, just risk adjustment).

    This is a heuristic risk score for category-level analysis.
    Hard forbidden categories should be read from config/risk.yaml.
    """
    # Default category risk scores (0-30 scale)
    category_risks = {
        "Politics": 25.0,  # High category risk
        "Geopolitics": 25.0,  # High category risk
        "Entertainment": 10.0,  # Medium category risk (subjective)
        "Sports": 5.0,  # Low category risk
        "Crypto": 15.0,  # Medium-high category risk (volatility)
        "Gaming": 5.0,  # Low category risk
        "Legal": 10.0,  # Medium category risk
        "Other": 10.0,  # Default medium risk
    }
    return category_risks.get(category, 10.0)


@dataclass
class MarketObservation:
    """Single observation of a market in one run"""
    run_id: str
    timestamp: str
    combined_ask: float | None = None
    event_score: float | None = None
    confidence: float | None = None
    suggested_mode: str | None = None
    ambiguity_risk: float | None = None
    volume_24h: float | None = None
    llm_success: bool | None = None
    near_miss_tier: str | None = None


@dataclass
class MarketSummary:
    """Aggregated summary of a market across runs"""
    market_id: str
    matched_by: str = "market_id"  # "market_id" or "normalized_question"
    normalized_question: str = ""
    question: str = ""
    category: str = "Other"

    appearances: int = 0
    run_ids: list[str] = field(default_factory=list)
    observations: list[MarketObservation] = field(default_factory=list)

    # Aggregated metrics
    avg_combined_ask: float | None = None
    avg_event_score: float | None = None
    avg_confidence: float | None = None
    avg_ambiguity_risk: float | None = None
    avg_volume: float | None = None

    min_combined_ask: float | None = None
    max_combined_ask: float | None = None

    near_miss_tier_mode: str | None = None
    suggested_mode_mode: str | None = None

    llm_success_rate: float | None = None

    # Scoring
    alpha_score: float | None = None
    avoid_score: float | None = None
    evidence_level: str = "weak"


@dataclass
class RunSummary:
    """Summary of a single run"""
    run_id: str
    run_dir: Path
    timestamp: str | None = None
    duration_minutes: float = 0.0
    data_mode: str = "unknown"
    llm_provider: str = "unknown"

    total_observed_markets: int = 0
    llm_total_samples: int = 0
    llm_successful_samples: int = 0
    llm_failed_samples: int = 0

    near_miss_tier_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)

    live_trading_enabled: bool = False
    allow_auto_execution: bool = False

    # Raw data
    events: list[dict] = field(default_factory=list)
    sampled_markets: list[dict] = field(default_factory=list)


@dataclass
class ComparisonSummary:
    """Summary of multi-run comparison"""
    # Run selection
    runs_dir: str = ""
    total_runs: int = 0
    run_ids: list[str] = field(default_factory=list)
    selection_criteria: str = ""
    date_range: dict[str, str] = field(default_factory=dict)

    # Aggregated stats
    total_observed_markets: int = 0
    unique_markets: int = 0
    total_llm_samples: int = 0
    llm_successful_samples: int = 0
    llm_success_rate: float = 0.0

    total_near_miss_tier1: int = 0
    total_near_miss_tier2: int = 0
    total_near_miss_tier3: int = 0
    total_near_miss_tier4: int = 0

    total_run_duration_minutes: float = 0.0

    # Category analysis
    category_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Top candidates
    persistent_watchlist: list[dict] = field(default_factory=list)
    alpha_candidates: list[dict] = field(default_factory=list)
    avoid_candidates: list[dict] = field(default_factory=list)

    # Safety
    all_runs_live_trading_disabled: bool = True
    all_runs_auto_execution_disabled: bool = True


class RunDiscovery:
    """Discover and filter runs"""

    @staticmethod
    def discover_runs(
        runs_dir: Path,
        run_ids: list[str] | None = None,
        latest_n: int | None = None,
        since: str | None = None,
        min_runs: int = 2,
    ) -> list[Path]:
        """Discover valid runs based on criteria"""
        if not runs_dir.exists():
            print(f"Error: runs_dir not found: {runs_dir}")
            return []

        # Get all run directories
        all_runs = [
            d for d in runs_dir.iterdir()
            if d.is_dir() and d.name.startswith("run_")
        ]

        # Filter by run_ids if specified
        if run_ids:
            filtered = [runs_dir / rid for rid in run_ids if (runs_dir / rid).exists()]
            return sorted(filtered, key=lambda p: p.name, reverse=True)

        # Sort by name (which includes timestamp)
        all_runs.sort(key=lambda p: p.name, reverse=True)

        # Filter by since date if specified
        if since:
            try:
                since_date = datetime.strptime(since, "%Y-%m-%d")
                filtered = []
                for run_path in all_runs:
                    # Extract date from run_id (format: run_YYYYMMDD_HHMMSS_hash)
                    parts = run_path.name.split("_")
                    if len(parts) >= 2:
                        try:
                            run_date = datetime.strptime(parts[1], "%Y%m%d")
                            if run_date >= since_date:
                                filtered.append(run_path)
                        except ValueError:
                            continue
                all_runs = filtered
            except ValueError:
                print(f"Warning: Invalid since date format: {since}")

        # Apply latest_n filter
        if latest_n:
            all_runs = all_runs[:latest_n]

        # Validate runs
        valid_runs = [r for r in all_runs if RunDiscovery.validate_run(r)]

        if len(valid_runs) < min_runs:
            print(f"Warning: Only {len(valid_runs)} valid runs found (min_runs={min_runs})")

        return valid_runs

    @staticmethod
    def validate_run(run_dir: Path) -> bool:
        """Check if run directory is valid"""
        if not run_dir.is_dir():
            return False

        # Must have at least one of these files
        has_intelligence_summary = (run_dir / "intelligence_summary.json").exists()
        has_summary = (run_dir / "summary.json").exists()
        has_events = (run_dir / "events.jsonl").exists()

        return has_intelligence_summary or (has_summary and has_events)


class RunDataLoader:
    """Load data from a single run"""

    @staticmethod
    def load_run(run_dir: Path) -> RunSummary:
        """Load all data from a run directory"""
        summary = RunSummary(
            run_id=run_dir.name,
            run_dir=run_dir,
        )

        # Try to load intelligence_summary.json first
        intelligence_summary_path = run_dir / "intelligence_summary.json"
        if intelligence_summary_path.exists():
            RunDataLoader._load_intelligence_summary(summary, intelligence_summary_path)

        # Load summary.json
        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            RunDataLoader._load_summary(summary, summary_path)

        # Load events.jsonl
        events_path = run_dir / "events.jsonl"
        if events_path.exists():
            RunDataLoader._load_events(summary, events_path)

        # Load sampled_markets.csv if exists
        csv_path = run_dir / "sampled_markets.csv"
        if csv_path.exists():
            RunDataLoader._load_sampled_markets_csv(summary, csv_path)

        return summary

    @staticmethod
    def _load_intelligence_summary(summary: RunSummary, path: Path) -> None:
        """Load intelligence_summary.json"""
        try:
            with open(path) as f:
                data = json.load(f)

            summary.total_observed_markets = data.get("total_observed_markets", 0)
            summary.llm_total_samples = data.get("llm_total_samples", 0)
            summary.llm_successful_samples = data.get("llm_successful_samples", 0)
            summary.llm_failed_samples = data.get("llm_failed_samples", 0)
            summary.near_miss_tier_distribution = data.get("near_miss_tier_distribution", {})
            summary.category_distribution = data.get("category_distribution", {})
            summary.live_trading_enabled = data.get("live_trading_enabled", False)
            summary.allow_auto_execution = data.get("allow_auto_execution", False)
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")

    @staticmethod
    def _load_summary(summary: RunSummary, path: Path) -> None:
        """Load summary.json"""
        try:
            with open(path) as f:
                data = json.load(f)

            summary.duration_minutes = data.get("duration_minutes", 0.0)
            summary.data_mode = data.get("data_mode", "unknown")
            summary.llm_provider = data.get("llm_provider", "unknown")
            summary.live_trading_enabled = data.get("live_trading_enabled", False)
            summary.allow_auto_execution = data.get("allow_auto_execution", False)

            # If not loaded from intelligence_summary
            if not summary.total_observed_markets:
                summary.total_observed_markets = data.get("markets_checked", 0)
            if not summary.llm_total_samples:
                summary.llm_total_samples = data.get("llm_sampling_calls_attempted", 0)
                summary.llm_successful_samples = data.get("llm_sampling_calls_succeeded", 0)
                summary.llm_failed_samples = data.get("llm_sampling_calls_failed", 0)
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")

    @staticmethod
    def _load_events(summary: RunSummary, path: Path) -> None:
        """Load events.jsonl"""
        try:
            with open(path) as f:
                summary.events = [json.loads(line) for line in f if line.strip()]
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")

    @staticmethod
    def _load_sampled_markets_csv(summary: RunSummary, path: Path) -> None:
        """Load sampled_markets.csv"""
        try:
            with open(path) as f:
                reader = csv.DictReader(f)
                summary.sampled_markets = list(reader)
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")


class MarketAggregator:
    """Aggregate market data across runs"""

    @staticmethod
    def aggregate_markets(
        runs_data: list[RunSummary],
        min_appearances: int = 2,
    ) -> dict[str, MarketSummary]:
        """Aggregate market data across all runs"""
        markets: dict[str, MarketSummary] = {}
        question_to_market: dict[str, str] = {}  # normalized_question -> market_key

        total_runs = len(runs_data)

        for run in runs_data:
            # Process events for market data
            for event in run.events:
                event_type = event.get("event_type", "")
                details = event.get("details") or {}

                if event_type == "llm_sampling_assessment":
                    MarketAggregator._process_llm_sampling_event(
                        markets, question_to_market, run, details, total_runs
                    )

            # Also process sampled_markets CSV if available
            for market_data in run.sampled_markets:
                MarketAggregator._process_sampled_market(
                    markets, question_to_market, run, market_data, total_runs
                )

        # Filter by min_appearances
        filtered = {
            k: v for k, v in markets.items()
            if v.appearances >= min_appearances
        }

        return filtered

    @staticmethod
    def _process_llm_sampling_event(
        markets: dict[str, MarketSummary],
        question_to_market: dict[str, str],
        run: RunSummary,
        details: dict,
        total_runs: int,
    ) -> None:
        """Process a single LLM sampling event"""
        market_id = details.get("market_id")
        question = details.get("question", "")
        normalized_q = normalize_question(question)

        # Determine market key (prefer market_id, fallback to normalized question)
        market_key = None
        matched_by = "market_id"

        if market_id:
            market_key = str(market_id)
            # Also update question mapping if we have both
            if normalized_q and normalized_q not in question_to_market:
                question_to_market[normalized_q] = market_key
        elif normalized_q:
            # Fallback to normalized question
            if normalized_q in question_to_market:
                market_key = question_to_market[normalized_q]
            else:
                market_key = f"q_{normalized_q[:50]}"
                question_to_market[normalized_q] = market_key
                matched_by = "normalized_question"

        if not market_key:
            return

        # Create or update market summary
        if market_key not in markets:
            markets[market_key] = MarketSummary(
                market_id=market_key,
                matched_by=matched_by,
                normalized_question=normalized_q,
                question=question,
                category=infer_market_category(question) if question else "Other",
            )

        market = markets[market_key]

        # Update question if we have it
        if question and not market.question:
            market.question = question

        # Create observation
        observation = MarketObservation(
            run_id=run.run_id,
            timestamp=run.timestamp or "",
            combined_ask=details.get("combined_ask"),
            event_score=details.get("event_score"),
            confidence=details.get("confidence"),
            suggested_mode=details.get("suggested_mode"),
            ambiguity_risk=details.get("ambiguity_risk"),
            volume_24h=details.get("volume_24h"),
            llm_success=details.get("success"),
        )

        market.observations.append(observation)
        market.appearances += 1
        if run.run_id not in market.run_ids:
            market.run_ids.append(run.run_id)

    @staticmethod
    def _process_sampled_market(
        markets: dict[str, MarketSummary],
        question_to_market: dict[str, str],
        run: RunSummary,
        market_data: dict,
        total_runs: int,
    ) -> None:
        """Process a sampled market from CSV"""
        market_id = market_data.get("market_id", "")
        question = market_data.get("question", "")
        normalized_q = normalize_question(question)

        if not market_id:
            return

        market_key = str(market_id)

        if market_key not in markets:
            markets[market_key] = MarketSummary(
                market_id=market_key,
                matched_by="market_id",
                normalized_question=normalized_q,
                question=question,
                category=market_data.get("category") or infer_market_category(question) or "Other",
            )

        market = markets[market_key]

        if question and not market.question:
            market.question = question

        # Create observation from CSV data
        try:
            combined_ask = float(market_data.get("combined_ask", 0)) if market_data.get("combined_ask") else None
            event_score = float(market_data.get("event_score", 0)) if market_data.get("event_score") else None
            confidence = float(market_data.get("confidence", 0)) if market_data.get("confidence") else None
            ambiguity_risk = float(market_data.get("ambiguity_risk", 0)) if market_data.get("ambiguity_risk") else None
            volume_24h = float(market_data.get("volume_24h", 0)) if market_data.get("volume_24h") else None
        except (ValueError, TypeError):
            return

        observation = MarketObservation(
            run_id=run.run_id,
            timestamp=run.timestamp or "",
            combined_ask=combined_ask,
            event_score=event_score,
            confidence=confidence,
            suggested_mode=market_data.get("suggested_mode"),
            ambiguity_risk=ambiguity_risk,
            volume_24h=volume_24h,
            llm_success=market_data.get("llm_success") == "True" if market_data.get("llm_success") else None,
        )

        # Check if this run already has an observation
        if run.run_id not in market.run_ids:
            market.observations.append(observation)
            market.appearances += 1
            market.run_ids.append(run.run_id)

    @staticmethod
    def calculate_aggregated_metrics(markets: dict[str, MarketSummary], total_runs: int) -> None:
        """Calculate aggregated metrics for each market"""
        for market in markets.values():
            # Calculate averages
            combined_asks = [o.combined_ask for o in market.observations if o.combined_ask is not None]
            event_scores = [o.event_score for o in market.observations if o.event_score is not None]
            confidences = [o.confidence for o in market.observations if o.confidence is not None]
            ambiguity_risks = [o.ambiguity_risk for o in market.observations if o.ambiguity_risk is not None]
            volumes = [o.volume_24h for o in market.observations if o.volume_24h is not None]
            llm_successes = [o.llm_success for o in market.observations if o.llm_success is not None]

            if combined_asks:
                market.avg_combined_ask = sum(combined_asks) / len(combined_asks)
                market.min_combined_ask = min(combined_asks)
                market.max_combined_ask = max(combined_asks)

            if event_scores:
                market.avg_event_score = sum(event_scores) / len(event_scores)

            if confidences:
                market.avg_confidence = sum(confidences) / len(confidences)

            if ambiguity_risks:
                market.avg_ambiguity_risk = sum(ambiguity_risks) / len(ambiguity_risks)

            if volumes:
                market.avg_volume = sum(volumes) / len(volumes)

            if llm_successes:
                market.llm_success_rate = sum(llm_successes) / len(llm_successes)

            # Calculate mode for near_miss_tier and suggested_mode
            tiers = [o.near_miss_tier for o in market.observations if o.near_miss_tier]
            if tiers:
                market.near_miss_tier_mode = max(set(tiers), key=tiers.count)

            modes = [o.suggested_mode for o in market.observations if o.suggested_mode]
            if modes:
                market.suggested_mode_mode = max(set(modes), key=modes.count)

            # Calculate evidence level
            market.evidence_level = calculate_evidence_level(market.appearances, total_runs)


class AlphaCandidateScorer:
    """Score alpha candidates"""

    # IMPORTANT: Alpha score is a HEURISTIC RESEARCH RANKING, NOT a trading signal
    DISCLAIMER = "Alpha score is a heuristic research ranking, not a trading signal. Candidates require further paper trading validation before any execution."

    @staticmethod
    def calculate_alpha_score(market: MarketSummary, total_runs: int) -> float:
        """
        Calculate alpha score for a market.

        Alpha score is a HEURISTIC RESEARCH RANKING, NOT a trading signal.
        Candidates require further paper trading validation before any execution.
        """
        scores = {}

        # 1. Near-miss frequency score (0-100)
        near_miss_count = sum(
            1 for o in market.observations
            if o.near_miss_tier in ["tier1_mispricing", "tier2_strong_near_miss", "tier3_weak_near_miss"]
        )
        scores["near_miss_frequency"] = min(100, (near_miss_count / max(1, total_runs)) * 100)

        # 2. Low combined_ask score (0-100)
        if market.avg_combined_ask is not None:
            # Lower combined_ask = higher score
            scores["low_combined_ask"] = max(0, min(100, 100 - (market.avg_combined_ask - 1.0) * 1000))
        else:
            scores["low_combined_ask"] = 50  # Neutral if no data

        # 3. High liquidity score (0-100)
        if market.avg_volume is not None:
            scores["high_liquidity"] = min(100, (market.avg_volume / 100000) * 100)
        else:
            scores["high_liquidity"] = 50  # Neutral if no data

        # 4. Low ambiguity score (0-100)
        if market.avg_ambiguity_risk is not None:
            scores["low_ambiguity"] = max(0, 100 - market.avg_ambiguity_risk)
        else:
            scores["low_ambiguity"] = 50  # Neutral if no data

        # 5. High event_score score (0-100)
        if market.avg_event_score is not None:
            scores["high_event_score"] = min(100, market.avg_event_score)
        else:
            scores["high_event_score"] = 50  # Neutral if no data

        # 6. Repeated appearance score (0-100)
        scores["repeated_appearance"] = min(100, market.appearances * 20)

        # Weighted average
        weights = {
            "near_miss_frequency": 0.25,
            "low_combined_ask": 0.20,
            "high_liquidity": 0.15,
            "low_ambiguity": 0.15,
            "high_event_score": 0.15,
            "repeated_appearance": 0.10,
        }

        alpha_score = sum(scores[k] * weights[k] for k in weights)

        return round(alpha_score, 2)

    @staticmethod
    def rank_candidates(markets: dict[str, MarketSummary], total_runs: int, top_n: int = 20) -> list[dict]:
        """Rank markets by alpha score and return top N"""
        # Calculate scores
        for market in markets.values():
            market.alpha_score = AlphaCandidateScorer.calculate_alpha_score(market, total_runs)

        # Sort by alpha score
        sorted_markets = sorted(
            markets.values(),
            key=lambda m: m.alpha_score or 0,
            reverse=True
        )

        # Convert to dict format
        candidates = []
        for market in sorted_markets[:top_n]:
            candidates.append({
                "market_id": market.market_id,
                "matched_by": market.matched_by,
                "question": market.question[:100] if market.question else None,
                "category": market.category,
                "appearances": market.appearances,
                "avg_combined_ask": market.avg_combined_ask,
                "avg_event_score": market.avg_event_score,
                "avg_ambiguity_risk": market.avg_ambiguity_risk,
                "avg_volume": market.avg_volume,
                "alpha_score": market.alpha_score,
                "evidence_level": market.evidence_level,
                "run_ids": market.run_ids,
            })

        return candidates


class AvoidCandidateScorer:
    """Score avoid candidates"""

    @staticmethod
    def calculate_avoid_score(market: MarketSummary, total_runs: int) -> tuple[float, list[str]]:
        """
        Calculate avoid score for a market.
        Returns (score, reasons).
        """
        scores = {}
        reasons = []

        # 1. High ambiguity risk score (0-100)
        if market.avg_ambiguity_risk is not None and market.avg_ambiguity_risk >= 50:
            scores["high_ambiguity"] = market.avg_ambiguity_risk
            reasons.append("high_ambiguity")
        elif market.avg_ambiguity_risk is not None:
            scores["high_ambiguity"] = market.avg_ambiguity_risk * 0.5
        else:
            scores["high_ambiguity"] = 0

        # 2. Category risk score (NOT hard forbidden, just risk adjustment)
        category_risk = get_category_risk_score(market.category)
        scores["category_risk"] = category_risk
        if category_risk >= 20:
            reasons.append("category_risk")

        # 3. Repeated avoid mode score (0-100)
        avoid_count = sum(1 for o in market.observations if o.suggested_mode == "avoid")
        if avoid_count >= 2:
            scores["repeated_avoid"] = min(100, avoid_count * 30)
            reasons.append("repeated_avoid_mode")
        else:
            scores["repeated_avoid"] = 0

        # 4. Poor liquidity score (0-100)
        if market.avg_volume is not None and market.avg_volume < 10000:
            scores["poor_liquidity"] = 80
            reasons.append("poor_liquidity")
        elif market.avg_volume is not None and market.avg_volume < 50000:
            scores["poor_liquidity"] = 40
        else:
            scores["poor_liquidity"] = 0

        # 5. High error rate score (0-100)
        if market.llm_success_rate is not None and market.llm_success_rate < 0.5:
            scores["high_error_rate"] = 70
            reasons.append("high_error_rate")
        else:
            scores["high_error_rate"] = 0

        # Weighted average
        weights = {
            "high_ambiguity": 0.30,
            "category_risk": 0.25,
            "repeated_avoid": 0.20,
            "poor_liquidity": 0.15,
            "high_error_rate": 0.10,
        }

        avoid_score = sum(scores[k] * weights[k] for k in weights)

        return round(avoid_score, 2), reasons

    @staticmethod
    def rank_candidates(markets: dict[str, MarketSummary], total_runs: int, top_n: int = 20) -> list[dict]:
        """Rank markets by avoid score and return top N"""
        # Calculate scores
        for market in markets.values():
            market.avoid_score, _ = AvoidCandidateScorer.calculate_avoid_score(market, total_runs)

        # Sort by avoid score
        sorted_markets = sorted(
            markets.values(),
            key=lambda m: m.avoid_score or 0,
            reverse=True
        )

        # Convert to dict format
        candidates = []
        for market in sorted_markets[:top_n]:
            _, reasons = AvoidCandidateScorer.calculate_avoid_score(market, total_runs)
            candidates.append({
                "market_id": market.market_id,
                "matched_by": market.matched_by,
                "question": market.question[:100] if market.question else None,
                "category": market.category,
                "appearances": market.appearances,
                "avg_ambiguity_risk": market.avg_ambiguity_risk,
                "avg_volume": market.avg_volume,
                "llm_success_rate": market.llm_success_rate,
                "avoid_score": market.avoid_score,
                "evidence_level": market.evidence_level,
                "reasons": reasons,
                "run_ids": market.run_ids,
            })

        return candidates


class PersistentWatchlistGenerator:
    """Generate persistent watchlist"""

    @staticmethod
    def generate(
        markets: dict[str, MarketSummary],
        total_runs: int,
        top_n: int = 20,
    ) -> list[dict]:
        """Generate persistent watchlist from markets that appear multiple times"""
        watchlist = []

        for market in markets.values():
            # Must appear at least twice
            if market.appearances < 2:
                continue

            # Check if market meets watchlist criteria
            is_near_miss = market.near_miss_tier_mode in [
                "tier1_mispricing", "tier2_strong_near_miss", "tier3_weak_near_miss"
            ]
            has_low_combined_ask = market.avg_combined_ask is not None and market.avg_combined_ask < 1.015
            has_event_score = market.avg_event_score is not None and market.avg_event_score >= 30

            if is_near_miss or has_low_combined_ask or has_event_score:
                watchlist.append({
                    "market_id": market.market_id,
                    "matched_by": market.matched_by,
                    "question": market.question[:100] if market.question else None,
                    "category": market.category,
                    "appearances": market.appearances,
                    "avg_combined_ask": market.avg_combined_ask,
                    "avg_event_score": market.avg_event_score,
                    "avg_ambiguity_risk": market.avg_ambiguity_risk,
                    "near_miss_tier_mode": market.near_miss_tier_mode,
                    "suggested_mode_mode": market.suggested_mode_mode,
                    "evidence_level": market.evidence_level,
                    "run_ids": market.run_ids,
                })

        # Sort by appearances (most frequent first), then by avg_combined_ask
        watchlist.sort(key=lambda m: (-m["appearances"], m.get("avg_combined_ask") or 999))

        return watchlist[:top_n]


class CategoryAnalyzer:
    """Analyze category-level statistics"""

    @staticmethod
    def analyze(markets: dict[str, MarketSummary]) -> dict[str, dict[str, Any]]:
        """Analyze statistics by category"""
        category_data: dict[str, dict[str, list]] = {}

        for market in markets.values():
            cat = market.category
            if cat not in category_data:
                category_data[cat] = {
                    "event_scores": [],
                    "ambiguity_risks": [],
                    "near_miss_count": 0,
                    "total_count": 0,
                    "error_count": 0,
                }

            cat_data = category_data[cat]
            cat_data["total_count"] += 1

            if market.avg_event_score is not None:
                cat_data["event_scores"].append(market.avg_event_score)

            if market.avg_ambiguity_risk is not None:
                cat_data["ambiguity_risks"].append(market.avg_ambiguity_risk)

            if market.near_miss_tier_mode in ["tier1_mispricing", "tier2_strong_near_miss", "tier3_weak_near_miss"]:
                cat_data["near_miss_count"] += 1

            if market.llm_success_rate is not None and market.llm_success_rate < 0.5:
                cat_data["error_count"] += 1

        # Calculate aggregated stats
        stats = {}
        for cat, data in category_data.items():
            stats[cat] = {
                "sample_count": data["total_count"],
                "avg_event_score": round(sum(data["event_scores"]) / len(data["event_scores"]), 2) if data["event_scores"] else None,
                "avg_ambiguity_risk": round(sum(data["ambiguity_risks"]) / len(data["ambiguity_risks"]), 2) if data["ambiguity_risks"] else None,
                "near_miss_frequency": round(data["near_miss_count"] / max(1, data["total_count"]), 4),
                "error_rate": round(data["error_count"] / max(1, data["total_count"]), 4),
                "category_risk_score": get_category_risk_score(cat),
            }

        return stats


class ComparisonReportGenerator:
    """Generate comparison reports"""

    @staticmethod
    def generate_markdown(summary: ComparisonSummary, top_n: int = 20) -> str:
        """Generate Markdown comparison report"""
        lines = [
            "# Market Intelligence Comparison Report",
            "",
            "## Run Selection",
            "",
            f"- **Total Runs**: {summary.total_runs}",
            f"- **Selection Criteria**: {summary.selection_criteria}",
            f"- **Date Range**: {summary.date_range.get('earliest', 'N/A')} to {summary.date_range.get('latest', 'N/A')}",
            "",
            "---",
            "",
            "## Summary Statistics",
            "",
            f"- **Total Observed Markets**: {summary.total_observed_markets}",
            f"- **Unique Markets**: {summary.unique_markets}",
            f"- **Total LLM Samples**: {summary.total_llm_samples}",
            f"- **LLM Success Rate**: {summary.llm_success_rate:.1%}",
            f"- **Total Run Duration**: {summary.total_run_duration_minutes:.1f} minutes",
            "",
            "### Near-Miss Distribution Across Runs",
            "",
            f"- **Tier 1: Mispricing Signal**: {summary.total_near_miss_tier1}",
            f"- **Tier 2: Strong Near-Miss**: {summary.total_near_miss_tier2}",
            f"- **Tier 3: Weak Near-Miss / Watchlist**: {summary.total_near_miss_tier3}",
            f"- **Tier 4: Normal but Monitor**: {summary.total_near_miss_tier4}",
            "",
            "---",
            "",
            "## Category Analysis",
            "",
        ]

        # Category stats
        if summary.category_stats:
            lines.append("| Category | Sample Count | Avg Event Score | Avg Ambiguity | Near-Miss Freq | Error Rate |")
            lines.append("|----------|--------------|-----------------|---------------|----------------|------------|")
            for cat, stats in sorted(summary.category_stats.items(), key=lambda x: -x[1]["sample_count"]):
                lines.append(
                    f"| {cat} | {stats['sample_count']} | "
                    f"{stats['avg_event_score'] or 'N/A'} | "
                    f"{stats['avg_ambiguity_risk'] or 'N/A'} | "
                    f"{stats['near_miss_frequency']:.1%} | "
                    f"{stats['error_rate']:.1%} |"
                )
            lines.append("")

        # Persistent watchlist
        lines.extend([
            "---",
            "",
            "## Persistent Watchlist",
            "",
            "*Markets that appeared in multiple runs and meet near-miss or event score criteria.*",
            "",
            f"**Top {min(top_n, len(summary.persistent_watchlist))} of {len(summary.persistent_watchlist)} markets**",
            "",
        ])

        if summary.persistent_watchlist:
            lines.append("| Market ID | Appearances | Avg Combined Ask | Avg Event Score | Tier | Evidence |")
            lines.append("|-----------|-------------|------------------|-----------------|------|----------|")
            for m in summary.persistent_watchlist[:top_n]:
                tier = m.get("near_miss_tier_mode", "N/A")
                if tier:
                    tier = tier.replace("tier1_", "T1: ").replace("tier2_", "T2: ").replace("tier3_", "T3: ").replace("tier4_", "T4: ")
                avg_ask = m.get("avg_combined_ask")
                avg_ask_str = f"{avg_ask:.4f}" if avg_ask is not None else "N/A"
                avg_score = m.get("avg_event_score")
                avg_score_str = f"{avg_score:.1f}" if avg_score is not None else "N/A"
                lines.append(
                    f"| {m['market_id']} | {m['appearances']} | "
                    f"{avg_ask_str} | {avg_score_str} | "
                    f"{tier} | {m.get('evidence_level', 'weak')} |"
                )
            lines.append("")

        # Alpha candidates
        lines.extend([
            "---",
            "",
            "## Alpha Candidates",
            "",
            "**⚠️ IMPORTANT DISCLAIMER**",
            "",
            f"*{AlphaCandidateScorer.DISCLAIMER}*",
            "",
            f"**Top {min(top_n, len(summary.alpha_candidates))} of {len(summary.alpha_candidates)} candidates**",
            "",
        ])

        if summary.alpha_candidates:
            lines.append("| Market ID | Alpha Score | Appearances | Avg Combined Ask | Category | Evidence |")
            lines.append("|-----------|-------------|-------------|------------------|----------|----------|")
            for m in summary.alpha_candidates[:top_n]:
                avg_ask = m.get("avg_combined_ask")
                avg_ask_str = f"{avg_ask:.4f}" if avg_ask is not None else "N/A"
                lines.append(
                    f"| {m['market_id']} | {m['alpha_score']:.1f} | "
                    f"{m['appearances']} | {avg_ask_str} | "
                    f"{m['category']} | {m.get('evidence_level', 'weak')} |"
                )
            lines.append("")

        # Avoid candidates
        lines.extend([
            "---",
            "",
            "## Avoid Candidates",
            "",
            "*Markets with high ambiguity risk, category risk, or other warning signs.*",
            "",
            f"**Top {min(top_n, len(summary.avoid_candidates))} of {len(summary.avoid_candidates)} candidates**",
            "",
        ])

        if summary.avoid_candidates:
            lines.append("| Market ID | Avoid Score | Category | Avg Ambiguity | Reasons | Evidence |")
            lines.append("|-----------|-------------|----------|---------------|---------|----------|")
            for m in summary.avoid_candidates[:top_n]:
                reasons = ", ".join(m.get("reasons", []))
                avg_amb = m.get("avg_ambiguity_risk")
                avg_amb_str = f"{avg_amb:.1f}" if avg_amb is not None else "N/A"
                lines.append(
                    f"| {m['market_id']} | {m['avoid_score']:.1f} | "
                    f"{m['category']} | {avg_amb_str} | "
                    f"{reasons} | {m.get('evidence_level', 'weak')} |"
                )
            lines.append("")

        # Safety verification
        lines.extend([
            "---",
            "",
            "## Safety Verification",
            "",
            f"- {'✅' if summary.all_runs_live_trading_disabled else '❌'} **All runs have live_trading_enabled: False**",
            f"- {'✅' if summary.all_runs_auto_execution_disabled else '❌'} **All runs have allow_auto_execution: False**",
            "",
            "---",
            "",
            "*Generated by PolySignal Pro Multi-Run Intelligence Comparison Analyzer*",
        ])

        return "\n".join(lines)

    @staticmethod
    def generate_json(summary: ComparisonSummary) -> dict:
        """Generate JSON summary"""
        return {
            "run_selection": {
                "runs_dir": summary.runs_dir,
                "total_runs": summary.total_runs,
                "run_ids": summary.run_ids,
                "selection_criteria": summary.selection_criteria,
                "date_range": summary.date_range,
            },
            "summary_statistics": {
                "total_observed_markets": summary.total_observed_markets,
                "unique_markets": summary.unique_markets,
                "total_llm_samples": summary.total_llm_samples,
                "llm_success_rate": summary.llm_success_rate,
                "total_run_duration_minutes": summary.total_run_duration_minutes,
                "near_miss_distribution": {
                    "tier1_mispricing": summary.total_near_miss_tier1,
                    "tier2_strong_near_miss": summary.total_near_miss_tier2,
                    "tier3_weak_near_miss": summary.total_near_miss_tier3,
                    "tier4_normal_monitor": summary.total_near_miss_tier4,
                },
            },
            "category_analysis": summary.category_stats,
            "persistent_watchlist_count": len(summary.persistent_watchlist),
            "alpha_candidates_count": len(summary.alpha_candidates),
            "avoid_candidates_count": len(summary.avoid_candidates),
            "alpha_disclaimer": AlphaCandidateScorer.DISCLAIMER,
            "safety_verification": {
                "all_runs_live_trading_disabled": summary.all_runs_live_trading_disabled,
                "all_runs_auto_execution_disabled": summary.all_runs_auto_execution_disabled,
            },
        }

    @staticmethod
    def export_csvs(summary: ComparisonSummary, output_dir: Path) -> None:
        """Export CSV files"""
        # Persistent watchlist
        if summary.persistent_watchlist:
            csv_path = output_dir / "persistent_watchlist.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "market_id", "matched_by", "question", "category", "appearances",
                    "avg_combined_ask", "avg_event_score", "avg_ambiguity_risk",
                    "near_miss_tier_mode", "suggested_mode_mode", "evidence_level", "run_ids"
                ])
                writer.writeheader()
                for m in summary.persistent_watchlist:
                    m_copy = m.copy()
                    m_copy["run_ids"] = "|".join(m_copy.get("run_ids", []))
                    writer.writerow(m_copy)
            print(f"Persistent watchlist: {csv_path}")

        # Alpha candidates
        if summary.alpha_candidates:
            csv_path = output_dir / "alpha_candidates.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "market_id", "matched_by", "question", "category", "appearances",
                    "avg_combined_ask", "avg_event_score", "avg_ambiguity_risk", "avg_volume",
                    "alpha_score", "evidence_level", "run_ids"
                ])
                writer.writeheader()
                for m in summary.alpha_candidates:
                    m_copy = m.copy()
                    m_copy["run_ids"] = "|".join(m_copy.get("run_ids", []))
                    writer.writerow(m_copy)
            print(f"Alpha candidates: {csv_path}")

        # Avoid candidates
        if summary.avoid_candidates:
            csv_path = output_dir / "avoid_candidates.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "market_id", "matched_by", "question", "category", "appearances",
                    "avg_ambiguity_risk", "avg_volume", "llm_success_rate",
                    "avoid_score", "evidence_level", "reasons", "run_ids"
                ])
                writer.writeheader()
                for m in summary.avoid_candidates:
                    m_copy = m.copy()
                    m_copy["run_ids"] = "|".join(m_copy.get("run_ids", []))
                    m_copy["reasons"] = "|".join(m_copy.get("reasons", []))
                    writer.writerow(m_copy)
            print(f"Avoid candidates: {csv_path}")

    @staticmethod
    def export_trajectories(markets: dict[str, MarketSummary], output_path: Path) -> None:
        """Export market trajectories to JSON"""
        trajectories = []

        for market in markets.values():
            if len(market.observations) < 2:
                continue

            trajectory = {
                "market_id": market.market_id,
                "matched_by": market.matched_by,
                "question": market.question,
                "category": market.category,
                "trajectory": [
                    {
                        "run_id": obs.run_id,
                        "timestamp": obs.timestamp,
                        "combined_ask": obs.combined_ask,
                        "event_score": obs.event_score,
                        "suggested_mode": obs.suggested_mode,
                        "ambiguity_risk": obs.ambiguity_risk,
                        "confidence": obs.confidence,
                    }
                    for obs in sorted(market.observations, key=lambda o: o.timestamp)
                ],
                "summary": {
                    "appearances": market.appearances,
                    "avg_combined_ask": market.avg_combined_ask,
                    "avg_event_score": market.avg_event_score,
                    "evidence_level": market.evidence_level,
                }
            }

            # Determine trends
            combined_asks = [o.combined_ask for o in market.observations if o.combined_ask is not None]
            if len(combined_asks) >= 2:
                if combined_asks[-1] < combined_asks[0]:
                    trajectory["trend"] = {"combined_ask_direction": "decreasing"}
                elif combined_asks[-1] > combined_asks[0]:
                    trajectory["trend"] = {"combined_ask_direction": "increasing"}
                else:
                    trajectory["trend"] = {"combined_ask_direction": "stable"}

            trajectories.append(trajectory)

        # Sort by appearances
        trajectories.sort(key=lambda t: -t["summary"]["appearances"])

        with open(output_path, "w") as f:
            json.dump(trajectories, f, indent=2)

        print(f"Market trajectories: {output_path}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Multi-Run Intelligence Comparison - Phase 5F",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 scripts/compare_run_intelligence.py --runs_dir runs --latest_n 5
    python3 scripts/compare_run_intelligence.py --run_ids run_20260509_112002_8977ca4e,run_20260508_155427_612f24ff
    python3 scripts/compare_run_intelligence.py --runs_dir runs --since 2026-05-01 --top_n 20 --export_csv

IMPORTANT: Alpha score is a HEURISTIC RESEARCH RANKING, NOT a trading signal.
Candidates require further paper trading validation before any execution.
        """,
    )

    # Run selection
    parser.add_argument(
        "--runs_dir",
        type=str,
        default="runs",
        help="Directory containing run directories (default: runs/)",
    )
    parser.add_argument(
        "--run_ids",
        type=str,
        help="Comma-separated list of run IDs to analyze",
    )
    parser.add_argument(
        "--latest_n",
        type=int,
        help="Analyze the latest N runs",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Analyze runs since date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--min_runs",
        type=int,
        default=2,
        help="Minimum number of runs required (default: 2)",
    )

    # Output options
    parser.add_argument(
        "--output_dir",
        type=str,
        help="Output directory (default: same as runs_dir)",
    )
    parser.add_argument(
        "--top_n",
        type=int,
        default=20,
        help="Number of top candidates to include in report (default: 20)",
    )
    parser.add_argument(
        "--min_appearances",
        type=int,
        default=2,
        help="Minimum appearances for watchlist inclusion (default: 2)",
    )
    parser.add_argument(
        "--export_csv",
        action="store_true",
        help="Export CSV files",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point"""
    args = parse_args()

    # Determine output directory
    output_dir = Path(args.output_dir) if args.output_dir else Path(args.runs_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover runs
    runs_dir = Path(args.runs_dir)

    run_ids = args.run_ids.split(",") if args.run_ids else None

    print(f"Discovering runs in {runs_dir}...")
    run_paths = RunDiscovery.discover_runs(
        runs_dir=runs_dir,
        run_ids=run_ids,
        latest_n=args.latest_n,
        since=args.since,
        min_runs=args.min_runs,
    )

    if len(run_paths) < args.min_runs:
        print(f"Error: Need at least {args.min_runs} runs, found {len(run_paths)}")
        sys.exit(1)

    print(f"Found {len(run_paths)} runs:")
    for p in run_paths:
        print(f"  - {p.name}")

    # Load run data
    print("\nLoading run data...")
    runs_data = []
    for run_path in run_paths:
        print(f"  Loading {run_path.name}...")
        run_summary = RunDataLoader.load_run(run_path)
        runs_data.append(run_summary)

    # Aggregate markets
    print("\nAggregating market data...")
    markets = MarketAggregator.aggregate_markets(runs_data, min_appearances=1)
    MarketAggregator.calculate_aggregated_metrics(markets, len(runs_data))
    print(f"  Found {len(markets)} unique markets")

    # Create comparison summary
    summary = ComparisonSummary(
        runs_dir=str(runs_dir),
        total_runs=len(runs_data),
        run_ids=[r.run_id for r in runs_data],
        selection_criteria=_format_selection_criteria(args),
        date_range=_calculate_date_range(runs_data),
        unique_markets=len(markets),
    )

    # Aggregate run-level stats
    for run in runs_data:
        summary.total_observed_markets += run.total_observed_markets
        summary.total_llm_samples += run.llm_total_samples
        summary.llm_successful_samples += run.llm_successful_samples
        summary.total_run_duration_minutes += run.duration_minutes

        for tier, count in run.near_miss_tier_distribution.items():
            if tier == "tier1_mispricing":
                summary.total_near_miss_tier1 += count
            elif tier == "tier2_strong_near_miss":
                summary.total_near_miss_tier2 += count
            elif tier == "tier3_weak_near_miss":
                summary.total_near_miss_tier3 += count
            elif tier == "tier4_normal_monitor":
                summary.total_near_miss_tier4 += count

        if run.live_trading_enabled:
            summary.all_runs_live_trading_disabled = False
        if run.allow_auto_execution:
            summary.all_runs_auto_execution_disabled = False

    # Calculate success rate
    if summary.total_llm_samples > 0:
        summary.llm_success_rate = summary.llm_successful_samples / summary.total_llm_samples

    # Category analysis
    print("Analyzing categories...")
    summary.category_stats = CategoryAnalyzer.analyze(markets)

    # Generate watchlist
    print("Generating persistent watchlist...")
    summary.persistent_watchlist = PersistentWatchlistGenerator.generate(
        markets, len(runs_data), top_n=args.top_n
    )
    print(f"  Found {len(summary.persistent_watchlist)} watchlist candidates")

    # Generate alpha candidates
    print("Scoring alpha candidates...")
    summary.alpha_candidates = AlphaCandidateScorer.rank_candidates(
        markets, len(runs_data), top_n=args.top_n
    )
    print(f"  Found {len(summary.alpha_candidates)} alpha candidates")

    # Generate avoid candidates
    print("Scoring avoid candidates...")
    summary.avoid_candidates = AvoidCandidateScorer.rank_candidates(
        markets, len(runs_data), top_n=args.top_n
    )
    print(f"  Found {len(summary.avoid_candidates)} avoid candidates")

    # Generate reports
    print("\nGenerating reports...")

    # Markdown report
    report_path = output_dir / "intelligence_comparison_report.md"
    report_content = ComparisonReportGenerator.generate_markdown(summary, top_n=args.top_n)
    with open(report_path, "w") as f:
        f.write(report_content)
    print(f"Markdown report: {report_path}")

    # JSON summary
    summary_path = output_dir / "intelligence_comparison_summary.json"
    summary_json = ComparisonReportGenerator.generate_json(summary)
    with open(summary_path, "w") as f:
        json.dump(summary_json, f, indent=2)
    print(f"JSON summary: {summary_path}")

    # CSV exports
    if args.export_csv:
        ComparisonReportGenerator.export_csvs(summary, output_dir)

    # Market trajectories
    trajectories_path = output_dir / "market_trajectories.json"
    ComparisonReportGenerator.export_trajectories(markets, trajectories_path)

    # Print summary
    print("\n=== Comparison Complete ===")
    print(f"Total runs: {summary.total_runs}")
    print(f"Unique markets: {summary.unique_markets}")
    print(f"Persistent watchlist: {len(summary.persistent_watchlist)} markets")
    print(f"Alpha candidates: {len(summary.alpha_candidates)} markets")
    print(f"Avoid candidates: {len(summary.avoid_candidates)} markets")
    print(f"All runs have live_trading_enabled=False: {summary.all_runs_live_trading_disabled}")
    print(f"\n⚠️ {AlphaCandidateScorer.DISCLAIMER}")


def _format_selection_criteria(args: argparse.Namespace) -> str:
    """Format selection criteria string"""
    criteria = []
    if args.run_ids:
        criteria.append(f"run_ids={args.run_ids}")
    if args.latest_n:
        criteria.append(f"latest_n={args.latest_n}")
    if args.since:
        criteria.append(f"since={args.since}")
    if not criteria:
        criteria.append("all runs in directory")
    return ", ".join(criteria)


def _calculate_date_range(runs_data: list[RunSummary]) -> dict[str, str]:
    """Calculate date range from runs"""
    dates = []
    for run in runs_data:
        # Extract date from run_id (format: run_YYYYMMDD_HHMMSS_hash)
        parts = run.run_id.split("_")
        if len(parts) >= 2:
            try:
                dt = datetime.strptime(parts[1], "%Y%m%d")
                dates.append(dt.strftime("%Y-%m-%d"))
            except ValueError:
                continue

    if dates:
        return {"earliest": min(dates), "latest": max(dates)}
    return {}


if __name__ == "__main__":
    main()
