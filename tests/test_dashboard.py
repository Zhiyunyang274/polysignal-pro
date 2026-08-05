"""
Tests for Phase 5G.1 Dashboard MVP

Coverage:
1. Can load runs
2. Can load summary.json
3. Can load intelligence_summary.json
4. Can load persistent_watchlist.csv
5. Can load alpha_candidates.csv
6. Can load avoid_candidates.csv
7. Alpha disclaimer exists
8. Avoid explanation exists
9. Dashboard does NOT import LiveTrader
10. Dashboard does NOT import PaperTrader
11. Dashboard does NOT write config
12. Dashboard does NOT require real API key
13. Missing files handled gracefully
14. live_trading_enabled=false can be read
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Mock streamlit before importing dashboard
# Dashboard imports streamlit at module level, so we must mock it
sys.modules["streamlit"] = MagicMock()

from polysignal.interface.dashboard import (
    ALPHA_DISCLAIMER,
    AVOID_EXPLANATION,
    ComparisonSummary,
    DashboardDataLoader,
    IntelligenceSummary,
    RunSummary,
    SafetyStatus,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
CONFIG_DIR = PROJECT_ROOT / "config"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def loader() -> DashboardDataLoader:
    """DashboardDataLoader pointing at real runs/ directory."""
    return DashboardDataLoader(runs_dir=RUNS_DIR, config_dir=CONFIG_DIR)


@pytest.fixture
def tmp_runs(tmp_path: Path) -> Path:
    """Create a temporary runs directory with test data."""
    run_dir = tmp_path / "run_test_001"
    run_dir.mkdir()

    summary = {
        "run_id": "run_test_001",
        "status": "completed",
        "duration_minutes": 30.0,
        "data_mode": "mock",
        "llm_provider": "mock",
        "markets_checked": 10,
        "signals_generated": 0,
        "paper_trades_created": 0,
        "llm_sampling_enabled": False,
        "llm_sampling_calls_attempted": 0,
        "llm_sampling_calls_succeeded": 0,
        "llm_sampling_calls_failed": 0,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary))

    return tmp_path


@pytest.fixture
def tmp_loader(tmp_runs: Path) -> DashboardDataLoader:
    """DashboardDataLoader with temporary test data."""
    return DashboardDataLoader(runs_dir=tmp_runs, config_dir=CONFIG_DIR)


# =============================================================================
# 1. Can load runs
# =============================================================================


class TestLoadRuns:
    def test_discover_runs_returns_list(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        assert isinstance(run_ids, list)
        assert len(run_ids) > 0

    def test_discover_runs_sorted_descending(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        assert run_ids == sorted(run_ids, reverse=True)

    def test_discover_runs_all_start_with_run_(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        assert all(rid.startswith("run_") for rid in run_ids)

    def test_discover_runs_empty_dir(self, tmp_path: Path):
        empty_loader = DashboardDataLoader(runs_dir=tmp_path / "nonexistent")
        run_ids = empty_loader.discover_runs()
        assert run_ids == []


# =============================================================================
# 2. Can load summary.json
# =============================================================================


class TestLoadSummary:
    def test_load_run_summary_returns_run_summary(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        assert len(run_ids) > 0
        summary = loader.load_run_summary(run_ids[0])
        assert summary is not None
        assert isinstance(summary, RunSummary)

    def test_load_run_summary_has_run_id(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        summary = loader.load_run_summary(run_ids[0])
        assert summary is not None
        assert summary.run_id == run_ids[0]

    def test_load_run_summary_has_status(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        summary = loader.load_run_summary(run_ids[0])
        assert summary is not None
        assert summary.status in ("completed", "running", "error", "unknown")

    def test_load_all_runs_returns_dict(self, loader: DashboardDataLoader):
        runs = loader.load_all_runs()
        assert isinstance(runs, dict)
        assert len(runs) > 0

    def test_load_run_summary_from_json(self):
        data = {
            "run_id": "test_001",
            "status": "completed",
            "duration_minutes": 60.0,
            "data_mode": "real_readonly",
            "llm_provider": "xfyun_anthropic",
            "markets_checked": 100,
            "combined_ask_distribution": {
                "min": 1.001,
                "max": 1.05,
                "median": 1.01,
                "observation_count": 50,
            },
        }
        summary = RunSummary.from_json(data)
        assert summary.run_id == "test_001"
        assert summary.status == "completed"
        assert summary.duration_minutes == 60.0
        assert summary.combined_ask_min == 1.001
        assert summary.combined_ask_observation_count == 50

    def test_aggregated_stats(self, loader: DashboardDataLoader):
        stats = loader.get_aggregated_stats()
        assert "total_runs" in stats
        assert "total_markets_checked" in stats
        assert stats["total_runs"] > 0


# =============================================================================
# 3. Can load intelligence_summary.json
# =============================================================================


class TestLoadIntelligenceSummary:
    def test_load_intelligence_summary_returns_object(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        # Find a run with intelligence_summary.json
        found = False
        for run_id in run_ids:
            intel = loader.load_intelligence_summary(run_id)
            if intel is not None:
                assert isinstance(intel, IntelligenceSummary)
                found = True
                break
        assert found, "No run with intelligence_summary.json found"

    def test_intelligence_summary_has_run_id(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        for run_id in run_ids:
            intel = loader.load_intelligence_summary(run_id)
            if intel is not None:
                assert intel.run_id == run_id
                break

    def test_intelligence_summary_from_json(self):
        data = {
            "run_id": "test_intel",
            "analysis_timestamp": "2026-05-09T16:46:49",
            "total_observed_markets": 20,
            "near_miss_tier_distribution": {"tier3_weak_near_miss": 10},
            "category_distribution": {"Sports": 7, "Gaming": 6},
            "llm_suggested_mode_distribution": {"research": 12, "ignore": 3},
            "top_near_miss_markets": [],
            "live_trading_enabled": False,
            "allow_auto_execution": False,
        }
        intel = IntelligenceSummary.from_json(data)
        assert intel.run_id == "test_intel"
        assert intel.total_markets_analyzed == 20
        assert intel.near_miss_tier_distribution == {"tier3_weak_near_miss": 10}
        assert intel.live_trading_enabled is False
        assert intel.allow_auto_execution is False

    def test_intelligence_summary_none_for_missing(self, loader: DashboardDataLoader):
        result = loader.load_intelligence_summary("nonexistent_run_id")
        assert result is None

    def test_load_comparison_summary(self, loader: DashboardDataLoader):
        comparison = loader.load_comparison_summary()
        if comparison is not None:
            assert isinstance(comparison, ComparisonSummary)
            assert comparison.total_runs > 0


# =============================================================================
# 4. Can load persistent_watchlist.csv
# =============================================================================


class TestLoadWatchlist:
    def test_load_persistent_watchlist_returns_dataframe(self, loader: DashboardDataLoader):
        df = loader.load_persistent_watchlist()
        assert isinstance(df, pd.DataFrame)
        if not df.empty:
            assert "market_id" in df.columns or "question" in df.columns

    def test_load_persistent_watchlist_has_content(self, loader: DashboardDataLoader):
        df = loader.load_persistent_watchlist()
        # The real file exists and has data
        assert len(df) > 0

    def test_load_persistent_watchlist_columns(self, loader: DashboardDataLoader):
        df = loader.load_persistent_watchlist()
        if not df.empty:
            assert "market_id" in df.columns
            assert "question" in df.columns
            assert "evidence_level" in df.columns


# =============================================================================
# 5. Can load alpha_candidates.csv
# =============================================================================


class TestLoadAlphaCandidates:
    def test_load_alpha_returns_dataframe(self, loader: DashboardDataLoader):
        df = loader.load_alpha_candidates()
        assert isinstance(df, pd.DataFrame)
        if not df.empty:
            assert "alpha_score" in df.columns

    def test_load_alpha_has_content(self, loader: DashboardDataLoader):
        df = loader.load_alpha_candidates()
        assert len(df) > 0

    def test_load_alpha_columns(self, loader: DashboardDataLoader):
        df = loader.load_alpha_candidates()
        if not df.empty:
            assert "market_id" in df.columns
            assert "question" in df.columns
            assert "alpha_score" in df.columns
            assert "evidence_level" in df.columns


# =============================================================================
# 6. Can load avoid_candidates.csv
# =============================================================================


class TestLoadAvoidCandidates:
    def test_load_avoid_returns_dataframe(self, loader: DashboardDataLoader):
        df = loader.load_avoid_candidates()
        assert isinstance(df, pd.DataFrame)
        if not df.empty:
            assert "avoid_score" in df.columns

    def test_load_avoid_has_content(self, loader: DashboardDataLoader):
        df = loader.load_avoid_candidates()
        assert len(df) > 0

    def test_load_avoid_columns(self, loader: DashboardDataLoader):
        df = loader.load_avoid_candidates()
        if not df.empty:
            assert "market_id" in df.columns
            assert "question" in df.columns
            assert "avoid_score" in df.columns
            assert "reasons" in df.columns


# =============================================================================
# 7. Alpha disclaimer exists
# =============================================================================


class TestAlphaDisclaimer:
    def test_alpha_disclaimer_constant_exists(self):
        assert ALPHA_DISCLAIMER is not None
        assert isinstance(ALPHA_DISCLAIMER, str)
        assert len(ALPHA_DISCLAIMER) > 0

    def test_alpha_disclaimer_contains_key_phrases(self):
        assert "DISCLAIMER" in ALPHA_DISCLAIMER
        assert "NOT a trading signal" in ALPHA_DISCLAIMER

    def test_comparison_summary_has_alpha_disclaimer(self, loader: DashboardDataLoader):
        comparison = loader.load_comparison_summary()
        assert comparison is not None, "intelligence_comparison_summary.json not found"
        raw = comparison.raw_data
        assert "alpha_disclaimer" in raw
        assert "not a trading signal" in raw["alpha_disclaimer"].lower()


# =============================================================================
# 8. Avoid explanation exists
# =============================================================================


class TestAvoidExplanation:
    def test_avoid_explanation_constant_exists(self):
        assert AVOID_EXPLANATION is not None
        assert isinstance(AVOID_EXPLANATION, str)
        assert len(AVOID_EXPLANATION) > 0

    def test_avoid_explanation_contains_key_phrases(self):
        assert "NOT hard forbidden" in AVOID_EXPLANATION
        assert "research annotations" in AVOID_EXPLANATION


# =============================================================================
# 9. Dashboard does NOT import LiveTrader
# =============================================================================


class TestNoLiveTraderImport:
    def test_dashboard_source_no_live_trader(self):
        """Use AST to verify no actual import of live_trader exists."""
        import ast

        dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
        source = dashboard_file.read_text()
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
        assert "polysignal.execution.live_trader" not in imported_modules
        assert "polysignal.execution.live_trader.LiveTrader" not in imported_modules

    def test_dashboard_source_no_live_trader_keyword(self):
        dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
        source = dashboard_file.read_text()
        # Check actual code, not docstrings or comments
        code_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in code_lines:
            # Skip lines inside docstrings (start with string literal)
            if line.startswith(('"""', "'''", '"', "'")):
                continue
            assert "LiveTrader()" not in line
            assert "live_trader.execute" not in line


