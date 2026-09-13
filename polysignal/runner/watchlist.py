"""
Watchlist-driven monitoring domain (Phase 5F.5).

Verbatim extraction from scripts/run_paper.py (Iteration 007) — classes are
unchanged; scripts/run_paper.py re-exports them for compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from polysignal.models.market import Market
from polysignal.utils.time import utc_now

# =============================================================================
# Phase 5F.5 — Watchlist-Driven Monitoring
# =============================================================================

@dataclass
class WatchlistEntry:
    """Entry from persistent_watchlist.csv"""
    market_id: str
    normalized_question: str
    evidence_level: str  # strong, moderate, weak
    appearance_count: int
    avg_combined_ask: float | None
    category: str | None


@dataclass
class AlphaCandidate:
    """Entry from alpha_candidates.csv"""
    market_id: str
    normalized_question: str
    alpha_score: float
    category: str | None
    combined_ask: float | None
    event_score: float | None
    near_miss_tier: str | None


@dataclass
class AvoidCandidate:
    """Entry from avoid_candidates.csv"""
    market_id: str
    normalized_question: str
    avoid_score: float
    category: str | None
    category_risk: str | None
    avoid_reasons: list[str] = field(default_factory=list)


@dataclass
class TrajectoryObservation:
    """Single observation in market trajectory"""
    timestamp: str
    combined_ask: float | None = None
    event_score: float | None = None
    near_miss_tier: str | None = None
    liquidity_score: float | None = None
    suggested_mode: str | None = None
    ambiguity_risk: float | None = None
    source: str = "watchlist_monitoring"


@dataclass
class MarketTrajectory:
    """Market trajectory from market_trajectories.json"""
    market_id: str
    normalized_question: str
    observations: list[TrajectoryObservation] = field(default_factory=list)


class WatchlistLoader:
    """
    Load watchlist files for Phase 5F.5.

    IMPORTANT: This is for RESEARCH/MONITORING only.
    - Does NOT affect trading decisions
    - Does NOT modify Risk Governor
    - Does NOT trigger trades
    """

    def __init__(self, logger: Any | None = None):
        self.logger = logger
        self._watchlist: dict[str, WatchlistEntry] = {}
        self._alpha_candidates: dict[str, AlphaCandidate] = {}
        self._avoid_candidates: dict[str, AvoidCandidate] = {}
        self._trajectories: dict[str, MarketTrajectory] = {}

    def load_watchlist(self, filepath: str) -> int:
        """Load persistent_watchlist.csv"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Watchlist file not found: {filepath}")
            return 0

        count = 0
        with open(filepath) as f:
            # Skip header
            header = f.readline().strip().split(",")
            header_map = {h.strip(): i for i, h in enumerate(header)}

            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue

                try:
                    market_id = parts[0].strip()

                    # Get question
                    if "question" in header_map:
                        question = parts[header_map["question"]].strip() if len(parts) > header_map["question"] else ""
                    else:
                        question = ""

                    # Get evidence_level
                    if "evidence_level" in header_map:
                        evidence_level = parts[header_map["evidence_level"]].strip() if len(parts) > header_map["evidence_level"] else "weak"
                    else:
                        evidence_level = "weak"

                    # Get appearances
                    if "appearances" in header_map:
                        appearance_count = int(parts[header_map["appearances"]]) if parts[header_map["appearances"]].strip().isdigit() else 1
                    else:
                        appearance_count = 1

                    # Get avg_combined_ask
                    if "avg_combined_ask" in header_map:
                        avg_combined_ask = float(parts[header_map["avg_combined_ask"]]) if parts[header_map["avg_combined_ask"]].strip() else None
                    else:
                        avg_combined_ask = None

                    # Get category
                    if "category" in header_map:
                        category = parts[header_map["category"]].strip() if len(parts) > header_map["category"] else None
                    else:
                        category = None

                    entry = WatchlistEntry(
                        market_id=market_id,
                        normalized_question=question,
                        evidence_level=evidence_level,
                        appearance_count=appearance_count,
                        avg_combined_ask=avg_combined_ask,
                        category=category,
                    )
                    self._watchlist[entry.market_id] = entry
                    count += 1
                except (ValueError, IndexError):
                    if self.logger:
                        self.logger(f"Skipping invalid watchlist line: {line[:50]}...")
                    continue

        if self.logger:
            self.logger(f"Loaded {count} watchlist entries from {filepath}")
        return count

    def load_alpha_candidates(self, filepath: str) -> int:
        """Load alpha_candidates.csv"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Alpha candidates file not found: {filepath}")
            return 0

        count = 0
        with open(filepath) as f:
            header = f.readline().strip().split(",")
            header_map = {h.strip(): i for i, h in enumerate(header)}

            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue

                # Handle different CSV formats
                # Format 1: market_id,normalized_question,alpha_score,category,combined_ask,event_score,near_miss_tier
                # Format 2: market_id,matched_by,question,category,appearances,avg_combined_ask,avg_event_score,avg_ambiguity_risk,avg_volume,alpha_score,evidence_level,run_ids
                try:
                    market_id = parts[0].strip()

                    # Try to get alpha_score from different positions
                    if "alpha_score" in header_map:
                        alpha_score = float(parts[header_map["alpha_score"]]) if parts[header_map["alpha_score"]].strip() else 0.0
                    elif len(parts) > 2 and parts[2].strip().replace(".", "").replace("-", "").isdigit():
                        alpha_score = float(parts[2])
                    else:
                        alpha_score = 0.0

                    # Get question
                    if "question" in header_map:
                        question = parts[header_map["question"]].strip() if len(parts) > header_map["question"] else ""
                    else:
                        question = parts[1].strip() if len(parts) > 1 else ""

                    # Get category
                    if "category" in header_map:
                        category = parts[header_map["category"]].strip() if len(parts) > header_map["category"] else None
                    else:
                        category = parts[3].strip() if len(parts) > 3 else None

                    # Get combined_ask
                    if "avg_combined_ask" in header_map:
                        combined_ask = float(parts[header_map["avg_combined_ask"]]) if parts[header_map["avg_combined_ask"]].strip() else None
                    elif len(parts) > 4 and parts[4].strip():
                        combined_ask = float(parts[4]) if parts[4].strip().replace(".", "").isdigit() else None
                    else:
                        combined_ask = None

                    # Get event_score
                    if "avg_event_score" in header_map:
                        event_score = float(parts[header_map["avg_event_score"]]) if parts[header_map["avg_event_score"]].strip() else None
                    elif len(parts) > 5 and parts[5].strip():
                        event_score = float(parts[5]) if parts[5].strip().replace(".", "").isdigit() else None
                    else:
                        event_score = None

                    entry = AlphaCandidate(
                        market_id=market_id,
                        normalized_question=question,
                        alpha_score=alpha_score,
                        category=category,
                        combined_ask=combined_ask,
                        event_score=event_score,
                        near_miss_tier=None,  # Not in this format
                    )
                    self._alpha_candidates[entry.market_id] = entry
                    count += 1
                except (ValueError, IndexError):
                    if self.logger:
                        self.logger(f"Skipping invalid alpha candidate line: {line[:50]}...")
                    continue

        if self.logger:
            self.logger(f"Loaded {count} alpha candidates from {filepath}")
        return count

    def load_avoid_candidates(self, filepath: str) -> int:
        """Load avoid_candidates.csv"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Avoid candidates file not found: {filepath}")
            return 0

        count = 0
        with open(filepath) as f:
            header = f.readline().strip().split(",")
            header_map = {h.strip(): i for i, h in enumerate(header)}

            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue

                try:
                    market_id = parts[0].strip()

                    # Get question
                    if "question" in header_map:
                        question = parts[header_map["question"]].strip() if len(parts) > header_map["question"] else ""
                    else:
                        question = ""

                    # Get avoid_score
                    if "avoid_score" in header_map:
                        avoid_score = float(parts[header_map["avoid_score"]]) if parts[header_map["avoid_score"]].strip() else 0.0
                    else:
                        avoid_score = 0.0

                    # Get category
                    if "category" in header_map:
                        category = parts[header_map["category"]].strip() if len(parts) > header_map["category"] else None
                    else:
                        category = None

                    # Get reasons
                    avoid_reasons = []
                    if "reasons" in header_map:
                        reasons_str = parts[header_map["reasons"]].strip().strip('"').strip("'") if len(parts) > header_map["reasons"] else ""
                        avoid_reasons = [r.strip() for r in reasons_str.split("|") if r.strip()]

                    # Determine category_risk from reasons
                    category_risk = "medium"
                    if "high_ambiguity" in avoid_reasons or "forbidden_category" in avoid_reasons:
                        category_risk = "high"

                    entry = AvoidCandidate(
                        market_id=market_id,
                        normalized_question=question,
                        avoid_score=avoid_score,
                        category=category,
                        category_risk=category_risk,
                        avoid_reasons=avoid_reasons,
                    )
                    self._avoid_candidates[entry.market_id] = entry
                    count += 1
                except (ValueError, IndexError):
                    if self.logger:
                        self.logger(f"Skipping invalid avoid candidate line: {line[:50]}...")
                    continue

        if self.logger:
            self.logger(f"Loaded {count} avoid candidates from {filepath}")
        return count

    def load_trajectories(self, filepath: str) -> int:
        """Load market_trajectories.json"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Trajectories file not found: {filepath}")
            return 0

        try:
            with open(filepath) as f:
                data = json.load(f)

            count = 0
            for market_id, traj_data in data.items():
                observations = []
                for obs_data in traj_data.get("observations", []):
                    obs = TrajectoryObservation(
                        timestamp=obs_data.get("timestamp", ""),
                        combined_ask=obs_data.get("combined_ask"),
                        event_score=obs_data.get("event_score"),
                        near_miss_tier=obs_data.get("near_miss_tier"),
                        liquidity_score=obs_data.get("liquidity_score"),
                        suggested_mode=obs_data.get("suggested_mode"),
                        ambiguity_risk=obs_data.get("ambiguity_risk"),
                        source=obs_data.get("source", "watchlist_monitoring"),
                    )
                    observations.append(obs)

                trajectory = MarketTrajectory(
                    market_id=market_id,
                    normalized_question=traj_data.get("normalized_question", ""),
                    observations=observations,
                )
                self._trajectories[market_id] = trajectory
                count += 1

            if self.logger:
                self.logger(f"Loaded {count} trajectories from {filepath}")
            return count

        except Exception as e:
            if self.logger:
                self.logger(f"Error loading trajectories: {e}")
            return 0

    @property
    def watchlist(self) -> dict[str, WatchlistEntry]:
        return self._watchlist

    @property
    def alpha_candidates(self) -> dict[str, AlphaCandidate]:
        return self._alpha_candidates

    @property
    def avoid_candidates(self) -> dict[str, AvoidCandidate]:
        return self._avoid_candidates

    @property
    def trajectories(self) -> dict[str, MarketTrajectory]:
        return self._trajectories


class MarketPrioritizer:
    """
    Prioritize markets for scanning based on watchlist.

    IMPORTANT: This affects scan order ONLY.
    - Does NOT affect trading decisions
    - Does NOT modify Risk Governor
    - Does NOT trigger trades
    """

    MIN_DISCOVERY_RATIO = 0.1  # Minimum 10% new market discovery

    def __init__(
        self,
        watchlist: dict[str, WatchlistEntry],
        alpha_candidates: dict[str, AlphaCandidate],
        watchlist_priority_ratio: float = 0.6,
        discovery_ratio: float = 0.2,
        alpha_priority_ratio: float = 0.0,
        alpha_repeat_target: int = 3,
    ):
        self.watchlist = watchlist
        self.alpha_candidates = alpha_candidates
        self.watchlist_priority_ratio = watchlist_priority_ratio
        self.discovery_ratio = max(discovery_ratio, self.MIN_DISCOVERY_RATIO)
        self.alpha_priority_ratio = max(0.0, min(alpha_priority_ratio, 0.8))
        self.alpha_repeat_target = alpha_repeat_target
        self._alpha_observation_counts: dict[str, int] = {}

    def update_alpha_observations(self, observation_counts: dict[str, int]) -> None:
        """Update alpha observation counts for deprioritization logic."""
        self._alpha_observation_counts = dict(observation_counts)

    def prioritize(
        self,
        all_markets: list[Market],
        max_markets: int,
    ) -> tuple[list[Market], dict[str, str]]:
        """
        Prioritize markets for scanning.

        Returns:
            Tuple of (prioritized_markets, market_sources)
            where market_sources[market_id] = "watchlist" | "alpha" | "discovery"
        """
        market_sources: dict[str, str] = {}

        # Calculate target counts with alpha priority.
        # IMPORTANT: priority ratios only affect scan order. They do not create
        # signals, alter Risk Governor inputs, or trigger PaperTrader.
        if self.alpha_priority_ratio > 0:
            alpha_slot_target = int(max_markets * self.alpha_priority_ratio)
            alphas_needing_obs = self._count_alphas_needing_observations(all_markets)
            alpha_count = min(alpha_slot_target, alphas_needing_obs)
            alpha_count = max(0, alpha_count)

            watchlist_count = int(max_markets * self.watchlist_priority_ratio)
            min_discovery_count = max(1, int(max_markets * self.MIN_DISCOVERY_RATIO))
            remaining_after_alpha = max_markets - alpha_count
            discovery_count = min(min_discovery_count, remaining_after_alpha)
            watchlist_count = max(0, max_markets - alpha_count - discovery_count)
            watchlist_count = min(watchlist_count, int(max_markets * self.watchlist_priority_ratio))

            # Any extra capacity after capped watchlist slots goes to discovery.
            discovery_count = max_markets - alpha_count - watchlist_count
        else:
            # Original behavior: no alpha priority
            watchlist_count = int(max_markets * self.watchlist_priority_ratio)
            alpha_count = int(max_markets * (1 - self.watchlist_priority_ratio - self.discovery_ratio))
            discovery_count = max_markets - watchlist_count - alpha_count

            # Ensure minimum discovery
            if discovery_count < int(max_markets * self.MIN_DISCOVERY_RATIO):
                discovery_count = int(max_markets * self.MIN_DISCOVERY_RATIO)
                remaining = max_markets - discovery_count
                watchlist_count = int(remaining * 0.7)
                alpha_count = remaining - watchlist_count

        prioritized: list[Market] = []

        # 1. Add watchlist markets (by evidence level)
        watchlist_markets = []
        for market in all_markets:
            if market.market_id in self.watchlist:
                entry = self.watchlist[market.market_id]
                priority = self._evidence_priority(entry.evidence_level)
                watchlist_markets.append((market, priority))

        # Sort by priority (higher first)
        watchlist_markets.sort(key=lambda x: x[1], reverse=True)
        for market, _ in watchlist_markets[:watchlist_count]:
            prioritized.append(market)
            market_sources[market.market_id] = "watchlist"

        # 2. Add alpha candidates (not already in watchlist)
        # When alpha_priority_ratio > 0, prioritize alphas that still need observations
        alpha_markets = []
        for market in all_markets:
            if market.market_id not in market_sources and market.market_id in self.alpha_candidates:
                candidate = self.alpha_candidates[market.market_id]
                obs_count = self._alpha_observation_counts.get(market.market_id, 0)

                # Skip alphas that have reached the repeat target (deprioritize)
                if self.alpha_priority_ratio > 0 and obs_count >= self.alpha_repeat_target:
                    continue

                priority = self._tier_priority(candidate.near_miss_tier)
                # Boost priority for alphas with fewer observations (need more data)
                if self.alpha_priority_ratio > 0 and obs_count < self.alpha_repeat_target:
                    priority += (self.alpha_repeat_target - obs_count) * 10
                alpha_markets.append((market, priority))

        alpha_markets.sort(key=lambda x: x[1], reverse=True)
        for market, _ in alpha_markets[:alpha_count]:
            prioritized.append(market)
            market_sources[market.market_id] = "alpha"

        # 3. Add discovery markets (not already prioritized)
        discovery_markets = [m for m in all_markets if m.market_id not in market_sources]
        # Shuffle for diversity
        import random
        random.shuffle(discovery_markets)

        for market in discovery_markets[:discovery_count]:
            prioritized.append(market)
            market_sources[market.market_id] = "discovery"

        # 4. Fill remaining with any markets
        remaining_count = max_markets - len(prioritized)
        if remaining_count > 0:
            remaining_markets = [m for m in all_markets if m.market_id not in market_sources]
            for market in remaining_markets[:remaining_count]:
                prioritized.append(market)
                market_sources[market.market_id] = "discovery"

        return prioritized, market_sources

    def _count_alphas_needing_observations(self, markets: list[Market] | None = None) -> int:
        """Count alpha candidates that haven't reached the repeat target."""
        available_ids = {m.market_id for m in markets} if markets is not None else None
        count = 0
        for market_id in self.alpha_candidates:
            if available_ids is not None and market_id not in available_ids:
                continue
            obs_count = self._alpha_observation_counts.get(market_id, 0)
            if obs_count < self.alpha_repeat_target:
                count += 1
        return count

    def _evidence_priority(self, evidence_level: str) -> int:
        """Convert evidence level to priority score"""
        priorities = {"strong": 100, "moderate": 70, "weak": 40}
        return priorities.get(evidence_level.lower(), 30)

    def _tier_priority(self, tier: str | None) -> int:
        """Convert near_miss_tier to priority score"""
        if not tier:
            return 20
        priorities = {"Tier1": 90, "Tier2": 70, "Tier3": 50, "Tier4": 30}
        return priorities.get(tier, 20)


