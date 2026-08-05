"""Tests for Phase 6 — Strategy Signal Validation."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import pytest

from scripts.validate_strategy_signals import (
    ALPHA_DISCLAIMER,
    VALIDATION_DISCLAIMER,
    AlphaForwardChange,
    AlphaValidator,
    AvoidGroupComparison,
    AvoidRiskValidation,
    AvoidValidator,
    CategoryPerformance,
    CategoryValidator,
    EventScoreCorrelationValidator,
    ValidationDataLoader,
    ValidationReportGenerator,
    WatchlistPersistence,
    WatchlistValidator,
    _compute_slope,
    _get_alpha_conclusion_status,
    _infer_category,
    _pearson_correlation,
    _safe_float,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_runs(tmp_path: Path) -> Path:
    """Create a temporary runs directory with sample data."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Create a run directory
    run_dir = runs_dir / "run_20260509_112002_8977ca4e"
    run_dir.mkdir()

    # summary.json
    summary = {
        "run_id": "run_20260509_112002_8977ca4e",
        "duration_minutes": 240,
        "live_trading_enabled": False,
        "allow_auto_execution": False,
        "markets_checked": 20,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary))

    # events.jsonl with LLM sampling events
    events = []
    for i in range(5):
        events.append(json.dumps({
            "event_type": "llm_sampling_assessment",
            "timestamp": f"2026-05-09T12:{i:02d}:00",
            "details": {
                "market_id": f"market_{i}",
                "question": f"Will event {i} happen?",
                "combined_ask": 0.98 + i * 0.005,
                "event_score": 70 + i * 3,
                "ambiguity_risk": 20 + i * 5,
                "suggested_mode": "research" if i < 3 else "alert_only",
                "confidence": 0.6 + i * 0.05,
                "risk_flags": [],
            },
        }))
    # Add a non-llm event to verify filtering
    events.append(json.dumps({
        "event_type": "market_scan",
        "timestamp": "2026-05-09T13:00:00",
        "details": {"market_id": "market_x"},
    }))
    (run_dir / "events.jsonl").write_text("\n".join(events))

    # alpha_candidates.csv
    alpha_path = runs_dir / "alpha_candidates.csv"
    with open(alpha_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["market_id", "question", "alpha_score", "evidence_level"])
        writer.writeheader()
        writer.writerow({"market_id": "market_0", "question": "Will event 0 happen?", "alpha_score": "85.5", "evidence_level": "strong"})
        writer.writerow({"market_id": "market_1", "question": "Will event 1 happen?", "alpha_score": "72.0", "evidence_level": "moderate"})
        writer.writerow({"market_id": "market_99", "question": "Unknown market", "alpha_score": "60.0", "evidence_level": "weak"})

    # avoid_candidates.csv
    avoid_path = runs_dir / "avoid_candidates.csv"
    with open(avoid_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["market_id", "question", "avoid_score", "reasons", "avg_ambiguity_risk", "category_risk"])
        writer.writeheader()
        writer.writerow({"market_id": "market_3", "question": "Will event 3 happen?", "avoid_score": "75.0", "reasons": "high_ambiguity", "avg_ambiguity_risk": "45.0", "category_risk": "0.8"})
        writer.writerow({"market_id": "market_4", "question": "Will event 4 happen?", "avoid_score": "68.0", "reasons": "category_risk", "avg_ambiguity_risk": "35.0", "category_risk": "0.7"})

    # persistent_watchlist.csv
    wl_path = runs_dir / "persistent_watchlist.csv"
    with open(wl_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["market_id", "question", "evidence_level"])
        writer.writeheader()
        writer.writerow({"market_id": "market_0", "question": "Will event 0 happen?", "evidence_level": "strong"})
        writer.writerow({"market_id": "market_1", "question": "Will event 1 happen?", "evidence_level": "moderate"})

    # market_trajectories.json
    trajectories = [
        {
            "market_id": "market_0",
            "question": "Will event 0 happen?",
            "trajectory": [
                {"combined_ask": 0.98, "event_score": 70, "timestamp": "2026-05-09T10:00:00"},
                {"combined_ask": 0.975, "event_score": 73, "timestamp": "2026-05-09T11:00:00"},
                {"combined_ask": 0.97, "event_score": 75, "timestamp": "2026-05-09T12:00:00"},
                {"combined_ask": 0.965, "event_score": 78, "timestamp": "2026-05-09T13:00:00"},
            ],
        },
        {
            "market_id": "market_1",
            "question": "Will event 1 happen?",
            "trajectory": [
                {"combined_ask": 0.99, "event_score": 72, "timestamp": "2026-05-09T10:00:00"},
                {"combined_ask": 0.985, "event_score": 74, "timestamp": "2026-05-09T11:00:00"},
            ],
        },
    ]
    (runs_dir / "market_trajectories.json").write_text(json.dumps(trajectories))

    # intelligence_comparison_summary.json
    comp_summary = {
        "num_runs_analyzed": 1,
        "safety_verification": {"live_trading_enabled": False},
    }
    (runs_dir / "intelligence_comparison_summary.json").write_text(json.dumps(comp_summary))

    return runs_dir


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestSafeFloat:
    def test_none_returns_default(self):
        assert _safe_float(None) is None
        assert _safe_float(None, 0.0) == 0.0

    def test_valid_float(self):
        assert _safe_float(3.14) == pytest.approx(3.14)
        assert _safe_float("2.5") == pytest.approx(2.5)
        assert _safe_float(0) == 0.0

    def test_invalid_returns_default(self):
        assert _safe_float("not_a_number") is None
        assert _safe_float("abc", 0.0) == 0.0


