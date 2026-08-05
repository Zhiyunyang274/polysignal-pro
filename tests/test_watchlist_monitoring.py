#!/usr/bin/env python3
"""
Tests for Watchlist-Driven Monitoring (Phase 5F.5).

IMPORTANT: These tests verify that watchlist monitoring is for RESEARCH ONLY.
- Does NOT affect Risk Governor score
- Does NOT add hard_reject reasons
- Does NOT block paper trades
- Does NOT change signal actions
- Avoid candidates are NOT hard forbidden
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_paper import (
    WatchlistLoader,
    WatchlistEntry,
    AlphaCandidate,
    AvoidCandidate,
    MarketTrajectory,
    TrajectoryObservation,
    MarketPrioritizer,
    AvoidAnnotator,
    TrajectoryTracker,
    WatchlistMonitoringStats,
    PaperTradingRunner,
    RunConfig,
    RunStatistics,
)

from polysignal.models.market import Market, MarketStatus


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def temp_watchlist_csv() -> Path:
    """Create temporary watchlist CSV file (actual format)"""
    content = """market_id,matched_by,question,category,appearances,avg_combined_ask,avg_event_score,avg_ambiguity_risk,near_miss_tier_mode,suggested_mode_mode,evidence_level,run_ids
12345,market_id,Will X happen?,crypto,3,0.992,75,10,,research,strong,run_1|run_2
67890,market_id,Will Y happen?,sports,2,0.995,60,15,,research,moderate,run_1
11111,market_id,Will Z happen?,unknown,1,1.001,50,20,,research,weak,run_1
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        return Path(f.name)


@pytest.fixture
def temp_alpha_csv() -> Path:
    """Create temporary alpha candidates CSV file (actual format)"""
    content = """market_id,matched_by,question,category,appearances,avg_combined_ask,avg_event_score,avg_ambiguity_risk,avg_volume,alpha_score,evidence_level,run_ids
12345,market_id,Will X happen?,crypto,3,0.992,75,10,1000,85.0,strong,run_1|run_2
67890,market_id,Will Y happen?,sports,2,0.995,60,15,500,70.0,moderate,run_1
22222,market_id,Will A happen?,crypto,1,0.998,55,20,200,65.0,weak,run_1
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        return Path(f.name)


@pytest.fixture
def temp_avoid_csv() -> Path:
    """Create temporary avoid candidates CSV file (actual format)"""
    content = """market_id,matched_by,question,category,appearances,avg_ambiguity_risk,avg_volume,llm_success_rate,avoid_score,evidence_level,reasons,run_ids
99999,market_id,Will BAD happen?,legal,1,80,0,1.0,75.0,strong,high_ambiguity|forbidden_category,run_1
88888,market_id,Will RISKY happen?,celebrity,1,50,0,1.0,60.0,moderate,subjective_market,run_1
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        return Path(f.name)


