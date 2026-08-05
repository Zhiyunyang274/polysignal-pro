"""Tests for Phase 6.5A — Control Group Sampling Patch."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
from typing import Any, Optional

import pytest

# Import from run_paper.py
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_paper import RunConfig, RunStatistics


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def default_run_config() -> RunConfig:
    """Default RunConfig with control_group_sampling_ratio = 0."""
    return RunConfig()


@pytest.fixture
def cg_run_config() -> RunConfig:
    """RunConfig with control group enabled."""
    return RunConfig(
        control_group_sampling_ratio=0.2,
        exclude_avoid_from_control_group=True,
        max_markets=30,
        llm_provider="xfyun_anthropic",
        enable_llm_sampling=True,
    )


@pytest.fixture
def tmp_runs_with_cg(tmp_path: Path) -> Path:
    """Create a temporary runs directory with control group samples."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Create a run directory
    run_dir = runs_dir / "run_20260510_120000_abc123"
    run_dir.mkdir()

    # summary.json
    summary = {
        "run_id": "run_20260510_120000_abc123",
        "live_trading_enabled": False,
        "allow_auto_execution": False,
        "control_group_samples": 5,
        "control_group_unique_markets": 5,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary))

    # control_group_samples.csv
    cg_path = run_dir / "control_group_samples.csv"
    with open(cg_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "market_id", "question", "category", "combined_ask",
            "event_score", "ambiguity_risk", "suggested_mode",
            "confidence", "success", "timestamp",
        ])
        writer.writeheader()
        writer.writerow({
            "market_id": "cg_market_1", "question": "Sports event?",
            "category": "Sports", "combined_ask": "0.97",
            "event_score": "72", "ambiguity_risk": "10",
            "suggested_mode": "research", "confidence": "0.8",
            "success": "True", "timestamp": "2026-05-10T12:05:00",
        })
        writer.writerow({
            "market_id": "cg_market_2", "question": "Crypto event?",
            "category": "Crypto", "combined_ask": "0.95",
            "event_score": "80", "ambiguity_risk": "5",
            "suggested_mode": "research", "confidence": "0.9",
            "success": "True", "timestamp": "2026-05-10T12:10:00",
        })
        writer.writerow({
            "market_id": "cg_market_3", "question": "Gaming event?",
            "category": "Gaming", "combined_ask": "0.98",
            "event_score": "65", "ambiguity_risk": "15",
            "suggested_mode": "alert_only", "confidence": "0.7",
            "success": "True", "timestamp": "2026-05-10T12:15:00",
        })
        writer.writerow({
            "market_id": "cg_market_4", "question": "Politics event?",
            "category": "Politics", "combined_ask": "0.96",
            "event_score": "68", "ambiguity_risk": "20",
            "suggested_mode": "research", "confidence": "0.75",
            "success": "True", "timestamp": "2026-05-10T12:20:00",
        })
        writer.writerow({
            "market_id": "cg_market_5", "question": "Legal event?",
            "category": "Legal", "combined_ask": "0.99",
            "event_score": "55", "ambiguity_risk": "25",
            "suggested_mode": "ignore", "confidence": "0.6",
            "success": "True", "timestamp": "2026-05-10T12:25:00",
        })

    # validation_loop_summary.json
    summary_path = run_dir / "validation_loop_summary.json"
    summary_data = {
        "run_id": "run_20260510_120000_abc123",
        "phase": "6.5A",
        "control_group_samples": 5,
        "unique_control_group_markets": 5,
        "control_group_categories": {
            "Sports": 1, "Crypto": 1, "Gaming": 1, "Politics": 1, "Legal": 1,
        },
        "llm_calls_used_for_control_group": 5,
        "safety_verification": {
            "live_trading_enabled": False,
            "allow_auto_execution": False,
            "real_api_calls": False,
            "trading_actions": False,
        },
    }
    summary_path.write_text(json.dumps(summary_data, indent=2))

    # avoid_candidates.csv (to test control group exclusion)
    avoid_path = runs_dir / "avoid_candidates.csv"
    with open(avoid_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["market_id", "question", "avoid_score", "reasons"])
        writer.writeheader()
        writer.writerow({"market_id": "avoid_1", "question": "Avoid market", "avoid_score": "70", "reasons": "high_ambiguity"})

    # alpha_candidates.csv
    alpha_path = runs_dir / "alpha_candidates.csv"
    with open(alpha_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["market_id", "question", "alpha_score", "evidence_level"])
        writer.writeheader()
        writer.writerow({"market_id": "alpha_1", "question": "Alpha market", "alpha_score": "85", "evidence_level": "strong"})

    # events.jsonl with control_group_assessment events
    events = [
        json.dumps({
            "event_type": "llm_sampling_assessment",
            "details": {"market_id": "alpha_1", "ambiguity_risk": 20, "event_score": 70},
        }),
        json.dumps({
            "event_type": "control_group_assessment",
            "details": {"market_id": "cg_market_1", "ambiguity_risk": 10, "event_score": 72, "group": "control"},
        }),
        json.dumps({
            "event_type": "control_group_assessment",
            "details": {"market_id": "cg_market_2", "ambiguity_risk": 5, "event_score": 80, "group": "control"},
        }),
    ]
    (run_dir / "events.jsonl").write_text("\n".join(events))

    return runs_dir