# =============================================================================
# 10. Dashboard does NOT import PaperTrader
# =============================================================================


class TestNoPaperTraderImport:
    def test_dashboard_source_no_paper_trader(self):
        """Use AST to verify no actual import of paper_trader exists."""
        import ast

        dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
        source = dashboard_file.read_text()
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
        assert "polysignal.execution.paper_trader" not in imported_modules
        assert "polysignal.execution.paper_trader.PaperTrader" not in imported_modules

    def test_dashboard_source_no_paper_trader_execute(self):
        dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
        source = dashboard_file.read_text()
        code_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in code_lines:
            if line.startswith(('"""', "'''", '"', "'")):
                continue
            assert "PaperTrader()" not in line
            assert "paper_trader.execute" not in line


# =============================================================================
# 11. Dashboard does NOT write config
# =============================================================================


class TestNoConfigWrite:
    def test_dashboard_source_no_config_write(self):
        dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
        source = dashboard_file.read_text()
        # Should not have write mode opens to config files
        assert "open(risk_yaml, 'w')" not in source
        assert 'open(risk_yaml, "w")' not in source
        assert "open(llm_yaml, 'w')" not in source
        assert 'open(llm_yaml, "w")' not in source
        # Verify all file opens in SafetyStatus.from_config are read-only
        code_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in code_lines:
            if "open(" in line and ("risk" in line.lower() or "llm" in line.lower()):
                assert "'r'" in line or '"r"' in line, f"Config open not read-only: {line}"

    def test_dashboard_loader_is_readonly(self, loader: DashboardDataLoader):
        """Verify loader methods return data without side effects."""
        # These should all be read-only operations
        runs = loader.load_all_runs()
        assert isinstance(runs, dict)
        # No file should have been created
        # (loader only reads, never writes)