@pytest.fixture
def temp_trajectories_json() -> Path:
    """Create temporary trajectories JSON file"""
    content = {
        "12345": {
            "market_id": "12345",
            "normalized_question": "Will X happen?",
            "observations": [
                {
                    "timestamp": "2026-05-09T10:00:00Z",
                    "combined_ask": 0.995,
                    "event_score": 70,
                    "near_miss_tier": "Tier2",
                    "liquidity_score": 85,
                    "suggested_mode": "research",
                    "ambiguity_risk": 20,
                    "source": "watchlist_monitoring",
                }
            ]
        },
        "67890": {
            "market_id": "67890",
            "normalized_question": "Will Y happen?",
            "observations": [
                {
                    "timestamp": "2026-05-09T10:00:00Z",
                    "combined_ask": 0.998,
                    "event_score": 65,
                    "near_miss_tier": "Tier3",
                    "source": "watchlist_monitoring",
                }
            ]
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(content, f)
        return Path(f.name)


@pytest.fixture
def sample_markets() -> list[Market]:
    """Create sample markets for testing"""
    return [
        Market(
            market_id="12345",
            title="Will X happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=100000,
            is_ambiguous=False,
        ),
        Market(
            market_id="67890",
            title="Will Y happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=50000,
            is_ambiguous=False,
        ),
        Market(
            market_id="11111",
            title="Will Z happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=20000,
            is_ambiguous=False,
        ),
        Market(
            market_id="22222",
            title="Will A happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=30000,
            is_ambiguous=False,
        ),
        Market(
            market_id="99999",
            title="Will BAD happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=10000,
            is_ambiguous=True,
        ),
        Market(
            market_id="88888",
            title="Will RISKY happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=15000,
            is_ambiguous=False,
        ),
        Market(
            market_id="33333",
            title="Will NEW happen?",
            status=MarketStatus.OPEN,
            total_volume_usd=25000,
            is_ambiguous=False,
        ),
    ]


# =============================================================================
# WatchlistLoader Tests
# =============================================================================

class TestWatchlistLoader:
    """Tests for WatchlistLoader class"""

    def test_load_persistent_watchlist(self, temp_watchlist_csv: Path):
        """Test loading persistent_watchlist.csv"""
        loader = WatchlistLoader()
        count = loader.load_watchlist(str(temp_watchlist_csv))

        assert count == 3
        assert len(loader.watchlist) == 3

        # Check entries
        assert "12345" in loader.watchlist
        entry = loader.watchlist["12345"]
        assert entry.market_id == "12345"
        assert entry.normalized_question == "Will X happen?"
        assert entry.evidence_level == "strong"
        assert entry.appearance_count == 3
        assert entry.avg_combined_ask == 0.992
        assert entry.category == "crypto"

    def test_load_alpha_candidates(self, temp_alpha_csv: Path):
        """Test loading alpha_candidates.csv"""
        loader = WatchlistLoader()
        count = loader.load_alpha_candidates(str(temp_alpha_csv))

        assert count == 3
        assert len(loader.alpha_candidates) == 3

        # Check entries
        assert "12345" in loader.alpha_candidates
        candidate = loader.alpha_candidates["12345"]
        assert candidate.market_id == "12345"
        assert candidate.alpha_score == 85.0
        # near_miss_tier is not in this format

    def test_load_avoid_candidates(self, temp_avoid_csv: Path):
        """Test loading avoid_candidates.csv"""
        loader = WatchlistLoader()
        count = loader.load_avoid_candidates(str(temp_avoid_csv))

        assert count == 2
        assert len(loader.avoid_candidates) == 2

        # Check entries
        assert "99999" in loader.avoid_candidates
        candidate = loader.avoid_candidates["99999"]
        assert candidate.market_id == "99999"
        assert candidate.avoid_score == 75.0
        # category_risk is inferred from reasons
        assert len(candidate.avoid_reasons) == 2

        # Check entries
        assert "99999" in loader.avoid_candidates
        candidate = candidate = loader.avoid_candidates["99999"]
        assert candidate.market_id == "99999"
        assert candidate.avoid_score == 75.0
        assert candidate.category_risk == "high"
        assert len(candidate.avoid_reasons) == 2

    def test_load_trajectories(self, temp_trajectories_json: Path):
        """Test loading market_trajectories.json"""
        loader = WatchlistLoader()
        count = loader.load_trajectories(str(temp_trajectories_json))

        assert count == 2
        assert len(loader.trajectories) == 2

        # Check trajectory
        assert "12345" in loader.trajectories
        traj = loader.trajectories["12345"]
        assert traj.market_id == "12345"
        assert len(traj.observations) == 1
        assert traj.observations[0].combined_ask == 0.995

    def test_load_missing_file(self):
        """Test loading missing file"""
        loader = WatchlistLoader()
        count = loader.load_watchlist("/nonexistent/path.csv")
        assert count == 0
        assert len(loader.watchlist) == 0


# =============================================================================
# MarketPrioritizer Tests
# =============================================================================

class TestMarketPrioritizer:
    """Tests for MarketPrioritizer class"""

    def test_prioritize_watchlist_first(self, temp_watchlist_csv: Path, sample_markets: list[Market]):
        """Test that watchlist markets are prioritized first"""
        loader = WatchlistLoader()
        loader.load_watchlist(str(temp_watchlist_csv))

        prioritizer = MarketPrioritizer(
            watchlist=loader.watchlist,
            alpha_candidates={},
            watchlist_priority_ratio=0.6,
            discovery_ratio=0.2,
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=5)

        # Check that watchlist markets are first
        watchlist_markets = [m for m in markets if sources.get(m.market_id) == "watchlist"]
        assert len(watchlist_markets) >= 2  # At least 2 watchlist markets

        # Check order - strong evidence should come before moderate
        if len(watchlist_markets) >= 2:
            first_watchlist = watchlist_markets[0]
            # 12345 has strong evidence, should be first
            assert first_watchlist.market_id == "12345"

    def test_prioritize_alpha_candidates(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """Test that alpha candidates are included"""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))

        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.6,
            discovery_ratio=0.2,
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=5)

        # Check that alpha markets are included
        alpha_markets = [m for m in markets if sources.get(m.market_id) == "alpha"]
        assert len(alpha_markets) >= 1

    def test_no_alpha_priority_ratio_preserves_legacy_behavior(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """Without alpha_priority_ratio, existing watchlist/discovery behavior remains available."""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))
        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.6,
            discovery_ratio=0.2,
        )

        _, sources = prioritizer.prioritize(sample_markets, max_markets=5)

        assert prioritizer.alpha_priority_ratio == 0.0
        assert "discovery" in set(sources.values())

    def test_alpha_priority_ratio_prioritizes_alpha_markets(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """Phase 6.5B: alpha priority reserves scan slots for alpha candidates."""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))

        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.0,
            discovery_ratio=0.2,
            alpha_priority_ratio=0.5,
            alpha_repeat_target=3,
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=6)

        alpha_markets = [m for m in markets if sources.get(m.market_id) == "alpha"]
        assert len(alpha_markets) == 3
        assert markets[0].market_id in {"12345", "67890", "22222"}

    def test_alpha_reaching_repeat_target_is_deprioritized(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """Alpha markets at target should lose alpha-priority slots."""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))

        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.0,
            discovery_ratio=0.2,
            alpha_priority_ratio=0.5,
            alpha_repeat_target=3,
        )
        prioritizer.update_alpha_observations({"12345": 3, "67890": 3, "22222": 1})

        _, sources = prioritizer.prioritize(sample_markets, max_markets=6)

        alpha_ids = {mid for mid, source in sources.items() if source == "alpha"}
        assert alpha_ids == {"22222"}

    def test_alpha_priority_keeps_discovery_ratio(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """Discovery floor stays at least 10% even with alpha priority enabled."""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))

        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.0,
            discovery_ratio=0.0,
            alpha_priority_ratio=0.8,
            alpha_repeat_target=3,
        )

        _, sources = prioritizer.prioritize(sample_markets, max_markets=7)

        discovery_markets = [mid for mid, source in sources.items() if source == "discovery"]
        assert len(discovery_markets) >= 1

    def test_alpha_slots_capped_by_remaining_candidates(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """alpha slots = min(int(max_markets * ratio), remaining alphas needing observations)."""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))

        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.0,
            discovery_ratio=0.2,
            alpha_priority_ratio=0.8,
            alpha_repeat_target=3,
        )
        prioritizer.update_alpha_observations({"12345": 3, "67890": 3})

        _, sources = prioritizer.prioritize(sample_markets, max_markets=10)

        assert sum(1 for source in sources.values() if source == "alpha") == 1

    def test_discovery_ratio_minimum(self, sample_markets: list[Market]):
        """Test that discovery ratio is at least 10%"""
        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates={},
            watchlist_priority_ratio=0.6,
            discovery_ratio=0.05,  # Below minimum
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=10)

        # Check that discovery markets are included (at least 10%)
        discovery_markets = [m for m in markets if sources.get(m.market_id) == "discovery"]
        assert len(discovery_markets) >= 1  # At least 1 discovery market

    def test_prioritize_with_all_sources(
        self,
        temp_watchlist_csv: Path,
        temp_alpha_csv: Path,
        sample_markets: list[Market],
    ):
        """Test prioritization with watchlist, alpha, and discovery"""
        loader = WatchlistLoader()
        loader.load_watchlist(str(temp_watchlist_csv))
        loader.load_alpha_candidates(str(temp_alpha_csv))

        prioritizer = MarketPrioritizer(
            watchlist=loader.watchlist,
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.5,
            discovery_ratio=0.2,
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=7)

        # Check all sources present
        source_types = set(sources.values())
        assert "watchlist" in source_types
        assert "discovery" in source_types


