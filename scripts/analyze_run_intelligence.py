#!/usr/bin/env python3
"""
Market Intelligence Report Analyzer - Phase 5E

Analyze run data to generate Market Intelligence Reports for alpha discovery.

IMPORTANT:
- This is an OFFLINE analysis tool
- No real-time API calls
- No trading execution
- live_trading_enabled must remain false

Usage:
    python3 scripts/analyze_run_intelligence.py --run_id run_20260509_112002_8977ca4e
    python3 scripts/analyze_run_intelligence.py --run_dir runs/run_20260509_112002_8977ca4e
    python3 scripts/analyze_run_intelligence.py --latest --export_csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Near-miss tier definitions
NEAR_MISS_TIERS = {
    "tier1_mispricing": {"min": 0.0, "max": 0.985, "label": "Tier 1: Mispricing Signal"},
    "tier2_strong_near_miss": {"min": 0.985, "max": 1.000, "label": "Tier 2: Strong Near-Miss"},
    "tier3_weak_near_miss": {"min": 1.000, "max": 1.010, "label": "Tier 3: Weak Near-Miss / Watchlist"},
    "tier4_normal_monitor": {"min": 1.010, "max": 1.030, "label": "Tier 4: Normal but Monitor"},
}


def classify_near_miss_tier(combined_ask: float) -> Optional[str]:
    """Classify combined_ask into near-miss tier"""
    # Handle negative combined_ask as mispricing signal
    if combined_ask < 0:
        return "tier1_mispricing"

    for tier_key, tier_def in NEAR_MISS_TIERS.items():
        if tier_def["min"] <= combined_ask < tier_def["max"]:
            return tier_key
    return None


def infer_market_category(question: str) -> str:
    """
    Infer market category from question text.

    NOTE: This is a HEURISTIC classification based on keywords.
    It should be treated as an approximation, not a definitive label.
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

    # Crypto keywords (use specific patterns to avoid false matches)
    crypto_keywords = [
        "bitcoin", "btc", "ethereum", "crypto",
        "solana", "token", "hit $", "market cap", "defi", "nft",
    ]
    for kw in crypto_keywords:
        if kw in question_lower:
            return "Crypto"
    # Check for "eth" as standalone (not inside "something")
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


@dataclass
class ObservedMarket:
    """Market observed during run (from combined_ask observations)"""
    market_id: str
    combined_ask: float
    near_miss_tier: Optional[str] = None
    category: str = "Other"

    # Optional fields from LLM sampling
    event_score: Optional[float] = None
    confidence: Optional[float] = None
    suggested_mode: Optional[str] = None
    evidence_strength: Optional[float] = None
    market_relevance: Optional[float] = None
    ambiguity_risk: Optional[float] = None
    risk_flags: list[str] = field(default_factory=list)
    latency_seconds: Optional[float] = None
    llm_success: Optional[bool] = None
    llm_error: Optional[str] = None
    question: Optional[str] = None
    volume_24h: Optional[float] = None


@dataclass
class IntelligenceSummary:
    """Summary of market intelligence analysis"""

    # Run info
    run_id: str
    analysis_timestamp: str
    run_duration_minutes: float
    data_mode: str
    llm_provider: str

    # All observed markets
    total_observed_markets: int = 0
    combined_ask_distribution: dict[str, Any] = field(default_factory=dict)

    # Near-miss analysis
    near_miss_tier_distribution: dict[str, int] = field(default_factory=dict)
    top_near_miss_markets: list[dict[str, Any]] = field(default_factory=list)

    # LLM sampling summary
    llm_total_samples: int = 0
    llm_successful_samples: int = 0
    llm_failed_samples: int = 0
    llm_avg_event_score: Optional[float] = None
    llm_avg_confidence: Optional[float] = None
    llm_avg_latency: Optional[float] = None
    llm_suggested_mode_distribution: dict[str, int] = field(default_factory=dict)

    # Category distribution (heuristic)
    category_distribution: dict[str, int] = field(default_factory=dict)
    category_note: str = "Market category is inferred from keywords and should be treated as heuristic."

    # Correlation analysis
    correlation_sample_size: int = 0
    event_score_vs_combined_ask_correlation: Optional[float] = None
    correlation_note: str = ""

    # Top candidates
    top_high_event_score_markets: list[dict[str, Any]] = field(default_factory=list)
    top_high_ambiguity_markets: list[dict[str, Any]] = field(default_factory=list)
    top_research_markets: list[dict[str, Any]] = field(default_factory=list)
    top_avoid_markets: list[dict[str, Any]] = field(default_factory=list)
    top_monitor_markets: list[dict[str, Any]] = field(default_factory=list)

    # Safety verification
    live_trading_enabled: bool = False
    allow_auto_execution: bool = False


