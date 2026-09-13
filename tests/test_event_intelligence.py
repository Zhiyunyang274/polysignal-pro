"""
Tests for Event Intelligence Engine
"""

import pytest

from polysignal.engines.event_intelligence import EventIntelligenceEngine
from polysignal.llm.mock_provider import MockScenario
from polysignal.models.event import (
    SuggestedMode,
    create_default_assessment,
)
from tests.fixtures.events import (
    create_event_market,
)


class TestEventIntelligenceEngine:
    """Test Event Intelligence Engine"""

    @pytest.fixture
    def engine(self) -> EventIntelligenceEngine:
        """Create engine with default settings"""
        return EventIntelligenceEngine(scenario=MockScenario.SUCCESS)

    # =========================================================================
    # Basic Tests
    # =========================================================================

    def test_default_settings(self, engine: EventIntelligenceEngine):
        """Test default settings"""
        assert engine.llm_provider is not None
        assert engine.MIN_CONFIDENCE == 0.5

    def test_get_status(self, engine: EventIntelligenceEngine):
        """Test get_status returns correct info"""
        status = engine.get_status()

        assert status["engine"] == "EventIntelligenceEngine"
        assert status["llm_provider"] == "mock"
        assert status["min_confidence"] == 0.5

    # =========================================================================
    # Assessment Tests
    # =========================================================================

    def test_assess_success(self, engine: EventIntelligenceEngine):
        """Test successful assessment"""
        market = create_event_market()
        assessment = engine.assess(market)

        assert assessment.market_id == market.market_id
        assert 0 <= assessment.event_score <= 100
        assert 0 <= assessment.evidence_strength <= 100
        assert 0 <= assessment.market_relevance <= 100
        assert 0 <= assessment.ambiguity_risk <= 100
        assert assessment.llm_success is True

    def test_assess_with_event_context(self, engine: EventIntelligenceEngine):
        """Test assessment with additional context"""
        market = create_event_market()
        context = "Bitcoin recently reached $95,000"
        assessment = engine.assess(market, event_context=context)

        assert assessment.market_id == market.market_id
        assert assessment.llm_success is True

    # =========================================================================
    # LLM Failure Tests
    # =========================================================================

    def test_assess_invalid_json(self):
        """Test assessment with invalid JSON from LLM"""
        engine = EventIntelligenceEngine(scenario=MockScenario.INVALID_JSON)
        market = create_event_market()
        assessment = engine.assess(market)

        # Should return default assessment
        assert assessment.event_score == 50.0
        assert assessment.confidence == 0.0
        assert "llm_invalid_json" in assessment.risk_flags
        assert assessment.llm_success is False
        assert assessment.suggested_mode == SuggestedMode.RESEARCH

    def test_assess_schema_error(self):
        """Test assessment with schema validation error"""
        engine = EventIntelligenceEngine(scenario=MockScenario.SCHEMA_ERROR)
        market = create_event_market()
        assessment = engine.assess(market)

        # Should return default assessment
        assert assessment.event_score == 50.0
        assert assessment.confidence == 0.0
        assert "llm_schema_validation_failed" in assessment.risk_flags
        assert assessment.llm_success is False

    def test_assess_missing_fields(self):
        """Test assessment with missing fields"""
        engine = EventIntelligenceEngine(scenario=MockScenario.MISSING_FIELDS)
        market = create_event_market()
        assessment = engine.assess(market)

        # Should return default assessment
        assert assessment.event_score == 50.0
        assert assessment.confidence == 0.0
        assert "llm_schema_validation_failed" in assessment.risk_flags
        assert assessment.llm_success is False

    def test_assess_low_confidence(self):
        """Test assessment with low confidence"""
        engine = EventIntelligenceEngine(scenario=MockScenario.LOW_CONFIDENCE)
        market = create_event_market()
        assessment = engine.assess(market)

        # Should return default assessment (confidence < 0.5)
        assert assessment.event_score == 50.0
        assert assessment.confidence == 0.0
        assert "llm_low_confidence" in assessment.risk_flags
        assert assessment.llm_success is False

    def test_assess_timeout(self):
        """Test assessment with timeout"""
        engine = EventIntelligenceEngine(scenario=MockScenario.TIMEOUT)
        market = create_event_market()
        assessment = engine.assess(market)

        # Should return default assessment
        assert assessment.event_score == 50.0
        assert assessment.confidence == 0.0
        assert "llm_timeout" in assessment.risk_flags
        assert assessment.llm_success is False

    # =========================================================================
    # Default Assessment Tests
    # =========================================================================

    def test_default_assessment_neutral_score(self):
        """Test default assessment has neutral score"""
        assessment = create_default_assessment(
            market_id="test_001",
            error_flag="llm_error",
        )

        assert assessment.event_score == 50.0
        assert assessment.evidence_strength == 50.0
        assert assessment.market_relevance == 50.0
        assert assessment.ambiguity_risk == 50.0
        assert assessment.confidence == 0.0
        assert assessment.suggested_mode == SuggestedMode.RESEARCH

    def test_default_assessment_does_not_trigger_execution(self):
        """Test default assessment cannot trigger execution"""
        assessment = create_default_assessment(
            market_id="test_001",
            error_flag="llm_error",
        )

        # Default assessment should not suggest trading actions
        assert assessment.suggested_mode in [
            SuggestedMode.RESEARCH,
            SuggestedMode.AVOID,
        ]
        assert assessment.confidence == 0.0

    # =========================================================================
    # Score Calculation Tests
    # =========================================================================

    def test_event_score_calculation(self):
        """Test event_score calculation formula"""
        score = EventIntelligenceEngine.calculate_event_score(
            evidence_strength=80.0,
            market_relevance=70.0,
            ambiguity_risk=20.0,
            confidence=0.8,
        )

        # Formula: 0.40 * 80 + 0.30 * 70 + 0.20 * (100-20) + 0.10 * 0.8 * 100
        # = 32 + 21 + 16 + 8 = 77
        assert abs(score - 77.0) < 0.1

    def test_evidence_strength_calculation(self):
        """Test evidence_strength calculation"""
        score = EventIntelligenceEngine.calculate_evidence_strength(
            source_reliability=80.0,
            evidence_concreteness=70.0,
            verification_status=90.0,
            timeliness=60.0,
        )

        # Formula: 0.30 * 80 + 0.30 * 70 + 0.20 * 90 + 0.20 * 60
        # = 24 + 21 + 18 + 12 = 75
        assert abs(score - 75.0) < 0.1

    def test_market_relevance_calculation(self):
        """Test market_relevance calculation"""
        score = EventIntelligenceEngine.calculate_market_relevance(
            direct_causation=80.0,
            rule_alignment=70.0,
            category_match=90.0,
        )

        # Formula: 0.40 * 80 + 0.30 * 70 + 0.30 * 90
        # = 32 + 21 + 27 = 80
        assert abs(score - 80.0) < 0.1

    def test_ambiguity_risk_calculation(self):
        """Test ambiguity_risk calculation"""
        score = EventIntelligenceEngine.calculate_ambiguity_risk(
            rule_clarity=80.0,  # 100 - 80 = 20
            resolution_source_clarity=70.0,  # 100 - 70 = 30
            edge_case_risk=40.0,
            historical_controversy=30.0,
        )

        # Formula: 0.35 * 20 + 0.25 * 30 + 0.20 * 40 + 0.20 * 30
        # = 7 + 7.5 + 8 + 6 = 28.5
        assert abs(score - 28.5) < 0.1

    # =========================================================================
    # Suggested Mode Tests
    # =========================================================================

    def test_suggested_mode_values(self):
        """Test SuggestedMode enum values"""
        assert SuggestedMode.IGNORE.value == "ignore"
        assert SuggestedMode.RESEARCH.value == "research"
        assert SuggestedMode.ALERT_ONLY.value == "alert_only"
        assert SuggestedMode.MANUAL_REVIEW.value == "manual_review"
        assert SuggestedMode.AVOID.value == "avoid"

    def test_suggested_mode_no_trade(self):
        """Test that 'trade' is not a valid suggested mode"""
        valid_modes = [mode.value for mode in SuggestedMode]
        assert "trade" not in valid_modes

    # =========================================================================
    # Summary Tests
    # =========================================================================

    def test_get_summary(self, engine: EventIntelligenceEngine):
        """Test assessment summary"""
        market = create_event_market()
        assessment = engine.assess(market)

        summary = assessment.get_summary()

        assert "Event" in summary
        assert "score=" in summary
        assert "evidence=" in summary
        assert "relevance=" in summary
        assert "ambiguity=" in summary