# =============================================================================
# AvoidAnnotator Tests
# =============================================================================

class TestAvoidAnnotator:
    """Tests for AvoidAnnotator class"""

    def test_annotate_avoid_candidate(self, temp_avoid_csv: Path):
        """Test annotating avoid candidate"""
        loader = WatchlistLoader()
        loader.load_avoid_candidates(str(temp_avoid_csv))

        annotator = AvoidAnnotator(avoid_candidates=loader.avoid_candidates)

        annotation = annotator.annotate("99999")

        assert annotation is not None
        assert annotation["is_avoid_candidate"] == True
        assert annotation["avoid_score"] == 75.0
        # category_risk is inferred from reasons (high_ambiguity -> high)
        assert annotation["category_risk"] == "high"
        assert annotation["is_hard_forbidden"] == False  # NOT hard forbidden

    def test_annotate_non_avoid_market(self, temp_avoid_csv: Path):
        """Test annotating non-avoid market"""
        loader = WatchlistLoader()
        loader.load_avoid_candidates(str(temp_avoid_csv))

        annotator = AvoidAnnotator(avoid_candidates=loader.avoid_candidates)

        annotation = annotator.annotate("12345")  # Not in avoid list

        assert annotation is None

    def test_avoid_not_hard_forbidden(self, temp_avoid_csv: Path):
        """Test that avoid annotation is NOT hard forbidden"""
        loader = WatchlistLoader()
        loader.load_avoid_candidates(str(temp_avoid_csv))

        annotator = AvoidAnnotator(avoid_candidates=loader.avoid_candidates)

        annotation = annotator.annotate("99999")

        # Critical test: avoid is NOT hard forbidden
        assert annotation["is_hard_forbidden"] == False
        assert annotation["annotation_type"] == "research_only"


