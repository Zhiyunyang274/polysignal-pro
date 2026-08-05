"""
Tests for Multi-Run Intelligence Comparison - Phase 5F
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.compare_run_intelligence import (
    AlphaCandidateScorer,
    AvoidCandidateScorer,
    CategoryAnalyzer,
    ComparisonReportGenerator,
    ComparisonSummary,
    MarketAggregator,
    MarketObservation,
    MarketSummary,
    PersistentWatchlistGenerator,
    RunDataLoader,
    RunDiscovery,
    RunSummary,
    calculate_evidence_level,
    get_category_risk_score,
    infer_market_category,
    normalize_question,
)


class TestNormalizeQuestion:
    """Test question normalization"""

    def test_normalize_basic(self):
        """Test basic normalization"""
        result = normalize_question("Will Bitcoin hit $100k?")
        assert result == "will bitcoin hit 100k"

    def test_normalize_punctuation(self):
        """Test punctuation removal"""
        result = normalize_question("Will the Colorado Avalanche win? (NHL 2026)")
        assert "(" not in result
        assert ")" not in result
        assert "?" not in result

    def test_normalize_whitespace(self):
        """Test whitespace collapse"""
        result = normalize_question("What   will   happen?")
        assert result == "what will happen"

    def test_normalize_empty(self):
        """Test empty string"""
        result = normalize_question("")
        assert result == ""

    def test_normalize_none(self):
        """Test None input"""
        result = normalize_question(None)
        assert result == ""

    def test_normalize_truncate(self):
        """Test truncation to 100 chars"""
        long_question = "Will " + "x" * 200 + " happen?"
        result = normalize_question(long_question)
        assert len(result) <= 100


class TestInferMarketCategory:
    """Test market category inference"""

    def test_sports_category(self):
        """Test sports category detection"""
        assert infer_market_category("Will the Avalanche win the Stanley Cup?") == "Sports"
        assert infer_market_category("Will France win the 2026 FIFA World Cup?") == "Sports"
        assert infer_market_category("UEFA Champions League winner?") == "Sports"
        assert infer_market_category("Who will win the Premier League?") == "Sports"

    def test_crypto_category(self):
        """Test crypto category detection"""
        assert infer_market_category("Will Bitcoin hit $100k?") == "Crypto"
        assert infer_market_category("Will Solana reach $500?") == "Crypto"
        assert infer_market_category("BTC dominance above 50%?") == "Crypto"

    def test_gaming_category(self):
        """Test gaming category detection"""
        assert infer_market_category("Will GTA VI be released in 2026?") == "Gaming"

    def test_politics_category(self):
        """Test politics category detection"""
        assert infer_market_category("Who will win the 2028 election?") == "Politics"
        assert infer_market_category("Will Gavin Newsom win the 2028 Democratic presidential nomination?") == "Politics"
        assert infer_market_category("Who will win the Republican primary?") == "Politics"

    def test_legal_category(self):
        """Test legal category detection"""
        assert infer_market_category("Will the defendant be convicted?") == "Legal"
        assert infer_market_category("Will the defendant go to prison?") == "Legal"
        assert infer_market_category("Will the defendant be sentenced?") == "Legal"
        assert infer_market_category("Sentencing hearing outcome?") == "Legal"

    def test_geopolitics_category(self):
        """Test geopolitics category detection"""
        assert infer_market_category("Will China invade Taiwan?") == "Geopolitics"

    def test_entertainment_category(self):
        """Test entertainment category detection"""
        assert infer_market_category("Who will win the Oscar?") == "Entertainment"

    def test_other_category(self):
        """Test other category for unknown"""
        assert infer_market_category("Random question about something") == "Other"


class TestGetCategoryRiskScore:
    """Test category risk score"""

    def test_politics_high_risk(self):
        """Test politics has high risk"""
        assert get_category_risk_score("Politics") >= 20

    def test_geopolitics_high_risk(self):
        """Test geopolitics has high risk"""
        assert get_category_risk_score("Geopolitics") >= 20

    def test_sports_low_risk(self):
        """Test sports has low risk"""
        assert get_category_risk_score("Sports") < 15

    def test_unknown_category_default(self):
        """Test unknown category gets default"""
        assert get_category_risk_score("UnknownCategory") == 10.0


class TestCalculateEvidenceLevel:
    """Test evidence level calculation"""

    def test_weak_single_appearance(self):
        """Test weak for single appearance"""
        assert calculate_evidence_level(1, 5) == "weak"

    def test_weak_few_runs(self):
        """Test weak for few total runs"""
        assert calculate_evidence_level(2, 2) == "weak"

    def test_moderate(self):
        """Test moderate evidence"""
        assert calculate_evidence_level(2, 3) == "moderate"

    def test_strong(self):
        """Test strong evidence"""
        assert calculate_evidence_level(3, 5) == "strong"

    def test_strong_high_appearances(self):
        """Test strong with high appearances"""
        assert calculate_evidence_level(5, 10) == "strong"


class TestRunDiscovery:
    """Test run discovery"""

    def test_discover_runs_empty_dir(self, tmp_path):
        """Test discovery with empty directory"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        result = RunDiscovery.discover_runs(runs_dir)
        assert result == []

    def test_discover_runs_with_valid_runs(self, tmp_path):
        """Test discovery with valid runs"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create valid run directories
        run1 = runs_dir / "run_20260508_120000_abc123"
        run1.mkdir()
        (run1 / "summary.json").write_text("{}")
        (run1 / "events.jsonl").write_text("{}")

        run2 = runs_dir / "run_20260509_120000_def456"
        run2.mkdir()
        (run2 / "summary.json").write_text("{}")
        (run2 / "events.jsonl").write_text("{}")

        result = RunDiscovery.discover_runs(runs_dir)
        assert len(result) == 2

    def test_discover_runs_with_latest_n(self, tmp_path):
        """Test discovery with latest_n filter"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        for i, (date, name) in enumerate([
            ("20260508", "abc123"),
            ("20260509", "def456"),
            ("20260510", "ghi789"),
        ]):
            run_dir = runs_dir / f"run_{date}_120000_{name}"
            run_dir.mkdir()
            (run_dir / "summary.json").write_text("{}")
            (run_dir / "events.jsonl").write_text("{}")

        result = RunDiscovery.discover_runs(runs_dir, latest_n=2)
        assert len(result) == 2
        # Should be sorted by name descending (latest first)
        assert "run_20260510" in result[0].name

    def test_discover_runs_with_run_ids(self, tmp_path):
        """Test discovery with specific run_ids"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run1 = runs_dir / "run_20260508_120000_abc123"
        run1.mkdir()
        (run1 / "summary.json").write_text("{}")

        run2 = runs_dir / "run_20260509_120000_def456"
        run2.mkdir()
        (run2 / "summary.json").write_text("{}")

        result = RunDiscovery.discover_runs(
            runs_dir,
            run_ids=["run_20260508_120000_abc123"]
        )
        assert len(result) == 1
        assert result[0].name == "run_20260508_120000_abc123"

    def test_validate_run_missing_files(self, tmp_path):
        """Test validation with missing files"""
        run_dir = tmp_path / "run_20260508_120000_abc123"
        run_dir.mkdir()

        # No summary.json or events.jsonl
        assert RunDiscovery.validate_run(run_dir) is False

    def test_validate_run_with_intelligence_summary(self, tmp_path):
        """Test validation with intelligence_summary.json"""
        run_dir = tmp_path / "run_20260508_120000_abc123"
        run_dir.mkdir()
        (run_dir / "intelligence_summary.json").write_text("{}")

        assert RunDiscovery.validate_run(run_dir) is True


class TestRunDataLoader:
    """Test run data loading"""

    def test_load_run_with_intelligence_summary(self, tmp_path):
        """Test loading run with intelligence_summary.json"""
        run_dir = tmp_path / "run_20260508_120000_abc123"
        run_dir.mkdir()

        intelligence_summary = {
            "run_id": "run_20260508_120000_abc123",
            "total_observed_markets": 20,
            "llm_total_samples": 18,
            "llm_successful_samples": 16,
            "llm_failed_samples": 2,
            "live_trading_enabled": False,
            "allow_auto_execution": False,
        }
        (run_dir / "intelligence_summary.json").write_text(json.dumps(intelligence_summary))

        result = RunDataLoader.load_run(run_dir)

        assert result.total_observed_markets == 20
        assert result.llm_total_samples == 18
        assert result.live_trading_enabled is False

    def test_load_run_with_summary_json(self, tmp_path):
        """Test loading run with summary.json"""
        run_dir = tmp_path / "run_20260508_120000_abc123"
        run_dir.mkdir()

        summary = {
            "duration_minutes": 240,
            "data_mode": "real_readonly",
            "llm_provider": "xfyun_anthropic",
            "live_trading_enabled": False,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary))
        (run_dir / "events.jsonl").write_text("{}")

        result = RunDataLoader.load_run(run_dir)

        assert result.duration_minutes == 240
        assert result.data_mode == "real_readonly"

    def test_load_run_with_events(self, tmp_path):
        """Test loading run with events.jsonl"""
        run_dir = tmp_path / "run_20260508_120000_abc123"
        run_dir.mkdir()

        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "123"}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "456"}},
        ]
        events_jsonl = "\n".join(json.dumps(e) for e in events)
        (run_dir / "events.jsonl").write_text(events_jsonl)
        (run_dir / "summary.json").write_text("{}")

        result = RunDataLoader.load_run(run_dir)

        assert len(result.events) == 2


class TestMarketAggregator:
    """Test market aggregation"""

    def test_aggregate_markets_basic(self, tmp_path):
        """Test basic market aggregation"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create two runs with overlapping markets
        run1 = runs_dir / "run_20260508_120000_abc123"
        run1.mkdir()
        events1 = [
            {"event_type": "llm_sampling_assessment", "details": {
                "market_id": "123",
                "question": "Will Bitcoin hit $100k?",
                "combined_ask": 1.001,
                "event_score": 35.0,
                "success": True,
            }},
        ]
        (run1 / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events1))
        (run1 / "summary.json").write_text("{}")

        run2 = runs_dir / "run_20260509_120000_def456"
        run2.mkdir()
        events2 = [
            {"event_type": "llm_sampling_assessment", "details": {
                "market_id": "123",
                "question": "Will Bitcoin hit $100k?",
                "combined_ask": 1.002,
                "event_score": 38.0,
                "success": True,
            }},
            {"event_type": "llm_sampling_assessment", "details": {
                "market_id": "456",
                "question": "Will the Avalanche win?",
                "combined_ask": 1.010,
                "success": True,
            }},
        ]
        (run2 / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events2))
        (run2 / "summary.json").write_text("{}")

        # Load runs
        runs_data = [RunDataLoader.load_run(run1), RunDataLoader.load_run(run2)]

        # Aggregate
        markets = MarketAggregator.aggregate_markets(runs_data, min_appearances=1)
        MarketAggregator.calculate_aggregated_metrics(markets, 2)

        assert len(markets) == 2
        assert markets["123"].appearances == 2
        assert markets["456"].appearances == 1

    def test_aggregate_with_normalized_question_fallback(self, tmp_path):
        """Test aggregation with normalized question fallback"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run1 = runs_dir / "run_20260508_120000_abc123"
        run1.mkdir()
        # Event without market_id, only question
        events1 = [
            {"event_type": "llm_sampling_assessment", "details": {
                "question": "Will Bitcoin hit $100k?",
                "combined_ask": 1.001,
                "success": True,
            }},
        ]
        (run1 / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events1))
        (run1 / "summary.json").write_text("{}")

        runs_data = [RunDataLoader.load_run(run1)]
        markets = MarketAggregator.aggregate_markets(runs_data, min_appearances=1)

        assert len(markets) == 1
        # Should have matched_by = "normalized_question"
        market = list(markets.values())[0]
        assert market.matched_by == "normalized_question"


class TestAlphaCandidateScorer:
    """Test alpha candidate scoring"""

    def test_alpha_score_disclaimer(self):
        """Test that disclaimer is present"""
        assert "heuristic research ranking" in AlphaCandidateScorer.DISCLAIMER.lower()
        assert "not a trading signal" in AlphaCandidateScorer.DISCLAIMER.lower()

    def test_calculate_alpha_score(self):
        """Test alpha score calculation"""
        market = MarketSummary(
            market_id="123",
            question="Test question",
            category="Sports",
            appearances=3,
            avg_combined_ask=1.001,
            avg_event_score=50.0,
            avg_ambiguity_risk=10.0,
            avg_volume=200000.0,
        )
        market.observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08", near_miss_tier="tier3_weak_near_miss"),
            MarketObservation(run_id="run2", timestamp="2026-05-09", near_miss_tier="tier3_weak_near_miss"),
        ]

        score = AlphaCandidateScorer.calculate_alpha_score(market, 3)

        assert 0 <= score <= 100
        # Higher score for low combined_ask, high event_score, low ambiguity
        assert score > 50

    def test_rank_candidates(self):
        """Test ranking candidates"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                appearances=3,
                avg_combined_ask=1.001,
                avg_event_score=60.0,
                avg_ambiguity_risk=5.0,
                avg_volume=300000.0,
            ),
            "456": MarketSummary(
                market_id="456",
                appearances=2,
                avg_combined_ask=1.010,
                avg_event_score=30.0,
                avg_ambiguity_risk=20.0,
                avg_volume=100000.0,
            ),
        }
        markets["123"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08", near_miss_tier="tier3_weak_near_miss"),
        ]
        markets["456"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08"),
        ]

        candidates = AlphaCandidateScorer.rank_candidates(markets, 3, top_n=10)

        assert len(candidates) == 2
        # First should have higher score
        assert candidates[0]["alpha_score"] >= candidates[1]["alpha_score"]