class AvoidAnnotator:
    """
    Annotate markets with avoid information.

    IMPORTANT: This is for RESEARCH ANNOTATION ONLY.
    - Does NOT affect Risk Governor score
    - Does NOT add hard_reject reasons
    - Does NOT block paper trades
    - Does NOT change signal action
    - Avoid candidates are NOT hard forbidden
    """

    def __init__(self, avoid_candidates: dict[str, AvoidCandidate]):
        self.avoid_candidates = avoid_candidates

    def annotate(self, market_id: str) -> dict[str, Any] | None:
        """
        Get avoid annotation for a market.

        Returns:
            Annotation dict if market is in avoid list, None otherwise.
            The annotation is for logging/reporting only.
        """
        if market_id not in self.avoid_candidates:
            return None

        candidate = self.avoid_candidates[market_id]
        return {
            "is_avoid_candidate": True,
            "avoid_score": candidate.avoid_score,
            "category_risk": candidate.category_risk,
            "avoid_reasons": candidate.avoid_reasons,
            # Explicitly state this is NOT a block
            "is_hard_forbidden": False,  # Always False - avoid is NOT hard forbidden
            "annotation_type": "research_only",
        }


class TrajectoryTracker:
    """
    Track market trajectory changes during monitoring.

    IMPORTANT: This is for RESEARCH/TRACKING only.
    - Does NOT affect trading decisions
    - Output is written to current run directory only
    """

    def __init__(
        self,
        trajectories: dict[str, MarketTrajectory],
        track_enabled: bool = True,
    ):
        self.trajectories = trajectories
        self.track_enabled = track_enabled
        self._updates: dict[str, TrajectoryObservation] = {}
        self._changes: list[dict[str, Any]] = []

    def track(
        self,
        market_id: str,
        combined_ask: float | None = None,
        event_score: float | None = None,
        near_miss_tier: str | None = None,
        liquidity_score: float | None = None,
        suggested_mode: str | None = None,
        ambiguity_risk: float | None = None,
    ) -> dict[str, Any] | None:
        """
        Track observation for a market.

        Returns:
            Change dict if significant change detected, None otherwise.
        """
        if not self.track_enabled:
            return None

        now = utc_now().isoformat()

        # Create observation
        observation = TrajectoryObservation(
            timestamp=now,
            combined_ask=combined_ask,
            event_score=event_score,
            near_miss_tier=near_miss_tier,
            liquidity_score=liquidity_score,
            suggested_mode=suggested_mode,
            ambiguity_risk=ambiguity_risk,
            source="watchlist_monitoring",
        )

        # Store update
        self._updates[market_id] = observation

        # Detect changes
        change = self._detect_change(market_id, observation)
        if change:
            self._changes.append(change)

        return change

    def _detect_change(
        self,
        market_id: str,
        current: TrajectoryObservation,
    ) -> dict[str, Any] | None:
        """Detect significant changes from previous observation"""
        if market_id not in self.trajectories:
            return None

        trajectory = self.trajectories[market_id]
        if not trajectory.observations:
            return None

        prev = trajectory.observations[-1]
        changes = []

        # combined_ask change (> 1%)
        if prev.combined_ask is not None and current.combined_ask is not None:
            delta = current.combined_ask - prev.combined_ask
            if abs(delta) > 0.01:
                changes.append({
                    "type": "combined_ask_change",
                    "from": prev.combined_ask,
                    "to": current.combined_ask,
                    "delta": round(delta, 4),
                })

        # near_miss_tier change
        if prev.near_miss_tier != current.near_miss_tier:
            changes.append({
                "type": "tier_change",
                "from": prev.near_miss_tier,
                "to": current.near_miss_tier,
            })

        # suggested_mode change
        if prev.suggested_mode != current.suggested_mode:
            changes.append({
                "type": "mode_change",
                "from": prev.suggested_mode,
                "to": current.suggested_mode,
            })

        if not changes:
            return None

        return {
            "market_id": market_id,
            "timestamp": current.timestamp,
            "changes": changes,
        }

    def get_updates(self) -> dict[str, TrajectoryObservation]:
        """Get all trajectory updates"""
        return self._updates

    def get_changes(self) -> list[dict[str, Any]]:
        """Get all detected changes"""
        return self._changes

    def to_trajectory_update_json(self) -> dict[str, Any]:
        """Convert updates to JSON-serializable dict for output"""
        trajectories_out = {}
        for market_id, obs in self._updates.items():
            trajectories_out[market_id] = {
                "market_id": market_id,
                "observation": {
                    "timestamp": obs.timestamp,
                    "combined_ask": obs.combined_ask,
                    "event_score": obs.event_score,
                    "near_miss_tier": obs.near_miss_tier,
                    "liquidity_score": obs.liquidity_score,
                    "suggested_mode": obs.suggested_mode,
                    "ambiguity_risk": obs.ambiguity_risk,
                    "source": obs.source,
                },
            }

        return {
            "updated_at": utc_now().isoformat(),
            "markets_updated": list(self._updates.keys()),
            "new_observations_count": len(self._updates),
            "changes_detected": len(self._changes),
            "changes": self._changes,
            "trajectories": trajectories_out,
        }