# =============================================================================
# TrajectoryTracker Tests
# =============================================================================

class TestTrajectoryTracker:
    """Tests for TrajectoryTracker class"""

    def test_track_observation(self, temp_trajectories_json: Path):
        """Test tracking observation"""
        loader = WatchlistLoader()
        loader.load_trajectories(str(temp_trajectories_json))

        tracker = TrajectoryTracker(trajectories=loader.trajectories, track_enabled=True)

        change = tracker.track(
            market_id="12345",
            combined_ask=0.980,  # Changed from 0.995, delta = 0.015 > 0.01 threshold
            event_score=75,
            near_miss_tier="Tier1",  # Provide current tier to avoid spurious change
            suggested_mode="research",  # Provide current mode to avoid spurious change
        )

        # Should detect combined_ask change (> 1%)
        assert change is not None
        # Check that combined_ask_change is in the changes
        change_types = [c.get("type") for c in change.get("changes", [])]
        assert "combined_ask_change" in change_types

    def test_track_no_change(self, temp_trajectories_json: Path):
        """Test tracking with no significant change"""
        loader = WatchlistLoader()
        loader.load_trajectories(str(temp_trajectories_json))

        tracker = TrajectoryTracker(trajectories=loader.trajectories, track_enabled=True)

        change = tracker.track(
            market_id="12345",
            combined_ask=0.995,  # Same as before
            event_score=75,
            near_miss_tier="Tier2",  # Same as before
            suggested_mode="research",  # Same as before
        )

        # No significant change
        assert change is None

    def test_track_disabled(self, temp_trajectories_json: Path):
        """Test tracking disabled"""
        loader = WatchlistLoader()
        loader.load_trajectories(str(temp_trajectories_json))

        tracker = TrajectoryTracker(trajectories=loader.trajectories, track_enabled=False)

        change = tracker.track(
            market_id="12345",
            combined_ask=0.988,
        )

        assert change is None

    def test_trajectory_update_json(self, temp_trajectories_json: Path):
        """Test trajectory update JSON output"""
        loader = WatchlistLoader()
        loader.load_trajectories(str(temp_trajectories_json))

        tracker = TrajectoryTracker(trajectories=loader.trajectories, track_enabled=True)

        tracker.track(
            market_id="12345",
            combined_ask=0.988,
            event_score=75,
        )

        update_json = tracker.to_trajectory_update_json()

        assert "updated_at" in update_json
        assert "markets_updated" in update_json
        assert "12345" in update_json["markets_updated"]
        assert update_json["new_observations_count"] == 1