class TestAvoidCandidateScorer:
    """Test avoid candidate scoring"""

    def test_calculate_avoid_score_high_ambiguity(self):
        """Test avoid score with high ambiguity"""
        market = MarketSummary(
            market_id="123",
            category="Entertainment",
            avg_ambiguity_risk=75.0,
            avg_volume=5000.0,
        )
        market.observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08", suggested_mode="avoid"),
            MarketObservation(run_id="run2", timestamp="2026-05-09", suggested_mode="avoid"),
        ]

        score, reasons = AvoidCandidateScorer.calculate_avoid_score(market, 2)

        assert score > 0
        assert "high_ambiguity" in reasons

    def test_calculate_avoid_score_category_risk(self):
        """Test avoid score with category risk"""
        market = MarketSummary(
            market_id="123",
            category="Politics",
            avg_ambiguity_risk=10.0,
        )
        market.observations = []

        score, reasons = AvoidCandidateScorer.calculate_avoid_score(market, 2)

        # Politics should have category_risk
        assert "category_risk" in reasons

    def test_avoid_not_hard_forbidden(self):
        """Test that avoid is NOT hard forbidden for politics"""
        # Politics should get category_risk, NOT hard_forbidden
        market = MarketSummary(
            market_id="123",
            category="Politics",
        )
        market.observations = []

        score, reasons = AvoidCandidateScorer.calculate_avoid_score(market, 2)

        # Should NOT have "hard_forbidden" in reasons
        assert "hard_forbidden" not in reasons
        # Should have "category_risk" instead
        assert "category_risk" in reasons


