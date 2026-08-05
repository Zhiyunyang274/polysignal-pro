"""
Tests for Resolution & Lifecycle Engine
"""

import pytest

from polysignal.models.market import MarketCategory, MarketStatus
from polysignal.models.lifecycle import LifecyclePhase, AmbiguityLevel, ResolutionRiskLevel
from polysignal.engines.resolution_lifecycle import ResolutionLifecycleEngine
from tests.fixtures.lifecycle import (
    create_lifecycle_market,
    create_early_phase_market,
    create_mid_phase_market,
    create_late_phase_market,
    create_closing_phase_market,
    create_closed_market,
    create_resolved_market,
    create_ambiguous_market,
    create_ambiguous_keyword_market,
    create_no_resolution_source_market,
    create_forbidden_category_market,
    create_no_close_time_market,
    create_no_created_at_market,
)


class TestResolutionLifecycleEngine:
    """Test Resolution & Lifecycle Engine"""

    @pytest.fixture
    def engine(self) -> ResolutionLifecycleEngine:
        """Create engine with default settings"""
        return ResolutionLifecycleEngine()

    # =========================================================================
    # Phase Detection Tests
    # =========================================================================

    def test_default_settings(self, engine: ResolutionLifecycleEngine):
        """Test default settings"""
        assert engine.early_threshold == 0.90
        assert engine.late_threshold == 0.20
        assert engine.closing_threshold == 0.05
        assert len(engine.ambiguity_keywords) > 0

    def test_assess_early_phase(self, engine: ResolutionLifecycleEngine):
        """Test EARLY phase detection"""
        market = create_early_phase_market()
        assessment = engine.assess(market)

        assert assessment.phase == LifecyclePhase.EARLY
        assert assessment.time_remaining_pct is not None
        assert assessment.time_remaining_pct >= 0.90
        assert assessment.close_time_risk <= 0.2

    def test_assess_mid_phase(self, engine: ResolutionLifecycleEngine):
        """Test MID phase detection"""
        market = create_mid_phase_market()
        assessment = engine.assess(market)

        assert assessment.phase == LifecyclePhase.MID
        assert assessment.time_remaining_pct is not None
        assert 0.20 < assessment.time_remaining_pct < 0.90
        assert assessment.close_time_risk == 0.0

    def test_assess_late_phase(self, engine: ResolutionLifecycleEngine):
        """Test LATE phase detection"""
        market = create_late_phase_market()
        assessment = engine.assess(market)

        assert assessment.phase == LifecyclePhase.LATE
        assert assessment.time_remaining_pct is not None
        assert 0.05 < assessment.time_remaining_pct <= 0.20
        assert assessment.close_time_risk == 0.5

    def test_assess_closing_phase(self, engine: ResolutionLifecycleEngine):
        """Test CLOSING phase detection"""
        market = create_closing_phase_market()
        assessment = engine.assess(market)

        assert assessment.phase == LifecyclePhase.CLOSING
        assert assessment.time_remaining_pct is not None
        assert assessment.time_remaining_pct <= 0.05
        assert assessment.close_time_risk == 0.9

    def test_assess_closed_market(self, engine: ResolutionLifecycleEngine):
        """Test CLOSED market"""
        market = create_closed_market()
        assessment = engine.assess(market)

        assert assessment.phase == LifecyclePhase.CLOSED
        assert assessment.close_time_risk == 1.0
        assert "market_not_open" in assessment.hard_reject_reasons
        assert assessment.is_tradable is False

    def test_assess_resolved_market(self, engine: ResolutionLifecycleEngine):
        """Test RESOLVED market"""
        market = create_resolved_market()
        assessment = engine.assess(market)

        assert assessment.phase == LifecyclePhase.RESOLVED
        assert "market_not_open" in assessment.hard_reject_reasons
        assert assessment.is_tradable is False

    def test_assess_no_close_time(self, engine: ResolutionLifecycleEngine):
        """Test market without close_time"""
        market = create_no_close_time_market()
        assessment = engine.assess(market)

        # Should be treated as long-term market
        assert assessment.phase == LifecyclePhase.MID
        assert assessment.close_time_risk == 0.0
        assert assessment.time_remaining_pct is None

    def test_assess_no_created_at(self, engine: ResolutionLifecycleEngine):
        """Test market without created_at but with close_time"""
        market = create_no_created_at_market()
        assessment = engine.assess(market)

        # Should still work, using absolute time
        assert assessment.phase in [LifecyclePhase.MID, LifecyclePhase.LATE, LifecyclePhase.CLOSING]
        assert assessment.time_remaining_pct is None

    # =========================================================================
    # Ambiguity Detection Tests
    # =========================================================================

    def test_ambiguity_explicit(self, engine: ResolutionLifecycleEngine):
        """Test explicit ambiguity flag"""
        market = create_ambiguous_market()
        assessment = engine.assess(market)

        assert assessment.ambiguity_level == AmbiguityLevel.CRITICAL
        assert assessment.ambiguity_risk == 1.0
        assert "market_ambiguous" in assessment.hard_reject_reasons
        assert assessment.is_tradable is False

    def test_ambiguity_no_resolution_source(self, engine: ResolutionLifecycleEngine):
        """Test market without resolution source"""
        market = create_no_resolution_source_market()
        assessment = engine.assess(market)

        assert assessment.ambiguity_level == AmbiguityLevel.HIGH
        assert assessment.ambiguity_risk == 0.8
        assert "no_resolution_source" in assessment.risk_flags

    def test_ambiguity_keyword_in_title(self, engine: ResolutionLifecycleEngine):
        """Test ambiguity keywords in title"""
        market = create_lifecycle_market(
            title="Will maybe something happen?",
        )
        assessment = engine.assess(market)

        assert assessment.ambiguity_level == AmbiguityLevel.MEDIUM
        assert assessment.ambiguity_risk == 0.5

    def test_ambiguity_keyword_in_source(self, engine: ResolutionLifecycleEngine):
        """Test ambiguity keywords in resolution source"""
        market = create_lifecycle_market(
            resolution_source="TBD",
        )
        assessment = engine.assess(market)

        assert assessment.ambiguity_level == AmbiguityLevel.MEDIUM
        assert assessment.ambiguity_risk == 0.5

    def test_ambiguity_insufficient_criteria(self, engine: ResolutionLifecycleEngine):
        """Test insufficient resolution criteria"""
        market = create_lifecycle_market(
            resolution_criteria="TBD",  # Too short
        )
        assessment = engine.assess(market)

        assert assessment.ambiguity_level == AmbiguityLevel.LOW
        assert assessment.ambiguity_risk == 0.2

    # =========================================================================
    # Resolution Risk Tests
    # =========================================================================

    def test_resolution_risk_crypto_category(self, engine: ResolutionLifecycleEngine):
        """Test resolution risk for crypto category"""
        market = create_lifecycle_market(category=MarketCategory.CRYPTO)
        assessment = engine.assess(market)

        assert assessment.resolution_risk_level == ResolutionRiskLevel.NONE
        assert assessment.resolution_risk == 0.0

    def test_resolution_risk_sports_category(self, engine: ResolutionLifecycleEngine):
        """Test resolution risk for sports category"""
        market = create_lifecycle_market(category=MarketCategory.SPORTS)
        assessment = engine.assess(market)

        assert assessment.resolution_risk_level == ResolutionRiskLevel.NONE

    def test_resolution_risk_politics_category(self, engine: ResolutionLifecycleEngine):
        """Test resolution risk for politics category"""
        market = create_lifecycle_market(category=MarketCategory.POLITICS)
        assessment = engine.assess(market)

        assert assessment.resolution_risk_level == ResolutionRiskLevel.HIGH
        assert assessment.resolution_risk == 0.7

    def test_resolution_risk_legal_category(self, engine: ResolutionLifecycleEngine):
        """Test resolution risk for legal category"""
        market = create_lifecycle_market(category=MarketCategory.LEGAL)
        assessment = engine.assess(market)

        assert assessment.resolution_risk_level == ResolutionRiskLevel.HIGH

    # =========================================================================
    # Forbidden Category Tests
    # =========================================================================

    def test_forbidden_category_politics(self, engine: ResolutionLifecycleEngine):
        """Test forbidden category - politics"""
        market = create_forbidden_category_market()
        assessment = engine.assess(market)

        assert assessment.is_auto_allowed is False
        assert "forbidden_category" in assessment.risk_flags

    def test_forbidden_category_crypto(self, engine: ResolutionLifecycleEngine):
        """Test allowed category - crypto"""
        market = create_lifecycle_market(category=MarketCategory.CRYPTO)
        assessment = engine.assess(market)

        assert assessment.is_auto_allowed is True
        assert "forbidden_category" not in assessment.risk_flags

    def test_forbidden_category_war(self, engine: ResolutionLifecycleEngine):
        """Test forbidden category - war"""
        market = create_lifecycle_market(category=MarketCategory.WAR_GEOPOLITICS)
        assessment = engine.assess(market)

        assert assessment.is_auto_allowed is False

    def test_forbidden_category_celebrity(self, engine: ResolutionLifecycleEngine):
        """Test forbidden category - celebrity"""
        market = create_lifecycle_market(category=MarketCategory.CELEBRITY)
        assessment = engine.assess(market)

        assert assessment.is_auto_allowed is False

    def test_forbidden_category_subjective(self, engine: ResolutionLifecycleEngine):
        """Test forbidden category - subjective"""
        market = create_lifecycle_market(category=MarketCategory.SUBJECTIVE)
        assessment = engine.assess(market)

        assert assessment.is_auto_allowed is False

    # =========================================================================
    # Lifecycle Score Calculation Tests
    # =========================================================================

    def test_lifecycle_score_mid_phase(self, engine: ResolutionLifecycleEngine):
        """Test lifecycle score for MID phase"""
        market = create_mid_phase_market()
        assessment = engine.assess(market)

        # MID phase base score is 90, no penalties
        assert assessment.lifecycle_score == 90.0

    def test_lifecycle_score_early_phase(self, engine: ResolutionLifecycleEngine):
        """Test lifecycle score for EARLY phase"""
        market = create_early_phase_market()
        assessment = engine.assess(market)

        # EARLY phase base score is 80, but has close_time_risk=0.1
        # Score = 80 - (0.1 * 20) = 78
        assert assessment.lifecycle_score == 78.0

    def test_lifecycle_score_with_ambiguity_penalty(self, engine: ResolutionLifecycleEngine):
        """Test lifecycle score with ambiguity penalty"""
        market = create_lifecycle_market(
            resolution_criteria="TBD",  # LOW ambiguity = 0.2
        )
        assessment = engine.assess(market)

        # Base 90 - (0.2 * 40) = 82
        assert assessment.lifecycle_score == 82.0

    def test_lifecycle_score_with_resolution_penalty(self, engine: ResolutionLifecycleEngine):
        """Test lifecycle score with resolution risk penalty"""
        market = create_lifecycle_market(category=MarketCategory.POLITICS)
        assessment = engine.assess(market)

        # Base 90 - (0.7 * 25) = 72.5
        assert assessment.lifecycle_score == 72.5

    def test_lifecycle_score_closed_market(self, engine: ResolutionLifecycleEngine):
        """Test lifecycle score for closed market"""
        market = create_closed_market()
        assessment = engine.assess(market)

        assert assessment.lifecycle_score == 0.0

    def test_lifecycle_score_resolved_market(self, engine: ResolutionLifecycleEngine):
        """Test lifecycle score for resolved market"""
        market = create_resolved_market()
        assessment = engine.assess(market)

        assert assessment.lifecycle_score == 0.0

    # =========================================================================
    # Tradable Status Tests
    # =========================================================================

    def test_tradable_true_for_open_market(self, engine: ResolutionLifecycleEngine):
        """Test is_tradable is True for open market"""
        market = create_mid_phase_market()
        assessment = engine.assess(market)

        assert assessment.is_tradable is True

    def test_tradable_false_when_closed(self, engine: ResolutionLifecycleEngine):
        """Test is_tradable is False when closed"""
        market = create_closed_market()
        assessment = engine.assess(market)

        assert assessment.is_tradable is False

    def test_tradable_false_when_ambiguous(self, engine: ResolutionLifecycleEngine):
        """Test is_tradable is False when ambiguous"""
        market = create_ambiguous_market()
        assessment = engine.assess(market)

        assert assessment.is_tradable is False

    # =========================================================================
    # Risk Flags Tests
    # =========================================================================

    def test_risk_flags_propagated(self, engine: ResolutionLifecycleEngine):
        """Test risk flags are properly set"""
        market = create_forbidden_category_market()
        assessment = engine.assess(market)

        assert len(assessment.risk_flags) > 0
        assert any("forbidden_category" in flag for flag in assessment.risk_flags)

    def test_hard_reject_reasons_for_closed(self, engine: ResolutionLifecycleEngine):
        """Test hard reject reasons for closed market"""
        market = create_closed_market()
        assessment = engine.assess(market)

        assert "market_not_open" in assessment.hard_reject_reasons

    def test_hard_reject_reasons_for_ambiguous(self, engine: ResolutionLifecycleEngine):
        """Test hard reject reasons for ambiguous market"""
        market = create_ambiguous_market()
        assessment = engine.assess(market)

        assert "market_ambiguous" in assessment.hard_reject_reasons

    # =========================================================================
    # Custom Keywords Tests
    # =========================================================================

    def test_custom_ambiguity_keywords(self):
        """Test custom ambiguity keywords"""
        custom_keywords = ["custom_keyword", "another_keyword"]
        engine = ResolutionLifecycleEngine(ambiguity_keywords=custom_keywords)

        market = create_lifecycle_market(
            title="Will custom_keyword trigger detection?",
        )
        assessment = engine.assess(market)

        assert assessment.ambiguity_level == AmbiguityLevel.MEDIUM

    def test_default_keywords_present(self, engine: ResolutionLifecycleEngine):
        """Test default keywords are present"""
        default_keywords = ["might", "maybe", "possibly", "subjective", "opinion"]

        for keyword in default_keywords:
            assert keyword in engine.ambiguity_keywords

    # =========================================================================
    # Summary Tests
    # =========================================================================

    def test_get_summary(self, engine: ResolutionLifecycleEngine):
        """Test assessment summary"""
        market = create_mid_phase_market()
        assessment = engine.assess(market)

        summary = assessment.get_summary()

        # Summary contains phase value (lowercase)
        assert "mid" in summary.lower()
        assert "score=90.0" in summary
        assert "tradable=True" in summary