class IntelligenceAnalyzer:
    """
    Analyze run data to generate Market Intelligence Reports.

    IMPORTANT:
    - This is an OFFLINE analysis tool
    - No real-time API calls
    - No trading execution
    """

    def __init__(self, run_dir: Path):
        """Initialize analyzer with run directory"""
        self.run_dir = run_dir
        self.run_id = run_dir.name
        self.events_file = run_dir / "events.jsonl"
        self.summary_file = run_dir / "summary.json"

        self.events: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = {}
        self.observed_markets: dict[str, ObservedMarket] = {}

    def load_data(self) -> bool:
        """Load events.jsonl and summary.json"""
        # Load events
        if not self.events_file.exists():
            print(f"Error: events.jsonl not found at {self.events_file}")
            return False

        with open(self.events_file, "r") as f:
            self.events = [json.loads(line) for line in f if line.strip()]

        # Load summary
        if not self.summary_file.exists():
            print(f"Error: summary.json not found at {self.summary_file}")
            return False

        with open(self.summary_file, "r") as f:
            self.summary = json.load(f)

        return True

    def analyze(self) -> IntelligenceSummary:
        """Run full analysis"""
        summary = IntelligenceSummary(
            run_id=self.run_id,
            analysis_timestamp=datetime.utcnow().isoformat(),
            run_duration_minutes=self.summary.get("duration_minutes", 0),
            data_mode=self.summary.get("data_mode", "unknown"),
            llm_provider=self.summary.get("llm_provider", "unknown"),
            live_trading_enabled=self.summary.get("live_trading_enabled", False),
            allow_auto_execution=self.summary.get("allow_auto_execution", False),
        )

        # Extract combined_ask distribution from summary
        summary.combined_ask_distribution = self.summary.get("combined_ask_distribution", {})

        # Process events
        self._process_events(summary)

        # Calculate statistics
        self._calculate_statistics(summary)

        # Generate top candidates
        self._generate_top_candidates(summary)

        return summary

    def _process_events(self, summary: IntelligenceSummary) -> None:
        """Process all events to extract market data"""
        for event in self.events:
            event_type = event.get("event_type", "")
            details = event.get("details") or {}

            # Process LLM sampling assessments
            if event_type == "llm_sampling_assessment":
                self._process_llm_sampling_event(details, summary)

            # Process combined_ask observations from scan events
            elif event_type == "scan_end":
                # Scan events don't have combined_ask directly, but we can track markets
                pass

    def _process_llm_sampling_event(self, details: dict[str, Any], summary: IntelligenceSummary) -> None:
        """Process a single LLM sampling assessment event"""
        market_id = details.get("market_id")
        if not market_id:
            return

        combined_ask = details.get("combined_ask")
        question = details.get("question", "")

        # Create or update observed market
        if market_id not in self.observed_markets:
            self.observed_markets[market_id] = ObservedMarket(
                market_id=market_id,
                combined_ask=combined_ask if combined_ask else 0.0,
                question=question,
                category=infer_market_category(question) if question else "Other",
            )

        market = self.observed_markets[market_id]

        # Update with LLM data
        market.event_score = details.get("event_score")
        market.confidence = details.get("confidence")
        market.suggested_mode = details.get("suggested_mode")
        market.evidence_strength = details.get("evidence_strength")
        market.market_relevance = details.get("market_relevance")
        market.ambiguity_risk = details.get("ambiguity_risk")
        market.risk_flags = details.get("risk_flags", [])
        market.latency_seconds = details.get("latency_seconds")
        market.llm_success = details.get("success")
        market.llm_error = details.get("error")
        market.volume_24h = details.get("volume_24h")

        # Classify near-miss tier
        if combined_ask:
            market.near_miss_tier = classify_near_miss_tier(combined_ask)

        # Update LLM sampling counts
        summary.llm_total_samples += 1
        if details.get("success"):
            summary.llm_successful_samples += 1
        else:
            summary.llm_failed_samples += 1

        # Track suggested_mode distribution
        suggested_mode = details.get("suggested_mode")
        if suggested_mode:
            summary.llm_suggested_mode_distribution[suggested_mode] = \
                summary.llm_suggested_mode_distribution.get(suggested_mode, 0) + 1

    def _calculate_statistics(self, summary: IntelligenceSummary) -> None:
        """Calculate aggregate statistics"""
        if not self.observed_markets:
            return

        summary.total_observed_markets = len(self.observed_markets)

        # Near-miss tier distribution
        for market in self.observed_markets.values():
            if market.near_miss_tier:
                summary.near_miss_tier_distribution[market.near_miss_tier] = \
                    summary.near_miss_tier_distribution.get(market.near_miss_tier, 0) + 1

            # Category distribution
            summary.category_distribution[market.category] = \
                summary.category_distribution.get(market.category, 0) + 1

        # LLM statistics
        llm_markets = [m for m in self.observed_markets.values() if m.llm_success is not None]
        successful_llm = [m for m in llm_markets if m.llm_success]

        if successful_llm:
            event_scores = [m.event_score for m in successful_llm if m.event_score is not None]
            confidences = [m.confidence for m in successful_llm if m.confidence is not None]
            latencies = [m.latency_seconds for m in successful_llm if m.latency_seconds is not None]

            if event_scores:
                summary.llm_avg_event_score = sum(event_scores) / len(event_scores)
            if confidences:
                summary.llm_avg_confidence = sum(confidences) / len(confidences)
            if latencies:
                summary.llm_avg_latency = sum(latencies) / len(latencies)

        # Correlation analysis with sample size protection
        self._calculate_correlation(summary, successful_llm)

    def _calculate_correlation(self, summary: IntelligenceSummary, markets: list[ObservedMarket]) -> None:
        """Calculate correlation between event_score and combined_ask with sample size protection"""
        valid_pairs = [
            (m.event_score, m.combined_ask)
            for m in markets
            if m.event_score is not None and m.combined_ask is not None
        ]

        summary.correlation_sample_size = len(valid_pairs)

        if len(valid_pairs) < 10:
            summary.correlation_note = "Insufficient sample size (< 10) for correlation analysis."
            return

        # Calculate Pearson correlation
        n = len(valid_pairs)
        sum_x = sum(p[0] for p in valid_pairs)
        sum_y = sum(p[1] for p in valid_pairs)
        sum_xy = sum(p[0] * p[1] for p in valid_pairs)
        sum_x2 = sum(p[0] ** 2 for p in valid_pairs)
        sum_y2 = sum(p[1] ** 2 for p in valid_pairs)

        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x2 - sum_x ** 2) ** 0.5) * ((n * sum_y2 - sum_y ** 2) ** 0.5)

        if denominator == 0:
            summary.correlation_note = "Cannot calculate correlation (zero variance)."
            return

        correlation = numerator / denominator
        summary.event_score_vs_combined_ask_correlation = round(correlation, 4)

        if len(valid_pairs) < 30:
            summary.correlation_note = (
                "Exploratory correlation (sample size 10-29). "
                "Correlation is exploratory and not causal."
            )
        else:
            summary.correlation_note = (
                f"Correlation based on {len(valid_pairs)} samples. "
                "Correlation is exploratory and not causal."
            )

    def _generate_top_candidates(self, summary: IntelligenceSummary) -> None:
        """Generate top candidate lists"""
        markets = list(self.observed_markets.values())

        # Top near-miss markets (lowest combined_ask)
        near_miss_markets = [
            m for m in markets
            if m.near_miss_tier and m.near_miss_tier in ["tier1_mispricing", "tier2_strong_near_miss", "tier3_weak_near_miss"]
        ]
        near_miss_markets.sort(key=lambda m: m.combined_ask)
        summary.top_near_miss_markets = [
            self._market_to_dict(m) for m in near_miss_markets[:10]
        ]

        # Top high event_score markets
        llm_markets = [m for m in markets if m.event_score is not None]
        llm_markets.sort(key=lambda m: m.event_score or 0, reverse=True)
        summary.top_high_event_score_markets = [
            self._market_to_dict(m) for m in llm_markets[:10]
        ]

        # Top high ambiguity markets
        ambiguity_markets = [m for m in markets if m.ambiguity_risk is not None]
        ambiguity_markets.sort(key=lambda m: m.ambiguity_risk or 0, reverse=True)
        summary.top_high_ambiguity_markets = [
            self._market_to_dict(m) for m in ambiguity_markets[:10]
        ]

        # Top research markets (suggested_mode == "research")
        research_markets = [m for m in markets if m.suggested_mode == "research"]
        research_markets.sort(key=lambda m: m.event_score or 0, reverse=True)
        summary.top_research_markets = [
            self._market_to_dict(m) for m in research_markets[:10]
        ]

        # Top avoid markets (suggested_mode == "avoid")
        avoid_markets = [m for m in markets if m.suggested_mode == "avoid"]
        avoid_markets.sort(key=lambda m: m.ambiguity_risk or 0, reverse=True)
        summary.top_avoid_markets = [
            self._market_to_dict(m) for m in avoid_markets[:10]
        ]

        # Top monitor markets (tier3 or tier4)
        monitor_markets = [
            m for m in markets
            if m.near_miss_tier in ["tier3_weak_near_miss", "tier4_normal_monitor"]
        ]
        monitor_markets.sort(key=lambda m: m.combined_ask)
        summary.top_monitor_markets = [
            self._market_to_dict(m) for m in monitor_markets[:10]
        ]

    def _market_to_dict(self, market: ObservedMarket) -> dict[str, Any]:
        """Convert ObservedMarket to dictionary"""
        return {
            "market_id": market.market_id,
            "question": market.question[:100] if market.question else None,
            "combined_ask": market.combined_ask,
            "near_miss_tier": market.near_miss_tier,
            "category": market.category,
            "event_score": market.event_score,
            "confidence": market.confidence,
            "suggested_mode": market.suggested_mode,
            "ambiguity_risk": market.ambiguity_risk,
            "risk_flags": market.risk_flags,
            "latency_seconds": market.latency_seconds,
            "llm_success": market.llm_success,
        }

    def generate_markdown_report(self, summary: IntelligenceSummary) -> str:
        """Generate Markdown intelligence report"""
        lines = [
            f"# Market Intelligence Report",
            "",
            f"## Run Information",
            "",
            f"- **Run ID**: {summary.run_id}",
            f"- **Analysis Timestamp**: {summary.analysis_timestamp}",
            f"- **Duration**: {summary.run_duration_minutes:.1f} minutes",
            f"- **Data Mode**: {summary.data_mode}",
            f"- **LLM Provider**: {summary.llm_provider}",
            "",
            "---",
            "",
            "## All Observed Markets Analysis",
            "",
            f"- **Total Observed Markets**: {summary.total_observed_markets}",
            "",
            "### Combined Ask Distribution",
            "",
        ]

        dist = summary.combined_ask_distribution
        if dist.get("observation_count", 0) > 0:
            lines.extend([
                f"- **Observations**: {dist.get('observation_count', 0)}",
                f"- **Min**: {dist.get('min', 'N/A'):.4f}" if dist.get('min') else "- **Min**: N/A",
                f"- **Max**: {dist.get('max', 'N/A'):.4f}" if dist.get('max') else "- **Max**: N/A",
                f"- **Median**: {dist.get('median', 'N/A'):.4f}" if dist.get('median') else "- **Median**: N/A",
                f"- **P5**: {dist.get('p5', 'N/A'):.4f}" if dist.get('p5') else "- **P5**: N/A",
                f"- **P95**: {dist.get('p95', 'N/A'):.4f}" if dist.get('p95') else "- **P95**: N/A",
            ])

        # Near-miss tier distribution
        lines.extend([
            "",
            "### Near-Miss Tier Distribution",
            "",
        ])

        for tier_key, tier_def in NEAR_MISS_TIERS.items():
            count = summary.near_miss_tier_distribution.get(tier_key, 0)
            lines.append(f"- **{tier_def['label']}**: {count}")

        # LLM Sampling Summary
        lines.extend([
            "",
            "---",
            "",
            "## LLM Sampling Analysis",
            "",
            f"- **Total Samples**: {summary.llm_total_samples}",
            f"- **Successful**: {summary.llm_successful_samples}",
            f"- **Failed**: {summary.llm_failed_samples}",
        ])

        if summary.llm_avg_event_score is not None:
            lines.append(f"- **Avg Event Score**: {summary.llm_avg_event_score:.2f}")
        if summary.llm_avg_confidence is not None:
            lines.append(f"- **Avg Confidence**: {summary.llm_avg_confidence:.2f}")
        if summary.llm_avg_latency is not None:
            lines.append(f"- **Avg Latency**: {summary.llm_avg_latency:.2f}s")

        # Suggested mode distribution
        if summary.llm_suggested_mode_distribution:
            lines.extend([
                "",
                "### Suggested Mode Distribution",
                "",
            ])
            for mode, count in sorted(summary.llm_suggested_mode_distribution.items()):
                lines.append(f"- **{mode}**: {count}")

        # Category distribution
        if summary.category_distribution:
            lines.extend([
                "",
                "### Category Distribution (Heuristic)",
                "",
                f"*{summary.category_note}*",
                "",
            ])
            for category, count in sorted(summary.category_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"- **{category}**: {count}")

        # Correlation analysis
        lines.extend([
            "",
            "---",
            "",
            "## LLM vs Orderbook Correlation",
            "",
        ])

        if summary.event_score_vs_combined_ask_correlation is not None:
            lines.append(f"- **Event Score vs Combined Ask Correlation**: {summary.event_score_vs_combined_ask_correlation:.4f}")
        lines.append(f"- **Sample Size**: {summary.correlation_sample_size}")
        lines.append(f"- **Note**: {summary.correlation_note}")

        # Top candidates sections
        lines.extend([
            "",
            "---",
            "",
            "## Top Candidates",
            "",
        ])

        # Top near-miss markets
        if summary.top_near_miss_markets:
            lines.extend([
                "",
                "### Top Near-Miss Markets",
                "",
            ])
            for m in summary.top_near_miss_markets[:5]:
                tier_label = NEAR_MISS_TIERS.get(m.get("near_miss_tier", ""), {}).get("label", m.get("near_miss_tier", ""))
                lines.append(f"- **{m['market_id']}** (combined_ask: {m['combined_ask']:.4f}, {tier_label})")
                if m.get("question"):
                    lines.append(f"  - Question: {m['question'][:80]}...")

        # Top high event_score markets
        if summary.top_high_event_score_markets:
            lines.extend([
                "",
                "### Top High Event Score Markets",
                "",
            ])
            for m in summary.top_high_event_score_markets[:5]:
                lines.append(f"- **{m['market_id']}** (event_score: {m.get('event_score', 'N/A')}, confidence: {m.get('confidence', 'N/A')})")
                if m.get("question"):
                    lines.append(f"  - Question: {m['question'][:80]}...")

        # Top high ambiguity markets
        if summary.top_high_ambiguity_markets:
            lines.extend([
                "",
                "### Top High Ambiguity Risk Markets",
                "",
            ])
            for m in summary.top_high_ambiguity_markets[:5]:
                lines.append(f"- **{m['market_id']}** (ambiguity_risk: {m.get('ambiguity_risk', 'N/A')})")
                if m.get("question"):
                    lines.append(f"  - Question: {m['question'][:80]}...")

        # Top research markets
        if summary.top_research_markets:
            lines.extend([
                "",
                "### Top Research Markets",
                "",
            ])
            for m in summary.top_research_markets[:5]:
                lines.append(f"- **{m['market_id']}** (event_score: {m.get('event_score', 'N/A')})")
                if m.get("question"):
                    lines.append(f"  - Question: {m['question'][:80]}...")

        # Top avoid markets
        if summary.top_avoid_markets:
            lines.extend([
                "",
                "### Top Avoid Markets",
                "",
            ])
            for m in summary.top_avoid_markets[:5]:
                lines.append(f"- **{m['market_id']}** (ambiguity_risk: {m.get('ambiguity_risk', 'N/A')})")
                if m.get("question"):
                    lines.append(f"  - Question: {m['question'][:80]}...")

        # Top monitor markets
        if summary.top_monitor_markets:
            lines.extend([
                "",
                "### Top Markets for Further Monitoring",
                "",
            ])
            for m in summary.top_monitor_markets[:5]:
                lines.append(f"- **{m['market_id']}** (combined_ask: {m.get('combined_ask', 'N/A'):.4f})")
                if m.get("question"):
                    lines.append(f"  - Question: {m['question'][:80]}...")

        # Safety verification
        lines.extend([
            "",
            "---",
            "",
            "## Safety Verification",
            "",
            f"- {'✅' if not summary.live_trading_enabled else '❌'} **live_trading_enabled**: {summary.live_trading_enabled}",
            f"- {'✅' if not summary.allow_auto_execution else '❌'} **allow_auto_execution**: {summary.allow_auto_execution}",
            "",
            "---",
            "",
            "*Generated by PolySignal Pro Market Intelligence Analyzer*",
        ])

        return "\n".join(lines)

    def export_csv(self, output_path: Path) -> None:
        """Export sampled markets to CSV"""
        if not self.observed_markets:
            print("No markets to export")
            return

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                "market_id", "question", "combined_ask", "near_miss_tier", "category",
                "event_score", "confidence", "suggested_mode", "evidence_strength",
                "market_relevance", "ambiguity_risk", "risk_flags", "latency_seconds",
                "llm_success", "llm_error"
            ])

            # Data
            for market in self.observed_markets.values():
                writer.writerow([
                    market.market_id,
                    market.question[:100] if market.question else "",
                    market.combined_ask,
                    market.near_miss_tier or "",
                    market.category,
                    market.event_score or "",
                    market.confidence or "",
                    market.suggested_mode or "",
                    market.evidence_strength or "",
                    market.market_relevance or "",
                    market.ambiguity_risk or "",
                    ";".join(market.risk_flags) if market.risk_flags else "",
                    market.latency_seconds or "",
                    market.llm_success or "",
                    market.llm_error or "",
                ])

        print(f"CSV exported to: {output_path}")