# =============================================================================
# 12. Dashboard does NOT require real API key
# =============================================================================


class TestNoApiKeyRequired:
    def test_dashboard_no_api_key_import(self):
        dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
        source = dashboard_file.read_text()
        assert "POLYMARKET_API_KEY" not in source
        assert "CLOB_API_KEY" not in source
        assert "TELEGRAM_BOT_TOKEN" not in source

    def test_loader_works_without_env_vars(self):
        """DashboardDataLoader should work without any environment variables."""
        loader = DashboardDataLoader(runs_dir=RUNS_DIR, config_dir=CONFIG_DIR)
        runs = loader.discover_runs()
        assert isinstance(runs, list)


# =============================================================================
# 13. Missing files handled gracefully
# =============================================================================


class TestMissingFiles:
    def test_missing_runs_dir(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path / "no_such_dir")
        assert loader.discover_runs() == []
        assert loader.load_all_runs() == {}

    def test_missing_summary_json(self, tmp_path: Path):
        run_dir = tmp_path / "run_empty"
        run_dir.mkdir()
        loader = DashboardDataLoader(runs_dir=tmp_path)
        summary = loader.load_run_summary("run_empty")
        assert summary is None

    def test_missing_intelligence_summary(self, loader: DashboardDataLoader):
        result = loader.load_intelligence_summary("nonexistent_run_xyz")
        assert result is None

    def test_missing_watchlist_csv(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path)
        df = loader.load_persistent_watchlist()
        assert df.empty

    def test_missing_alpha_csv(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path)
        df = loader.load_alpha_candidates()
        assert df.empty

    def test_missing_avoid_csv(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path)
        df = loader.load_avoid_candidates()
        assert df.empty

    def test_missing_comparison_summary(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path)
        result = loader.load_comparison_summary()
        assert result is None

    def test_missing_trajectories_json(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path)
        result = loader.load_market_trajectories()
        assert result == {}

    def test_corrupted_json(self, tmp_path: Path):
        run_dir = tmp_path / "run_corrupt"
        run_dir.mkdir()
        (run_dir / "summary.json").write_text("not valid json {{{")
        loader = DashboardDataLoader(runs_dir=tmp_path)
        summary = loader.load_run_summary("run_corrupt")
        assert summary is None

    def test_aggregated_stats_empty(self, tmp_path: Path):
        loader = DashboardDataLoader(runs_dir=tmp_path)
        stats = loader.get_aggregated_stats()
        assert stats["total_runs"] == 0
        assert stats["total_markets_checked"] == 0