class TestPersistentWatchlistGenerator:
    """Test persistent watchlist generation"""

    def test_generate_watchlist(self):
        """Test watchlist generation"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                appearances=3,
                avg_combined_ask=1.001,
                avg_event_score=40.0,
                near_miss_tier_mode="tier3_weak_near_miss",
            ),
            "456": MarketSummary(
                market_id="456",
                appearances=1,  # Only one appearance, should not be included
                avg_combined_ask=1.002,
                near_miss_tier_mode="tier3_weak_near_miss",
            ),
        }
        markets["123"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08"),
            MarketObservation(run_id="run2", timestamp="2026-05-09"),
        ]
        markets["456"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08"),
        ]

        watchlist = PersistentWatchlistGenerator.generate(markets, 2, top_n=10)

        assert len(watchlist) == 1
        assert watchlist[0]["market_id"] == "123"

    def test_watchlist_includes_evidence_level(self):
        """Test that watchlist includes evidence level"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                appearances=3,
                avg_combined_ask=1.001,
                near_miss_tier_mode="tier3_weak_near_miss",
            ),
        }
        markets["123"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08"),
            MarketObservation(run_id="run2", timestamp="2026-05-09"),
            MarketObservation(run_id="run3", timestamp="2026-05-10"),
        ]

        watchlist = PersistentWatchlistGenerator.generate(markets, 5, top_n=10)

        assert "evidence_level" in watchlist[0]