# =============================================================================
# RunConfig Tests
# =============================================================================


class TestRunConfigDefaults:
    def test_control_group_sampling_ratio_default_zero(self, default_run_config: RunConfig):
        assert default_run_config.control_group_sampling_ratio == 0.0

    def test_exclude_avoid_from_control_group_default_true(self, default_run_config: RunConfig):
        assert default_run_config.exclude_avoid_from_control_group is True

    def test_control_group_ratio_in_cg_config(self, cg_run_config: RunConfig):
        assert cg_run_config.control_group_sampling_ratio == 0.2

    def test_control_group_ratio_zero_no_effect(self, default_run_config: RunConfig):
        """When ratio is 0, control group should not activate."""
        assert default_run_config.control_group_sampling_ratio == 0.0
        # This ensures backward compatibility


# =============================================================================
# RunStatistics Tests
# =============================================================================


class TestRunStatisticsControlGroup:
    def test_default_control_group_stats(self):
        stats = RunStatistics(run_id="test", start_time=None)
        assert stats.control_group_samples == 0
        assert stats.control_group_unique_markets == 0
        assert stats.control_group_llm_calls == 0
        assert stats.control_group_categories == {}

    def test_to_dict_includes_control_group(self):
        from datetime import datetime
        stats = RunStatistics(run_id="test", start_time=datetime.utcnow())
        stats.control_group_samples = 5
        stats.control_group_unique_markets = 5
        d = stats.to_dict()
        assert d["control_group_samples"] == 5
        assert d["control_group_unique_markets"] == 5
        assert "control_group_llm_calls" in d
        assert "control_group_categories" in d


# =============================================================================
# ValidationDataLoader Tests (control group)
# =============================================================================


class TestValidationDataLoaderControlGroup:
    def test_load_control_group_samples(self, tmp_runs_with_cg: Path):
        from scripts.validate_strategy_signals import ValidationDataLoader
        loader = ValidationDataLoader(tmp_runs_with_cg)
        samples = loader.load_control_group_samples()
        assert len(samples) == 5

    def test_load_control_group_samples_empty(self, tmp_path: Path):
        from scripts.validate_strategy_signals import ValidationDataLoader
        loader = ValidationDataLoader(tmp_path)
        samples = loader.load_control_group_samples()
        assert samples == []

    def test_control_group_categories(self, tmp_runs_with_cg: Path):
        from scripts.validate_strategy_signals import ValidationDataLoader
        loader = ValidationDataLoader(tmp_runs_with_cg)
        samples = loader.load_control_group_samples()
        categories = {s.get("category") for s in samples}
        assert categories == {"Sports", "Crypto", "Gaming", "Politics", "Legal"}


# =============================================================================
# AvoidValidator Tests (with control group)
# =============================================================================


class TestAvoidValidatorWithControlGroup:
    def test_group_comparison_with_control_group(self, tmp_runs_with_cg: Path):
        from scripts.validate_strategy_signals import ValidationDataLoader, AvoidValidator
        loader = ValidationDataLoader(tmp_runs_with_cg)
        avoid = loader.load_avoid_candidates()
        events = loader.load_all_llm_events()
        cg_samples = loader.load_control_group_samples()

        validator = AvoidValidator()
        comparison = validator.validate_group_comparison(avoid, events, cg_samples)

        # Should have non-avoid group from control group samples
        assert comparison.non_avoid_group_size >= 2
        assert comparison.conclusion_status != "insufficient_control_group"

    def test_group_comparison_without_control_group(self, tmp_runs_with_cg: Path):
        from scripts.validate_strategy_signals import ValidationDataLoader, AvoidValidator
        loader = ValidationDataLoader(tmp_runs_with_cg)
        avoid = loader.load_avoid_candidates()
        events = loader.load_all_llm_events()

        validator = AvoidValidator()
        comparison = validator.validate_group_comparison(avoid, events)

        # Without control group, non-avoid may be small
        # (depends on events not in avoid)
        assert comparison.avoid_group_size == 1

    def test_control_group_excludes_avoid_markets(self, tmp_runs_with_cg: Path):
        """Control group samples should not include avoid market IDs."""
        from scripts.validate_strategy_signals import ValidationDataLoader
        loader = ValidationDataLoader(tmp_runs_with_cg)
        avoid = loader.load_avoid_candidates()
        cg_samples = loader.load_control_group_samples()

        avoid_ids = {str(c.get("market_id", "")) for c in avoid}
        cg_ids = {str(s.get("market_id", "")) for s in cg_samples}
        overlap = avoid_ids & cg_ids
        assert len(overlap) == 0, f"Control group overlaps with avoid: {overlap}"