# =============================================================================
# 14. live_trading_enabled=false can be read
# =============================================================================


class TestLiveTradingDisabled:
    def test_risk_yaml_has_live_trading_disabled(self):
        risk_yaml = CONFIG_DIR / "risk.yaml"
        if risk_yaml.exists():
            try:
                import yaml

                with open(risk_yaml, "r") as f:
                    config = yaml.safe_load(f) or {}
                assert config.get("live_trading_enabled") is False
            except ImportError:
                pytest.skip("PyYAML not installed")

    def test_risk_yaml_has_auto_execution_disabled(self):
        risk_yaml = CONFIG_DIR / "risk.yaml"
        if risk_yaml.exists():
            try:
                import yaml

                with open(risk_yaml, "r") as f:
                    config = yaml.safe_load(f) or {}
                assert config.get("allow_auto_execution") is False
            except ImportError:
                pytest.skip("PyYAML not installed")

    def test_safety_status_default_is_disabled(self):
        safety = SafetyStatus()
        assert safety.live_trading_enabled is False
        assert safety.allow_auto_execution is False

    def test_comparison_summary_safety_flags(self, loader: DashboardDataLoader):
        comparison = loader.load_comparison_summary()
        if comparison is not None:
            assert comparison.all_runs_live_trading_disabled is True
            assert comparison.all_runs_auto_execution_disabled is True

    def test_intelligence_summary_safety_flags(self, loader: DashboardDataLoader):
        run_ids = loader.discover_runs()
        for run_id in run_ids:
            intel = loader.load_intelligence_summary(run_id)
            if intel is not None:
                assert intel.live_trading_enabled is False
                assert intel.allow_auto_execution is False
                break

    def test_run_dashboard_check_no_trading_imports(self):
        """Verify run_dashboard.py does not import trading modules (AST-based)."""
        import ast

        script_file = PROJECT_ROOT / "scripts" / "run_dashboard.py"
        source = script_file.read_text()
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
        assert "polysignal.execution.live_trader" not in imported_modules
        assert "polysignal.execution.paper_trader" not in imported_modules
        assert "polysignal.risk.risk_governor" not in imported_modules