class WatchlistMonitoringStats:
    """Statistics for watchlist-driven monitoring"""

    def __init__(self):
        self.watchlist_markets_loaded: int = 0
        self.alpha_candidates_loaded: int = 0
        self.avoid_candidates_loaded: int = 0
        self.trajectories_loaded: int = 0

        self.watchlist_markets_scanned: int = 0
        self.alpha_markets_scanned: int = 0
        self.discovery_markets_scanned: int = 0

        self.avoid_annotations_count: int = 0
        self.trajectory_updates_count: int = 0
        self.trajectory_changes_count: int = 0

        self.market_sources: dict[str, str] = {}  # market_id -> source
        self.avoid_annotations: list[dict[str, Any]] = []
        self.trajectory_changes: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output"""
        return {
            "watchlist_stats": {
                "total_watchlist_markets": self.watchlist_markets_loaded,
                "watchlist_markets_scanned": self.watchlist_markets_scanned,
                "alpha_candidates_scanned": self.alpha_markets_scanned,
                "avoid_candidates_annotated": self.avoid_annotations_count,
                "discovery_markets_scanned": self.discovery_markets_scanned,
            },
            "trajectory_stats": {
                "trajectories_loaded": self.trajectories_loaded,
                "updates_count": self.trajectory_updates_count,
                "changes_count": self.trajectory_changes_count,
            },
            "top_changes": self.trajectory_changes[:10],
            "avoid_annotations": self.avoid_annotations[:10],
        }