# =============================================================================
# Group Comparison Conclusion Tests
# =============================================================================


class TestGroupComparisonConclusion:
    def test_sufficient_control_group_observed(self):
        from scripts.validate_strategy_signals import AvoidValidator
        validator = AvoidValidator()
        avoid = [{"market_id": "a1", "avoid_score": "70"}]
        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "a1", "ambiguity_risk": 60}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x1", "ambiguity_risk": 15}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x2", "ambiguity_risk": 10}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x3", "ambiguity_risk": 20}},
        ]
        comparison = validator.validate_group_comparison(avoid, events)
        assert comparison.conclusion_status == "observed"
        assert comparison.ambiguity_risk_delta is not None
        assert comparison.ambiguity_risk_delta > 0

    def test_insufficient_control_group_small(self):
        from scripts.validate_strategy_signals import AvoidValidator
        validator = AvoidValidator()
        avoid = [{"market_id": "a1"}, {"market_id": "a2"}]
        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "a1", "ambiguity_risk": 50}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "a2", "ambiguity_risk": 45}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x1", "ambiguity_risk": 20}},
        ]
        comparison = validator.validate_group_comparison(avoid, events)
        assert comparison.conclusion_status == "insufficient_control_group"

    def test_control_group_samples_merge(self):
        """control_group_samples should be merged into non-avoid group."""
        from scripts.validate_strategy_signals import AvoidValidator
        validator = AvoidValidator()
        avoid = [{"market_id": "a1", "avoid_score": "70"}]
        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "a1", "ambiguity_risk": 60}},
        ]
        cg_samples = [
            {"market_id": "cg1", "ambiguity_risk": "10", "event_score": "75"},
            {"market_id": "cg2", "ambiguity_risk": "15", "event_score": "70"},
            {"market_id": "cg3", "ambiguity_risk": "8", "event_score": "80"},
        ]
        comparison = validator.validate_group_comparison(avoid, events, cg_samples)
        assert comparison.non_avoid_group_size >= 3
        assert comparison.conclusion_status == "observed"


# =============================================================================
# Output File Tests
# =============================================================================


class TestControlGroupOutputFiles:
    def test_control_group_samples_csv_exists(self, tmp_runs_with_cg: Path):
        run_dir = tmp_runs_with_cg / "run_20260510_120000_abc123"
        csv_path = run_dir / "control_group_samples.csv"
        assert csv_path.exists()

    def test_control_group_samples_csv_content(self, tmp_runs_with_cg: Path):
        csv_path = tmp_runs_with_cg / "run_20260510_120000_abc123" / "control_group_samples.csv"
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 5
        assert rows[0]["market_id"] == "cg_market_1"
        assert "category" in rows[0]

    def test_validation_loop_summary_json(self, tmp_runs_with_cg: Path):
        summary_path = tmp_runs_with_cg / "run_20260510_120000_abc123" / "validation_loop_summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_text())
        assert data["phase"] == "6.5A"
        assert data["control_group_samples"] == 5
        assert data["safety_verification"]["live_trading_enabled"] is False
        assert data["safety_verification"]["trading_actions"] is False

    def test_validation_loop_summary_categories(self, tmp_runs_with_cg: Path):
        summary_path = tmp_runs_with_cg / "run_20260510_120000_abc123" / "validation_loop_summary.json"
        data = json.loads(summary_path.read_text())
        cats = data["control_group_categories"]
        assert len(cats) == 5
        assert all(cats[c] == 1 for c in cats)


# =============================================================================
# AST Safety Audit Tests
# =============================================================================


class TestASTSafetyAudit:
    """Verify new code does NOT import trading modules."""

    def _get_imported_modules(self, filepath: Path) -> list[str]:
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

    def test_validate_strategy_signals_no_trading_imports(self):
        filepath = Path(__file__).resolve().parent.parent / "scripts" / "validate_strategy_signals.py"
        modules = self._get_imported_modules(filepath)
        assert not any("live_trader" in m for m in modules)
        assert not any("paper_trader" in m for m in modules)
        assert not any("risk_governor" in m for m in modules)


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    def test_default_ratio_zero_no_behavior_change(self, default_run_config: RunConfig):
        """With default ratio=0, control group should not activate."""
        assert default_run_config.control_group_sampling_ratio == 0.0

    def test_validate_group_comparison_unchanged_without_cg(self):
        """validate_group_comparison works without control_group_samples param."""
        from scripts.validate_strategy_signals import AvoidValidator
        validator = AvoidValidator()
        avoid = [{"market_id": "a1"}]
        events = [
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "a1", "ambiguity_risk": 60}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x1", "ambiguity_risk": 15}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x2", "ambiguity_risk": 10}},
            {"event_type": "llm_sampling_assessment", "details": {"market_id": "x3", "ambiguity_risk": 20}},
        ]
        # Old signature still works
        comparison = validator.validate_group_comparison(avoid, events)
        assert comparison.conclusion_status == "observed"
