"""
Tests for Combined Ask Distribution in Summary/Report - Phase 5C Audit

Coverage:
- RunStatistics tracks combined_ask_observations
- to_dict() includes combined_ask_distribution
- _calculate_combined_ask_distribution computes correct statistics
- report.md includes combined_ask distribution section
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_paper import (
    PaperTradingRunner,
    RunConfig,
    RunStatistics,
)


class TestCombinedAskDistribution:
    """Test combined_ask distribution tracking"""

    def test_run_statistics_has_combined_ask_observations(self):
        """Test RunStatistics has combined_ask_observations field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "combined_ask_observations")
        assert stats.combined_ask_observations == []

    def test_combined_ask_distribution_in_to_dict(self):
        """Test to_dict includes combined_ask_distribution"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.combined_ask_observations = [1.01, 1.02, 1.03, 1.04, 1.05]

        result = stats.to_dict()

        assert "combined_ask_distribution" in result
        assert result["combined_ask_distribution"]["observation_count"] == 5

    def test_calculate_combined_ask_distribution_empty(self):
        """Test _calculate_combined_ask_distribution with no observations"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        result = stats._calculate_combined_ask_distribution()

        assert result["min"] is None
        assert result["max"] is None
        assert result["median"] is None
        assert result["observation_count"] == 0

    def test_calculate_combined_ask_distribution_basic(self):
        """Test _calculate_combined_ask_distribution with basic data"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.combined_ask_observations = [1.01, 1.02, 1.03, 1.04, 1.05]

        result = stats._calculate_combined_ask_distribution()

        assert result["min"] == 1.01
        assert result["max"] == 1.05
        assert result["median"] == 1.03
        assert result["observation_count"] == 5

    def test_calculate_combined_ask_distribution_percentiles(self):
        """Test _calculate_combined_ask_distribution percentiles"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        # 100 observations from 1.00 to 1.99
        stats.combined_ask_observations = [1.00 + i * 0.01 for i in range(100)]

        result = stats._calculate_combined_ask_distribution()

        assert result["min"] == 1.00
        assert result["max"] == 1.99
        # P5 should be around index 5
        assert result["p5"] >= 1.00
        assert result["p5"] <= 1.10
        # P95 should be around index 95
        assert result["p95"] >= 1.90
        assert result["p95"] <= 2.00

    def test_calculate_combined_ask_distribution_samples(self):
        """Test _calculate_combined_ask_distribution sample values"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.combined_ask_observations = [1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09, 1.10]

        result = stats._calculate_combined_ask_distribution()

        assert result["sample_lowest"] == [1.01, 1.02, 1.03, 1.04, 1.05]
        assert result["sample_highest"] == [1.06, 1.07, 1.08, 1.09, 1.10]

    def test_calculate_combined_ask_distribution_single_value(self):
        """Test _calculate_combined_ask_distribution with single value"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.combined_ask_observations = [1.05]

        result = stats._calculate_combined_ask_distribution()

        assert result["min"] == 1.05
        assert result["max"] == 1.05
        assert result["median"] == 1.05
        assert result["p5"] == 1.05
        assert result["p95"] == 1.05
        assert result["observation_count"] == 1


class TestReportIncludesCombinedAsk:
    """Test that report.md includes combined_ask distribution"""

    def test_generate_markdown_report_includes_combined_ask(self):
        """Test _generate_markdown_report includes combined_ask section"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.combined_ask_observations = [1.01, 1.02, 1.03, 1.04, 1.05]

        report = runner._generate_markdown_report()

        assert "Combined Ask Distribution" in report
        assert "Observations" in report

    def test_generate_markdown_report_empty_observations(self):
        """Test _generate_markdown_report handles empty observations"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        report = runner._generate_markdown_report()

        # Should not include combined_ask section when no observations
        assert "Combined Ask Distribution" not in report


class TestSummaryJsonIncludesCombinedAsk:
    """Test that summary.json includes combined_ask distribution"""

    def test_summary_json_structure(self):
        """Test summary.json has correct structure"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.combined_ask_observations = [1.01, 1.02, 1.03]

        result = stats.to_dict()

        assert "combined_ask_distribution" in result
        dist = result["combined_ask_distribution"]
        assert "min" in dist
        assert "max" in dist
        assert "median" in dist
        assert "p5" in dist
        assert "p95" in dist
        assert "sample_lowest" in dist
        assert "sample_highest" in dist
        assert "observation_count" in dist


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