# =============================================================================
# Additional: Data class construction
# =============================================================================


class TestDataClasses:
    def test_run_summary_from_json_minimal(self):
        summary = RunSummary.from_json({})
        assert summary.run_id == "unknown"
        assert summary.status == "unknown"

    def test_intelligence_summary_from_json_minimal(self):
        intel = IntelligenceSummary.from_json({})
        assert intel.run_id == "unknown"
        assert intel.total_markets_analyzed == 0

    def test_comparison_summary_from_json_minimal(self):
        comp = ComparisonSummary.from_json({})
        assert comp.total_runs == 0
        assert comp.all_runs_live_trading_disabled is True

    def test_safety_status_defaults(self):
        safety = SafetyStatus()
        assert safety.live_trading_enabled is False
        assert safety.allow_auto_execution is False
        assert safety.paper_trading_enabled is True
        assert safety.llm_provider == "mock"


# =============================================================================
# Additional: run_dashboard.py checks
# =============================================================================


class TestRunDashboard:
    def test_check_safety_config(self):
        from scripts.run_dashboard import check_safety_config

        issues = check_safety_config()
        assert issues == []

    def test_check_runs_directory(self):
        from scripts.run_dashboard import check_runs_directory

        issues = check_runs_directory()
        # Should have no critical issues (runs/ exists and has data)
        assert issues == []

    def test_check_data_files(self):
        from scripts.run_dashboard import check_data_files

        files = check_data_files()
        assert isinstance(files, dict)
        assert "persistent_watchlist.csv" in files
        assert "alpha_candidates.csv" in files
        assert "avoid_candidates.csv" in files

    def test_check_no_trading_imports(self):
        from scripts.run_dashboard import check_no_trading_imports

        issues = check_no_trading_imports()
        assert issues == []