# =============================================================================
# Backward Compatibility Tests
# =============================================================================

class TestBackwardCompatibility:
    """Tests for backward compatibility"""

    def test_default_mode_no_watchlist(self):
        """Test that default mode does not require watchlist"""
        config = RunConfig()

        assert config.monitor_mode == "default"
        assert config.watchlist_file is None
        assert config.alpha_candidates_file is None
        assert config.avoid_candidates_file is None

    def test_run_config_defaults(self):
        """Test RunConfig defaults"""
        config = RunConfig()

        # RunConfig doesn't have live_trading_enabled (that's in config/risk.yaml)
        # Check watchlist-related defaults
        assert config.monitor_mode == "default"
        assert config.watchlist_file is None
        assert config.alpha_candidates_file is None
        assert config.avoid_candidates_file is None
        assert config.watchlist_priority_ratio == 0.6
        assert config.discovery_ratio == 0.2
        assert config.track_trajectory == True
        assert config.alpha_priority_ratio == 0.0
        assert config.alpha_repeat_target == 3


# =============================================================================
# Safety Verification Tests
# =============================================================================

class TestSafetyVerification:
    """Tests for safety verification"""

    def test_avoid_annotation_does_not_block(self, temp_avoid_csv: Path):
        """Test that avoid annotation does NOT block trading"""
        loader = WatchlistLoader()
        loader.load_avoid_candidates(str(temp_avoid_csv))

        annotator = AvoidAnnotator(avoid_candidates=loader.avoid_candidates)

        annotation = annotator.annotate("99999")

        # Critical: avoid annotation should NOT block
        assert annotation["is_hard_forbidden"] == False
        assert annotation["annotation_type"] == "research_only"

    def test_avoid_annotation_no_hard_reject(self, temp_avoid_csv: Path):
        """Test that avoid annotation does NOT add hard_reject"""
        loader = WatchlistLoader()
        loader.load_avoid_candidates(str(temp_avoid_csv))

        annotator = AvoidAnnotator(avoid_candidates=loader.avoid_candidates)

        annotation = annotator.annotate("99999")

        # No hard_reject field should be True
        assert annotation.get("is_hard_forbidden") == False

    def test_watchlist_does_not_trigger_trade(self):
        """Test that watchlist does NOT trigger trading"""
        # This is a design test - watchlist should only affect scan order
        prioritizer = MarketPrioritizer(
            watchlist={"12345": WatchlistEntry(
                market_id="12345",
                normalized_question="Test",
                evidence_level="strong",
                appearance_count=3,
                avg_combined_ask=0.99,
                category="crypto",
            )},
            alpha_candidates={},
            watchlist_priority_ratio=0.6,
            discovery_ratio=0.2,
        )

        # Prioritizer only returns markets and sources
        # It does NOT generate signals or trigger trades
        markets, sources = prioritizer.prioritize([], max_markets=5)

        # No markets = no trading
        assert len(markets) == 0

    def test_alpha_score_does_not_trigger_trade(self, temp_alpha_csv: Path, sample_markets: list[Market]):
        """Alpha score only affects scan priority and never creates a trading action."""
        loader = WatchlistLoader()
        loader.load_alpha_candidates(str(temp_alpha_csv))
        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.0,
            discovery_ratio=0.2,
            alpha_priority_ratio=0.5,
            alpha_repeat_target=3,
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=5)

        assert any(sources.get(m.market_id) == "alpha" for m in markets)
        assert set(sources.values()).issubset({"alpha", "discovery", "watchlist"})
        assert all(source != "paper_trade" for source in sources.values())
        assert all(source != "signal" for source in sources.values())

    def test_alpha_score_does_not_affect_risk_governor(self):
        """MarketPrioritizer has no Risk Governor inputs or scoring outputs."""
        prioritizer = MarketPrioritizer(
            watchlist={},
            alpha_candidates={
                "alpha_1": AlphaCandidate(
                    market_id="alpha_1",
                    normalized_question="Alpha",
                    alpha_score=99.0,
                    category="crypto",
                    combined_ask=0.99,
                    event_score=70.0,
                    near_miss_tier="Tier1",
                )
            },
            alpha_priority_ratio=0.5,
        )

        markets, sources = prioritizer.prioritize([], max_markets=5)

        assert markets == []
        assert sources == {}
        assert not hasattr(prioritizer, "risk_governor")
        assert not hasattr(prioritizer, "hard_reject_reasons")

    def test_trajectory_tracker_does_not_trigger_trade(self):
        """Test that trajectory tracker does NOT trigger trading"""
        tracker = TrajectoryTracker(trajectories={}, track_enabled=True)

        # Tracker only records observations
        # It does NOT generate signals or trigger trades
        change = tracker.track(
            market_id="12345",
            combined_ask=0.988,
        )

        # Tracker returns change info, not trading signal
        # Even if change is detected, it's just for logging
        # The return value is a dict, not a Signal
        if change:
            assert isinstance(change, dict)
            assert "type" not in change or change.get("type") != "trade"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for watchlist monitoring"""

    def test_full_watchlist_flow(
        self,
        temp_watchlist_csv: Path,
        temp_alpha_csv: Path,
        temp_avoid_csv: Path,
        temp_trajectories_json: Path,
        sample_markets: list[Market],
    ):
        """Test full watchlist flow"""
        # Load all files
        loader = WatchlistLoader()
        loader.load_watchlist(str(temp_watchlist_csv))
        loader.load_alpha_candidates(str(temp_alpha_csv))
        loader.load_avoid_candidates(str(temp_avoid_csv))
        loader.load_trajectories(str(temp_trajectories_json))

        # Prioritize markets
        prioritizer = MarketPrioritizer(
            watchlist=loader.watchlist,
            alpha_candidates=loader.alpha_candidates,
            watchlist_priority_ratio=0.5,
            discovery_ratio=0.2,
        )

        markets, sources = prioritizer.prioritize(sample_markets, max_markets=5)

        # Annotate avoid candidates
        annotator = AvoidAnnotator(avoid_candidates=loader.avoid_candidates)

        avoid_count = 0
        for market in markets:
            annotation = annotator.annotate(market.market_id)
            if annotation:
                avoid_count += 1
                # Verify annotation is research only
                assert annotation["is_hard_forbidden"] == False

        # Track trajectories
        tracker = TrajectoryTracker(trajectories=loader.trajectories, track_enabled=True)

        for market in markets:
            if sources.get(market.market_id) in ("watchlist", "alpha"):
                tracker.track(
                    market_id=market.market_id,
                    combined_ask=0.99,
                )

        # Get updates
        update_json = tracker.to_trajectory_update_json()

        assert len(update_json["markets_updated"]) > 0

    def test_watchlist_stats(self):
        """Test WatchlistMonitoringStats"""
        stats = WatchlistMonitoringStats()

        stats.watchlist_markets_loaded = 10
        stats.alpha_candidates_loaded = 5
        stats.avoid_candidates_loaded = 3
        stats.watchlist_markets_scanned = 8
        stats.alpha_markets_scanned = 4
        stats.discovery_markets_scanned = 2
        stats.avoid_annotations_count = 2
        stats.trajectory_updates_count = 10
        stats.trajectory_changes_count = 3

        stats_dict = stats.to_dict()

        assert stats_dict["watchlist_stats"]["total_watchlist_markets"] == 10
        assert stats_dict["watchlist_stats"]["alpha_candidates_scanned"] == 4
        assert stats_dict["trajectory_stats"]["changes_count"] == 3

    def test_alpha_repeat_observation_summary_format(self, tmp_path: Path):
        """Phase 6.5B summary has the required research-only fields."""
        runner = PaperTradingRunner.__new__(PaperTradingRunner)
        runner.run_config = RunConfig(alpha_priority_ratio=0.5, alpha_repeat_target=3)
        runner.run_dir = tmp_path
        runner.events_file = None
        runner.db = None
        runner.watchlist_loader = None
        runner.watchlist_stats = WatchlistMonitoringStats()
        runner.watchlist_stats.alpha_candidates_loaded = 4
        runner.watchlist_stats.alpha_markets_scanned = 6
        runner._alpha_ids = {"a1", "a2", "a3", "a4"}
        runner._alpha_observation_counts = {"a1": 1, "a2": 2, "a3": 3, "a4": 5}
        runner.config = SimpleNamespace(
            env=SimpleNamespace(
                live_trading_enabled=False,
                allow_auto_execution=False,
                paper_trading_enabled=True,
            )
        )
        runner.stats = RunStatistics(run_id="test_run", start_time=datetime.utcnow())

        runner._generate_alpha_repeat_reports()

        summary_path = tmp_path / "alpha_repeat_observation_summary.json"
        report_path = tmp_path / "alpha_repeat_observation_report.md"
        assert summary_path.exists()
        assert report_path.exists()

        summary = json.loads(summary_path.read_text())
        assert summary["alpha_candidates_loaded"] == 4
        assert summary["alpha_candidates_scanned"] == 6
        assert summary["alpha_candidates_with_1_observation"] == 1
        assert summary["alpha_candidates_with_2_observations"] == 1
        assert summary["alpha_candidates_with_3_or_more_observations"] == 2
        assert summary["alpha_candidates_with_5_or_more_observations"] == 1
        assert summary["alpha_repeat_target"] == 3
        assert summary["alpha_priority_ratio"] == 0.5
        assert summary["safety_verification"]["live_trading_enabled"] is False
        assert summary["safety_verification"]["allow_auto_execution"] is False
        assert summary["safety_verification"]["paper_trading_enabled"] is True
        assert summary["safety_verification"]["alpha_score_triggers_trade"] is False

    def test_live_trading_config_remains_false(self):
        """Repository default risk config keeps live trading disabled."""
        risk_yaml = Path(__file__).resolve().parent.parent / "config" / "risk.yaml"
        text = risk_yaml.read_text()

        assert "live_trading_enabled: false" in text
        assert "allow_auto_execution: false" in text
        assert "paper_trading_enabled: true" in text


# =============================================================================
# Cleanup
# =============================================================================

@pytest.fixture(autouse=True)
def cleanup_temp_files(
    temp_watchlist_csv: Path,
    temp_alpha_csv: Path,
    temp_avoid_csv: Path,
    temp_trajectories_json: Path,
):
    """Cleanup temporary files after tests"""
    yield
    # Cleanup
    for path in [temp_watchlist_csv, temp_alpha_csv, temp_avoid_csv, temp_trajectories_json]:
        try:
            path.unlink()
        except Exception:
            pass