def find_latest_run() -> Optional[Path]:
    """Find the latest run directory"""
    runs_dir = Path("runs")
    if not runs_dir.exists():
        return None

    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
    if not run_dirs:
        return None

    # Sort by name (which includes timestamp)
    run_dirs.sort(reverse=True)
    return run_dirs[0]


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Market Intelligence Report Analyzer - Phase 5E",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 scripts/analyze_run_intelligence.py --run_id run_20260509_112002_8977ca4e
    python3 scripts/analyze_run_intelligence.py --run_dir runs/run_20260509_112002_8977ca4e
    python3 scripts/analyze_run_intelligence.py --latest --export_csv
        """,
    )

    # Run identification (mutually exclusive)
    run_group = parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument(
        "--run_id",
        type=str,
        help="Run ID to analyze",
    )
    run_group.add_argument(
        "--run_dir",
        type=str,
        help="Path to run directory",
    )
    run_group.add_argument(
        "--latest",
        action="store_true",
        help="Analyze the latest run",
    )

    # Export options
    parser.add_argument(
        "--export_csv",
        action="store_true",
        help="Export sampled markets to CSV",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point"""
    args = parse_args()

    # Determine run directory
    if args.run_id:
        run_dir = Path("runs") / args.run_id
    elif args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.latest:
        run_dir = find_latest_run()
        if not run_dir:
            print("Error: No runs found")
            sys.exit(1)
        print(f"Analyzing latest run: {run_dir.name}")
    else:
        print("Error: Must specify --run_id, --run_dir, or --latest")
        sys.exit(1)

    if not run_dir.exists():
        print(f"Error: Run directory not found: {run_dir}")
        sys.exit(1)

    # Initialize analyzer
    analyzer = IntelligenceAnalyzer(run_dir)

    # Load data
    print(f"Loading data from {run_dir}...")
    if not analyzer.load_data():
        sys.exit(1)

    # Run analysis
    print("Running analysis...")
    summary = analyzer.analyze()

    # Generate outputs
    print("Generating reports...")

    # Markdown report
    report_path = run_dir / "intelligence_report.md"
    report_content = analyzer.generate_markdown_report(summary)
    with open(report_path, "w") as f:
        f.write(report_content)
    print(f"Markdown report: {report_path}")

    # JSON summary
    summary_path = run_dir / "intelligence_summary.json"

    # Convert summary to dict
    summary_dict = {
        "run_id": summary.run_id,
        "analysis_timestamp": summary.analysis_timestamp,
        "run_duration_minutes": summary.run_duration_minutes,
        "data_mode": summary.data_mode,
        "llm_provider": summary.llm_provider,
        "total_observed_markets": summary.total_observed_markets,
        "combined_ask_distribution": summary.combined_ask_distribution,
        "near_miss_tier_distribution": summary.near_miss_tier_distribution,
        "llm_total_samples": summary.llm_total_samples,
        "llm_successful_samples": summary.llm_successful_samples,
        "llm_failed_samples": summary.llm_failed_samples,
        "llm_avg_event_score": summary.llm_avg_event_score,
        "llm_avg_confidence": summary.llm_avg_confidence,
        "llm_avg_latency": summary.llm_avg_latency,
        "llm_suggested_mode_distribution": summary.llm_suggested_mode_distribution,
        "category_distribution": summary.category_distribution,
        "category_note": summary.category_note,
        "correlation_sample_size": summary.correlation_sample_size,
        "event_score_vs_combined_ask_correlation": summary.event_score_vs_combined_ask_correlation,
        "correlation_note": summary.correlation_note,
        "top_near_miss_markets": summary.top_near_miss_markets,
        "top_high_event_score_markets": summary.top_high_event_score_markets,
        "top_high_ambiguity_markets": summary.top_high_ambiguity_markets,
        "top_research_markets": summary.top_research_markets,
        "top_avoid_markets": summary.top_avoid_markets,
        "top_monitor_markets": summary.top_monitor_markets,
        "live_trading_enabled": summary.live_trading_enabled,
        "allow_auto_execution": summary.allow_auto_execution,
    }

    with open(summary_path, "w") as f:
        json.dump(summary_dict, f, indent=2)
    print(f"JSON summary: {summary_path}")

    # CSV export
    if args.export_csv:
        csv_path = run_dir / "sampled_markets.csv"
        analyzer.export_csv(csv_path)

    print("\n=== Analysis Complete ===")
    print(f"Total observed markets: {summary.total_observed_markets}")
    print(f"LLM samples: {summary.llm_total_samples} ({summary.llm_successful_samples} successful)")
    print(f"live_trading_enabled: {summary.live_trading_enabled}")


if __name__ == "__main__":
    main()