class TestCategoryAnalyzer:
    """Test category analysis"""

    def test_analyze_categories(self):
        """Test category analysis"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                category="Sports",
                avg_event_score=40.0,
                avg_ambiguity_risk=10.0,
                near_miss_tier_mode="tier3_weak_near_miss",
            ),
            "456": MarketSummary(
                market_id="456",
                category="Sports",
                avg_event_score=30.0,
                avg_ambiguity_risk=15.0,
            ),
            "789": MarketSummary(
                market_id="789",
                category="Crypto",
                avg_event_score=50.0,
                avg_ambiguity_risk=20.0,
            ),
        }

        stats = CategoryAnalyzer.analyze(markets)

        assert "Sports" in stats
        assert "Crypto" in stats
        assert stats["Sports"]["sample_count"] == 2
        assert stats["Crypto"]["sample_count"] == 1


class TestComparisonReportGenerator:
    """Test comparison report generation"""

    def test_generate_markdown_includes_disclaimer(self):
        """Test that markdown includes alpha disclaimer"""
        summary = ComparisonSummary(
            total_runs=2,
            run_ids=["run1", "run2"],
            selection_criteria="test",
            date_range={"earliest": "2026-05-08", "latest": "2026-05-09"},
        )

        report = ComparisonReportGenerator.generate_markdown(summary)

        assert "heuristic research ranking" in report.lower()
        assert "not a trading signal" in report.lower()

    def test_generate_markdown_includes_safety_verification(self):
        """Test that markdown includes safety verification"""
        summary = ComparisonSummary(
            total_runs=2,
            run_ids=["run1", "run2"],
            selection_criteria="test",
            all_runs_live_trading_disabled=True,
            all_runs_auto_execution_disabled=True,
        )

        report = ComparisonReportGenerator.generate_markdown(summary)

        assert "live_trading_enabled" in report.lower()
        assert "false" in report.lower()

    def test_generate_json_structure(self):
        """Test JSON summary structure"""
        summary = ComparisonSummary(
            runs_dir="runs/",
            total_runs=2,
            run_ids=["run1", "run2"],
            selection_criteria="test",
            unique_markets=10,
            all_runs_live_trading_disabled=True,
        )
        summary.alpha_candidates = [{"market_id": "123", "alpha_score": 70.0}]

        json_summary = ComparisonReportGenerator.generate_json(summary)

        assert "run_selection" in json_summary
        assert "summary_statistics" in json_summary
        assert "alpha_disclaimer" in json_summary
        assert json_summary["alpha_disclaimer"] == AlphaCandidateScorer.DISCLAIMER


class TestEvidenceLevelInOutput:
    """Test that evidence level is included in outputs"""

    def test_alpha_candidates_include_evidence_level(self):
        """Test alpha candidates include evidence level"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                appearances=3,
                avg_combined_ask=1.001,
                avg_event_score=50.0,
            ),
        }
        markets["123"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08"),
        ]

        candidates = AlphaCandidateScorer.rank_candidates(markets, 5, top_n=10)

        assert "evidence_level" in candidates[0]

    def test_avoid_candidates_include_evidence_level(self):
        """Test avoid candidates include evidence level"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                category="Politics",
                appearances=3,
            ),
        }
        markets["123"].observations = []

        candidates = AvoidCandidateScorer.rank_candidates(markets, 5, top_n=10)

        assert "evidence_level" in candidates[0]

    def test_watchlist_includes_evidence_level(self):
        """Test watchlist includes evidence level"""
        markets = {
            "123": MarketSummary(
                market_id="123",
                appearances=3,
                near_miss_tier_mode="tier3_weak_near_miss",
            ),
        }
        markets["123"].observations = [
            MarketObservation(run_id="run1", timestamp="2026-05-08"),
        ]

        watchlist = PersistentWatchlistGenerator.generate(markets, 5, top_n=10)

        assert "evidence_level" in watchlist[0]


class TestSafetyConstraints:
    """Test safety constraints"""

    def test_all_runs_live_trading_disabled(self):
        """Test that safety check for live trading"""
        summary = ComparisonSummary(
            total_runs=2,
            all_runs_live_trading_disabled=True,
        )

        assert summary.all_runs_live_trading_disabled is True

    def test_detect_enabled_live_trading(self):
        """Test detection of enabled live trading"""
        summary = ComparisonSummary(
            total_runs=2,
            all_runs_live_trading_disabled=False,
        )

        assert summary.all_runs_live_trading_disabled is False

    def test_json_summary_includes_safety(self):
        """Test JSON summary includes safety verification"""
        summary = ComparisonSummary(
            total_runs=2,
            all_runs_live_trading_disabled=True,
            all_runs_auto_execution_disabled=True,
        )

        json_summary = ComparisonReportGenerator.generate_json(summary)

        assert json_summary["safety_verification"]["all_runs_live_trading_disabled"] is True


class TestTopNLimit:
    """Test top_n parameter limits"""

    def test_alpha_candidates_respects_top_n(self):
        """Test alpha candidates respects top_n"""
        markets = {}
        for i in range(30):
            markets[str(i)] = MarketSummary(
                market_id=str(i),
                appearances=2,
                avg_event_score=50.0,
            )
            markets[str(i)].observations = []

        candidates = AlphaCandidateScorer.rank_candidates(markets, 5, top_n=10)

        assert len(candidates) == 10

    def test_avoid_candidates_respects_top_n(self):
        """Test avoid candidates respects top_n"""
        markets = {}
        for i in range(30):
            markets[str(i)] = MarketSummary(
                market_id=str(i),
                category="Politics",
                appearances=2,
            )
            markets[str(i)].observations = []

        candidates = AvoidCandidateScorer.rank_candidates(markets, 5, top_n=10)

        assert len(candidates) == 10

    def test_watchlist_respects_top_n(self):
        """Test watchlist respects top_n"""
        markets = {}
        for i in range(30):
            markets[str(i)] = MarketSummary(
                market_id=str(i),
                appearances=2,
                near_miss_tier_mode="tier3_weak_near_miss",
            )
            markets[str(i)].observations = [
                MarketObservation(run_id="run1", timestamp="2026-05-08"),
            ]

        watchlist = PersistentWatchlistGenerator.generate(markets, 5, top_n=10)

        assert len(watchlist) == 10


class TestMinAppearances:
    """Test min_appearances parameter"""

    def test_min_appearances_filter(self):
        """Test that markets below min_appearances are filtered"""
        markets = {
            "123": MarketSummary(market_id="123", appearances=3),
            "456": MarketSummary(market_id="456", appearances=1),
            "789": MarketSummary(market_id="789", appearances=2),
        }
        for m in markets.values():
            m.observations = []

        # Filter with min_appearances=2
        filtered = {k: v for k, v in markets.items() if v.appearances >= 2}

        assert len(filtered) == 2
        assert "123" in filtered
        assert "789" in filtered
        assert "456" not in filtered