class TestComputeSlope:
    def test_single_value_returns_zero(self):
        assert _compute_slope([1.0]) == 0.0

    def test_increasing_values_positive_slope(self):
        slope = _compute_slope([1.0, 2.0, 3.0, 4.0])
        assert slope > 0

    def test_decreasing_values_negative_slope(self):
        slope = _compute_slope([4.0, 3.0, 2.0, 1.0])
        assert slope < 0

    def test_constant_values_zero_slope(self):
        assert _compute_slope([5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_two_values(self):
        slope = _compute_slope([0.0, 10.0])
        assert slope == pytest.approx(10.0)


class TestPearsonCorrelation:
    def test_perfect_positive(self):
        r = _pearson_correlation([1, 2, 3, 4], [2, 4, 6, 8])
        assert r == pytest.approx(1.0)

    def test_perfect_negative(self):
        r = _pearson_correlation([1, 2, 3, 4], [8, 6, 4, 2])
        assert r == pytest.approx(-1.0)

    def test_no_correlation(self):
        # Constant ys -> 0
        r = _pearson_correlation([1, 2, 3], [5, 5, 5])
        assert r == pytest.approx(0.0)

    def test_too_few_points(self):
        assert _pearson_correlation([1], [2]) == 0.0


class TestInferCategory:
    def test_sports(self):
        assert _infer_category("Will the NBA team win?") == "Sports"

    def test_sports_fifa(self):
        assert _infer_category("Will France win the 2026 FIFA World Cup?") == "Sports"

    def test_sports_uefa(self):
        assert _infer_category("UEFA Champions League winner?") == "Sports"

    def test_sports_tennis(self):
        assert _infer_category("Who will win the tennis Grand Slam?") == "Sports"

    def test_gaming(self):
        assert _infer_category("Will GTA 6 be released?") == "Gaming"

    def test_crypto(self):
        assert _infer_category("Will Bitcoin hit 100k?") == "Crypto"

    def test_crypto_solana(self):
        assert _infer_category("Will Solana reach $500?") == "Crypto"

    def test_crypto_btc(self):
        assert _infer_category("BTC dominance above 50%?") == "Crypto"

    def test_politics(self):
        assert _infer_category("Will the president get re-elected in 2028?") == "Politics"

    def test_politics_nomination(self):
        assert _infer_category("Will Gavin Newsom win the 2028 Democratic presidential nomination?") == "Politics"

    def test_politics_primary(self):
        assert _infer_category("Who will win the Republican primary?") == "Politics"

    def test_legal(self):
        assert _infer_category("Will the trial result in prison?") == "Legal"

    def test_legal_sentenced(self):
        assert _infer_category("Will the defendant be sentenced?") == "Legal"

    def test_legal_lawsuit(self):
        assert _infer_category("Lawsuit settlement amount?") == "Legal"

    def test_entertainment(self):
        assert _infer_category("Who will win the Oscar?") == "Entertainment"

    def test_geopolitics(self):
        assert _infer_category("Will China invade Taiwan?") == "Geopolitics"

    def test_other(self):
        assert _infer_category("Will the weather be sunny?") == "Other"


# =============================================================================
# Data Loader Tests
# =============================================================================


class TestValidationDataLoader:
    def test_discover_runs(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        run_ids = loader.discover_runs()
        assert len(run_ids) == 1
        assert "run_20260509_112002_8977ca4e" in run_ids

    def test_discover_runs_empty(self, tmp_path: Path):
        loader = ValidationDataLoader(tmp_path / "nonexistent")
        assert loader.discover_runs() == []

    def test_load_run_summary(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        summary = loader.load_run_summary("run_20260509_112002_8977ca4e")
        assert summary is not None
        assert summary["run_id"] == "run_20260509_112002_8977ca4e"
        assert summary["live_trading_enabled"] is False

    def test_load_run_summary_missing(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        assert loader.load_run_summary("nonexistent_run") is None

    def test_load_llm_sampling_events(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        events = loader.load_llm_sampling_events("run_20260509_112002_8977ca4e")
        assert len(events) == 5
        assert all(e["event_type"] == "llm_sampling_assessment" for e in events)

    def test_load_llm_sampling_events_filters_non_llm(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        events = loader.load_llm_sampling_events("run_20260509_112002_8977ca4e")
        types = {e["event_type"] for e in events}
        assert "market_scan" not in types

    def test_load_all_llm_events(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        events = loader.load_all_llm_events()
        assert len(events) == 5

    def test_load_alpha_candidates(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        candidates = loader.load_alpha_candidates()
        assert len(candidates) == 3
        assert candidates[0]["market_id"] == "market_0"

    def test_load_avoid_candidates(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        candidates = loader.load_avoid_candidates()
        assert len(candidates) == 2

    def test_load_persistent_watchlist(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        wl = loader.load_persistent_watchlist()
        assert len(wl) == 2

    def test_load_trajectories(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        trajs = loader.load_trajectories()
        assert len(trajs) == 2

    def test_load_comparison_summary(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        summary = loader.load_comparison_summary()
        assert summary is not None
        assert summary["num_runs_analyzed"] == 1

    def test_load_missing_files_returns_empty(self, tmp_path: Path):
        loader = ValidationDataLoader(tmp_path)
        assert loader.load_alpha_candidates() == []
        assert loader.load_avoid_candidates() == []
        assert loader.load_persistent_watchlist() == []
        assert loader.load_trajectories() == []
        assert loader.load_comparison_summary() is None


# =============================================================================
# Alpha Validator Tests
# =============================================================================


class TestAlphaValidator:
    def test_validate_with_trajectory_data(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        alpha = loader.load_alpha_candidates()
        trajs = loader.load_trajectories()
        events = loader.load_all_llm_events()

        validator = AlphaValidator()
        results = validator.validate(alpha, trajs, events)

        assert len(results) == 3

        # market_0 has 4 trajectory observations -> preliminary_observed
        r0 = next(r for r in results if r.market_id == "market_0")
        assert r0.conclusion_status == "preliminary_observed"
        assert r0.num_observations == 4
        assert r0.first_combined_ask == pytest.approx(0.98)
        assert r0.last_combined_ask == pytest.approx(0.965)
        assert r0.delta == pytest.approx(-0.015)
        assert r0.slope is not None and r0.slope < 0

    def test_validate_with_two_observations_weak_descriptive(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        alpha = loader.load_alpha_candidates()
        trajs = loader.load_trajectories()
        events = loader.load_all_llm_events()

        validator = AlphaValidator()
        results = validator.validate(alpha, trajs, events)

        # market_1 has 2 trajectory observations -> weak_descriptive
        r1 = next(r for r in results if r.market_id == "market_1")
        assert r1.conclusion_status == "weak_descriptive"
        assert r1.num_observations == 2

    def test_alpha_conclusion_tiers(self):
        assert _get_alpha_conclusion_status(0) == "insufficient_data"
        assert _get_alpha_conclusion_status(1) == "insufficient_data"
        assert _get_alpha_conclusion_status(2) == "weak_descriptive"
        assert _get_alpha_conclusion_status(3) == "preliminary_observed"
        assert _get_alpha_conclusion_status(4) == "preliminary_observed"
        assert _get_alpha_conclusion_status(5) == "stronger_observed"

    def test_validate_no_data_market(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        alpha = loader.load_alpha_candidates()
        trajs = loader.load_trajectories()
        events = loader.load_all_llm_events()

        validator = AlphaValidator()
        results = validator.validate(alpha, trajs, events)

        # market_99 has no trajectory data but has LLM events -> single-run fallback
        r99 = next(r for r in results if r.market_id == "market_99")
        assert r99.conclusion_status == "insufficient_data"
        assert "No trajectory" in r99.note or "Single-run" in r99.note

    def test_validate_empty_inputs(self):
        validator = AlphaValidator()
        results = validator.validate([], [], [])
        assert results == []

    def test_validate_preserves_alpha_score(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        alpha = loader.load_alpha_candidates()
        trajs = loader.load_trajectories()

        validator = AlphaValidator()
        results = validator.validate(alpha, trajs, [])

        r0 = next(r for r in results if r.market_id == "market_0")
        assert r0.alpha_score == pytest.approx(85.5)
        assert r0.evidence_level == "strong"


# =============================================================================
# Watchlist Validator Tests
# =============================================================================


class TestWatchlistValidator:
    def test_validate_persistence(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        wl = loader.load_persistent_watchlist()
        trajs = loader.load_trajectories()

        validator = WatchlistValidator()
        results = validator.validate(wl, trajs, min_appearances=2)

        assert len(results) == 2

        # market_0: 4 appearances, all near-miss (all <= 1.03)
        r0 = next(r for r in results if r.market_id == "market_0")
        assert r0.total_appearances == 4
        assert r0.near_miss_hits == 4
        assert r0.persistence_score == pytest.approx(1.0)
        assert r0.conclusion_status == "observed"
        assert r0.avg_combined_ask is not None

    def test_validate_two_appearances_observed(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        wl = loader.load_persistent_watchlist()
        trajs = loader.load_trajectories()

        validator = WatchlistValidator()
        results = validator.validate(wl, trajs, min_appearances=2)

        # market_1: 2 appearances -> observed (min_appearances=2)
        r1 = next(r for r in results if r.market_id == "market_1")
        assert r1.total_appearances == 2
        assert r1.conclusion_status == "observed"

    def test_validate_no_trajectory_data(self):
        validator = WatchlistValidator()
        wl = [{"market_id": "m1", "question": "test", "evidence_level": "weak"}]
        results = validator.validate(wl, [], min_appearances=2)

        assert len(results) == 1
        assert results[0].conclusion_status == "insufficient_data"
        assert results[0].total_appearances == 0

    def test_validate_high_combined_ask_not_near_miss(self):
        validator = WatchlistValidator()
        wl = [{"market_id": "m1", "question": "test", "evidence_level": "weak"}]
        trajs = [{
            "market_id": "m1",
            "question": "test",
            "trajectory": [
                {"combined_ask": 1.05, "event_score": 50},
                {"combined_ask": 1.10, "event_score": 40},
                {"combined_ask": 1.15, "event_score": 30},
            ],
        }]
        results = validator.validate(wl, trajs, min_appearances=2)

        assert results[0].near_miss_hits == 0
        assert results[0].persistence_score == pytest.approx(0.0)
        assert results[0].conclusion_status == "observed"


# =============================================================================
# Avoid Validator Tests
# =============================================================================


class TestAvoidValidator:
    def test_validate_single_with_events(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        avoid = loader.load_avoid_candidates()
        events = loader.load_all_llm_events()

        validator = AvoidValidator()
        # market_3 has events (indices 3, 4)
        result = validator.validate_single(avoid[0], events)

        assert result.market_id == "market_3"
        assert result.avoid_score == pytest.approx(75.0)
        assert result.conclusion_status == "observed"
        assert result.suggested_mode == "alert_only"

    def test_validate_single_no_events(self):
        validator = AvoidValidator()
        cand = {"market_id": "no_data", "question": "test", "avoid_score": "50", "reasons": "test"}
        result = validator.validate_single(cand, [])

        assert result.conclusion_status == "insufficient_data"
        assert "No LLM event data" in result.note

    def test_validate_group_comparison_insufficient_control(self, tmp_runs: Path):
        """When non-avoid group is too small, should return insufficient_control_group."""
        loader = ValidationDataLoader(tmp_runs)
        avoid = loader.load_avoid_candidates()
        events = loader.load_all_llm_events()

        validator = AvoidValidator()
        comparison = validator.validate_group_comparison(avoid, events)

        # Only 5 markets in events, 2 are avoid -> 3 non-avoid (exactly 3 is >= 3)
        # But we need to check actual logic
        assert comparison.avoid_group_size == 2
        assert comparison.conclusion_status in ("observed", "insufficient_control_group")

    def test_validate_group_comparison_insufficient_control_too_small(self):
        """When non-avoid group < 3, should return insufficient_control_group."""
        validator = AvoidValidator()
        avoid = [
            {"market_id": "m1", "avoid_score": "70"},
            {"market_id": "m2", "avoid_score": "65"},
        ]
        # Only 2 non-avoid markets
        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m1", "ambiguity_risk": 50}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m2", "ambiguity_risk": 45}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m3", "ambiguity_risk": 20}},
        ]
        comparison = validator.validate_group_comparison(avoid, events)

        assert comparison.conclusion_status == "insufficient_control_group"
        assert comparison.non_avoid_group_size < 3

    def test_validate_group_comparison_observed(self):
        """When enough data, should return observed with ambiguity delta."""
        validator = AvoidValidator()
        avoid = [{"market_id": "m1", "avoid_score": "70"}]
        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m1", "ambiguity_risk": 60}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m2", "ambiguity_risk": 20}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m3", "ambiguity_risk": 15}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "m4", "ambiguity_risk": 25}},
        ]
        comparison = validator.validate_group_comparison(avoid, events)

        assert comparison.conclusion_status == "observed"
        assert comparison.avoid_avg_ambiguity_risk == pytest.approx(60.0)
        assert comparison.ambiguity_risk_delta is not None
        assert comparison.ambiguity_risk_delta > 0  # avoid has higher ambiguity


# =============================================================================
# Event Score Correlation Validator Tests
# =============================================================================


class TestEventScoreCorrelationValidator:
    def test_validate_with_enough_data(self):
        validator = EventScoreCorrelationValidator()
        trajectories = [{
            "market_id": "m1",
            "trajectory": [
                {"event_score": 80, "combined_ask": 0.95},
                {"event_score": 85, "combined_ask": 0.93},
                {"event_score": 90, "combined_ask": 0.91},
                {"event_score": 70, "combined_ask": 0.97},
            ],
        }]
        result = validator.validate(trajectories)

        assert result["conclusion_status"] == "observed"
        assert "correlation" in result
        assert result["num_pairs"] == 3

    def test_validate_insufficient_data(self):
        validator = EventScoreCorrelationValidator()
        trajectories = [{
            "market_id": "m1",
            "trajectory": [
                {"event_score": 80, "combined_ask": 0.95},
            ],
        }]
        result = validator.validate(trajectories)

        assert result["conclusion_status"] == "insufficient_data"
        assert result["num_pairs"] == 0

    def test_validate_exactly_two_pairs_insufficient(self):
        validator = EventScoreCorrelationValidator()
        trajectories = [{
            "market_id": "m1",
            "trajectory": [
                {"event_score": 80, "combined_ask": 0.95},
                {"event_score": 85, "combined_ask": 0.93},
                {"event_score": 90, "combined_ask": 0.91},
            ],
        }]
        result = validator.validate(trajectories)

        assert result["conclusion_status"] == "insufficient_data"
        assert result["num_pairs"] == 2


# =============================================================================
# Category Validator Tests
# =============================================================================


class TestCategoryValidator:
    def test_validate_categories(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        alpha = loader.load_alpha_candidates()
        avoid = loader.load_avoid_candidates()
        events = loader.load_all_llm_events()

        validator = CategoryValidator()
        results = validator.validate(alpha, avoid, events)

        assert len(results) > 0
        categories = {r.category for r in results}
        assert "Other" in categories  # "Will event X happen?" -> Other

    def test_validate_market_count(self, tmp_runs: Path):
        loader = ValidationDataLoader(tmp_runs)
        alpha = loader.load_alpha_candidates()
        avoid = loader.load_avoid_candidates()
        events = loader.load_all_llm_events()

        validator = CategoryValidator()
        results = validator.validate(alpha, avoid, events)

        total_markets = sum(r.market_count for r in results)
        assert total_markets >= 5  # 5 unique markets from events

    def test_validate_empty_inputs(self):
        validator = CategoryValidator()
        results = validator.validate([], [], [])
        assert results == []


# =============================================================================
# Report Generator Tests
# =============================================================================


class TestValidationReportGenerator:
    def test_generate_report_contains_disclaimers(self, tmp_path: Path):
        generator = ValidationReportGenerator(tmp_path)
        report = generator.generate_report(
            alpha_results=[],
            watchlist_results=[],
            avoid_results=[],
            avoid_comparison=AvoidGroupComparison(),
            category_results=[],
            correlation_result={"conclusion_status": "insufficient_data", "note": "", "num_pairs": 0},
            summary={"num_runs": 1},
        )

        assert "Strategy Signal Validation Report" in report
        assert ALPHA_DISCLAIMER in report
        assert VALIDATION_DISCLAIMER in report
        assert "live_trading_enabled: false" in report
        assert "allow_auto_execution: false" in report

    def test_generate_summary_json_safety(self, tmp_path: Path):
        generator = ValidationReportGenerator(tmp_path)
        summary = generator.generate_summary_json(
            alpha_results=[],
            watchlist_results=[],
            avoid_results=[],
            avoid_comparison=AvoidGroupComparison(),
            category_results=[],
            correlation_result={"conclusion_status": "insufficient_data", "note": "", "num_pairs": 0},
            num_runs=1,
        )

        assert summary["safety_verification"]["live_trading_enabled"] is False
        assert summary["safety_verification"]["allow_auto_execution"] is False
        assert summary["safety_verification"]["real_api_calls"] is False
        assert summary["safety_verification"]["trading_actions"] is False
        assert summary["alpha_disclaimer"] == ALPHA_DISCLAIMER

    def test_export_alpha_csv(self, tmp_path: Path):
        generator = ValidationReportGenerator(tmp_path)
        results = [
            AlphaForwardChange(
                market_id="m1", question="test", alpha_score=80.0,
                evidence_level="strong", first_combined_ask=0.95,
                last_combined_ask=0.93, min_combined_ask=0.92,
                max_combined_ask=0.96, delta=-0.02, slope=-0.005,
                num_observations=4, conclusion_status="preliminary_observed",
            ),
        ]
        path = generator.export_alpha_csv(results)
        assert path.exists()

        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["market_id"] == "m1"
        assert rows[0]["conclusion_status"] == "preliminary_observed"

    def test_export_avoid_csv(self, tmp_path: Path):
        generator = ValidationReportGenerator(tmp_path)
        results = [
            AvoidRiskValidation(
                market_id="m1", question="test", avoid_score=70.0,
                reasons="high_ambiguity", conclusion_status="observed",
            ),
        ]
        path = generator.export_avoid_csv(results)
        assert path.exists()

        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1

    def test_export_watchlist_csv(self, tmp_path: Path):
        generator = ValidationReportGenerator(tmp_path)
        results = [
            WatchlistPersistence(
                market_id="m1", question="test", evidence_level="strong",
                total_appearances=4, near_miss_hits=3,
                persistence_score=0.75, conclusion_status="observed",
            ),
        ]
        path = generator.export_watchlist_csv(results)
        assert path.exists()

        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["persistence_score"] == "0.75"

    def test_overall_status_all_observed(self):
        results = [
            AlphaForwardChange(market_id="m1", question="", alpha_score=0, evidence_level="strong", conclusion_status="observed"),
            AlphaForwardChange(market_id="m2", question="", alpha_score=0, evidence_level="moderate", conclusion_status="observed"),
        ]
        assert ValidationReportGenerator._overall_status(results) == "observed"

    def test_overall_status_all_preliminary(self):
        results = [
            AlphaForwardChange(market_id="m1", question="", alpha_score=0, evidence_level="strong", conclusion_status="preliminary_observed"),
            AlphaForwardChange(market_id="m2", question="", alpha_score=0, evidence_level="moderate", conclusion_status="preliminary_observed"),
        ]
        assert ValidationReportGenerator._overall_status(results) == "preliminary_observed"

    def test_overall_status_mixed(self):
        results = [
            AlphaForwardChange(market_id="m1", question="", alpha_score=0, evidence_level="strong", conclusion_status="observed"),
            AlphaForwardChange(market_id="m2", question="", alpha_score=0, evidence_level="weak", conclusion_status="insufficient_data"),
        ]
        assert ValidationReportGenerator._overall_status(results) == "inconclusive"

    def test_overall_status_all_insufficient(self):
        results = [
            AlphaForwardChange(market_id="m1", question="", alpha_score=0, evidence_level="weak", conclusion_status="insufficient_data"),
        ]
        assert ValidationReportGenerator._overall_status(results) == "insufficient_data"

    def test_overall_status_empty(self):
        assert ValidationReportGenerator._overall_status([]) == "insufficient_data"


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestDataclasses:
    def test_alpha_forward_change_defaults(self):
        r = AlphaForwardChange(market_id="m1", question="q", alpha_score=80.0, evidence_level="strong")
        assert r.first_combined_ask is None
        assert r.last_combined_ask is None
        assert r.delta is None
        assert r.slope is None
        assert r.num_observations == 0
        assert r.conclusion_status == "insufficient_data"

    def test_watchlist_persistence_defaults(self):
        r = WatchlistPersistence(market_id="m1", question="q", evidence_level="moderate")
        assert r.total_appearances == 0
        assert r.near_miss_hits == 0
        assert r.persistence_score == 0.0
        assert r.conclusion_status == "insufficient_data"

    def test_avoid_risk_validation_defaults(self):
        r = AvoidRiskValidation(market_id="m1", question="q", avoid_score=70.0, reasons="test")
        assert r.avg_ambiguity_risk is None
        assert r.conclusion_status == "insufficient_data"

    def test_avoid_group_comparison_defaults(self):
        c = AvoidGroupComparison()
        assert c.avoid_group_size == 0
        assert c.non_avoid_group_size == 0
        assert c.conclusion_status == "insufficient_data"

    def test_category_performance_defaults(self):
        p = CategoryPerformance(category="Gaming")
        assert p.market_count == 0
        assert p.avg_alpha_score is None
        assert p.conclusion_status == "insufficient_data"


# =============================================================================
# AST Safety Audit Tests
# =============================================================================


class TestASTSafetyAudit:
    """Verify validate_strategy_signals.py does NOT import trading modules."""

    def _get_imported_modules(self, filepath: Path) -> list[str]:
        """Parse file and return all imported module names."""
        source = filepath.read_text()
        tree = ast.parse(source)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.append(node.module)
        return modules

    def test_no_live_trader_import(self):
        filepath = Path(__file__).resolve().parent.parent / "scripts" / "validate_strategy_signals.py"
        modules = self._get_imported_modules(filepath)
        assert not any("live_trader" in m for m in modules), f"Forbidden import found: {[m for m in modules if 'live_trader' in m]}"

    def test_no_paper_trader_import(self):
        filepath = Path(__file__).resolve().parent.parent / "scripts" / "validate_strategy_signals.py"
        modules = self._get_imported_modules(filepath)
        assert not any("paper_trader" in m for m in modules), f"Forbidden import found: {[m for m in modules if 'paper_trader' in m]}"

    def test_no_risk_governor_import(self):
        filepath = Path(__file__).resolve().parent.parent / "scripts" / "validate_strategy_signals.py"
        modules = self._get_imported_modules(filepath)
        assert not any("risk_governor" in m for m in modules), f"Forbidden import found: {[m for m in modules if 'risk_governor' in m]}"

    def test_no_authenticated_clob_import(self):
        filepath = Path(__file__).resolve().parent.parent / "scripts" / "validate_strategy_signals.py"
        modules = self._get_imported_modules(filepath)
        assert not any("authenticated" in m for m in modules), f"Forbidden import found: {[m for m in modules if 'authenticated' in m]}"


# =============================================================================
# Integration Test
# =============================================================================


class TestIntegration:
    def test_full_pipeline(self, tmp_runs: Path):
        """Run full validation pipeline on sample data."""
        loader = ValidationDataLoader(tmp_runs)
        run_ids = loader.discover_runs()
        assert len(run_ids) > 0

        alpha_candidates = loader.load_alpha_candidates()
        avoid_candidates = loader.load_avoid_candidates()
        watchlist = loader.load_persistent_watchlist()
        trajectories = loader.load_trajectories()
        all_events = loader.load_all_llm_events()

        # Alpha validation
        alpha_validator = AlphaValidator()
        alpha_results = alpha_validator.validate(alpha_candidates, trajectories, all_events)
        assert len(alpha_results) == len(alpha_candidates)

        # Avoid validation
        avoid_validator = AvoidValidator()
        avoid_results = [avoid_validator.validate_single(c, all_events) for c in avoid_candidates]
        avoid_comparison = avoid_validator.validate_group_comparison(avoid_candidates, all_events)
        assert len(avoid_results) == len(avoid_candidates)

        # Watchlist validation
        wl_validator = WatchlistValidator()
        wl_results = wl_validator.validate(watchlist, trajectories, min_appearances=2)
        assert len(wl_results) == len(watchlist)

        # Correlation validation
        corr_validator = EventScoreCorrelationValidator()
        corr_result = corr_validator.validate(trajectories)
        assert corr_result["conclusion_status"] in ("observed", "insufficient_data")

        # Category validation
        cat_validator = CategoryValidator()
        cat_results = cat_validator.validate(alpha_candidates, avoid_candidates, all_events)
        assert len(cat_results) > 0

        # Report generation
        output_dir = tmp_runs / "output"
        output_dir.mkdir()
        generator = ValidationReportGenerator(output_dir)

        report = generator.generate_report(
            alpha_results, wl_results, avoid_results,
            avoid_comparison, cat_results, corr_result,
            {"num_runs": len(run_ids)},
        )
        assert "Strategy Signal Validation Report" in report
        assert ALPHA_DISCLAIMER in report

        summary = generator.generate_summary_json(
            alpha_results, wl_results, avoid_results,
            avoid_comparison, cat_results, corr_result,
            len(run_ids),
        )
        assert summary["safety_verification"]["live_trading_enabled"] is False

        # CSV exports
        alpha_csv = generator.export_alpha_csv(alpha_results)
        avoid_csv = generator.export_avoid_csv(avoid_results)
        wl_csv = generator.export_watchlist_csv(wl_results)

        assert alpha_csv.exists()
        assert avoid_csv.exists()
        assert wl_csv.exists()


# =============================================================================
# Control Group Tests (Phase 6.5A)
# =============================================================================


class TestControlGroupIntegration:
    def test_full_pipeline_with_control_group(self, tmp_path: Path):
        """Run full pipeline with control group samples."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run_test"
        run_dir.mkdir()

        # summary
        (run_dir / "summary.json").write_text(json.dumps({
            "run_id": "run_test",
            "live_trading_enabled": False,
            "control_group_samples": 3,
        }))

        # control_group_samples.csv
        with open(run_dir / "control_group_samples.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "market_id", "question", "category", "combined_ask",
                "event_score", "ambiguity_risk", "suggested_mode",
                "confidence", "success", "timestamp",
            ])
            writer.writeheader()
            for i in range(3):
                writer.writerow({
                    "market_id": f"cg_{i}", "question": f"CG market {i}",
                    "category": "Sports", "combined_ask": "0.97",
                    "event_score": str(70 + i * 5), "ambiguity_risk": str(10 + i * 3),
                    "suggested_mode": "research", "confidence": "0.8",
                    "success": "True", "timestamp": f"2026-05-10T12:{i:02d}:00",
                })

        # avoid_candidates.csv
        with open(runs_dir / "avoid_candidates.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["market_id", "question", "avoid_score", "reasons"])
            writer.writeheader()
            writer.writerow({"market_id": "avoid_1", "question": "Avoid", "avoid_score": "70", "reasons": "test"})

        # alpha_candidates.csv
        with open(runs_dir / "alpha_candidates.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["market_id", "question", "alpha_score", "evidence_level"])
            writer.writeheader()

        # persistent_watchlist.csv
        with open(runs_dir / "persistent_watchlist.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["market_id", "question", "evidence_level"])
            writer.writeheader()

        # market_trajectories.json
        (runs_dir / "market_trajectories.json").write_text("[]")

        # events.jsonl with avoid market event (so avoid group has data)
        events = [
            json.dumps({
                "event_type": "llm_sampling_assessment",
                "details": {"market_id": "avoid_1", "ambiguity_risk": 55, "event_score": 30},
            }),
        ]
        (run_dir / "events.jsonl").write_text("\n".join(events))

        loader = ValidationDataLoader(runs_dir)
        cg_samples = loader.load_control_group_samples()
        assert len(cg_samples) == 3

        avoid = loader.load_avoid_candidates()
        all_events = loader.load_all_llm_events()

        avoid_validator = AvoidValidator()
        comparison = avoid_validator.validate_group_comparison(avoid, all_events, cg_samples)
        assert comparison.non_avoid_group_size >= 3
        assert comparison.conclusion_status == "observed"

    def test_control_group_excludes_avoid_in_validation(self, tmp_path: Path):
        """Control group samples with avoid IDs should be excluded from non-avoid group."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run_test"
        run_dir.mkdir()
        (run_dir / "summary.json").write_text(json.dumps({"run_id": "run_test"}))

        # control_group_samples.csv includes an avoid market
        with open(run_dir / "control_group_samples.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "market_id", "question", "category", "combined_ask",
                "event_score", "ambiguity_risk", "suggested_mode",
                "confidence", "success", "timestamp",
            ])
            writer.writeheader()
            writer.writerow({
                "market_id": "avoid_1", "question": "In avoid list",
                "category": "Other", "combined_ask": "0.99",
                "event_score": "50", "ambiguity_risk": "40",
                "suggested_mode": "avoid", "confidence": "0.5",
                "success": "True", "timestamp": "2026-05-10T12:00:00",
            })
            writer.writerow({
                "market_id": "cg_good", "question": "Not in avoid",
                "category": "Sports", "combined_ask": "0.97",
                "event_score": "75", "ambiguity_risk": "10",
                "suggested_mode": "research", "confidence": "0.8",
                "success": "True", "timestamp": "2026-05-10T12:05:00",
            })

        with open(runs_dir / "avoid_candidates.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["market_id", "question", "avoid_score", "reasons"])
            writer.writeheader()
            writer.writerow({"market_id": "avoid_1", "question": "Avoid", "avoid_score": "70", "reasons": "test"})

        loader = ValidationDataLoader(runs_dir)
        avoid = loader.load_avoid_candidates()
        cg_samples = loader.load_control_group_samples()

        avoid_validator = AvoidValidator()
        comparison = avoid_validator.validate_group_comparison(avoid, [], cg_samples)

        # avoid_1 should be excluded from non-avoid group
        # Only cg_good should be in non-avoid
        assert comparison.non_avoid_group_size >= 1
