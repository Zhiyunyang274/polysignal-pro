"""
Tests for Configuration Loading
"""

import pytest
from pathlib import Path

from polysignal.config import Config, AppSettings, RiskSettings


class TestConfig:
    """Test configuration loading"""

    def test_default_risk_settings(self):
        """Test default risk settings"""
        risk = RiskSettings()

        # CRITICAL: These must be False by default
        assert risk.live_trading_enabled is False
        assert risk.allow_auto_execution is False
        assert risk.paper_trading_enabled is True

    def test_default_app_settings(self):
        """Test default app settings"""
        app = AppSettings()

        assert app.app.name == "PolySignal Pro"
        assert app.data_mode == "mock"

    def test_config_loads_yaml(self):
        """Test that config loads from YAML files"""
        config = Config(config_dir="config")

        # Should load from YAML
        assert config.risk.live_trading_enabled is False
        assert config.app.data_mode == "mock"

    def test_config_summary(self):
        """Test config summary generation"""
        config = Config(config_dir="config")
        summary = config.get_summary()

        assert "app" in summary
        assert "risk" in summary
        assert summary["risk"]["live_trading_enabled"] is False

    def test_is_live_trading_enabled(self):
        """Test live trading check"""
        config = Config(config_dir="config")

        # Should be False by default
        assert config.is_live_trading_enabled() is False

    def test_is_telegram_enabled_without_config(self):
        """Test Telegram check without config"""
        config = Config(config_dir="config")

        # Should be False without token
        assert config.is_telegram_enabled() is False

    def test_risk_thresholds(self):
        """Test risk thresholds"""
        risk = RiskSettings()

        assert risk.thresholds.ignore == 70
        assert risk.thresholds.log_only == 80
        assert risk.thresholds.alert == 90
        assert risk.thresholds.manual_review == 95

    def test_scoring_weights(self):
        """Test scoring weights sum to 1.0"""
        risk = RiskSettings()
        weights = risk.scoring_weights

        total = (
            weights.microstructure
            + weights.liquidity
            + weights.event
            + weights.wallet
            + weights.lifecycle
        )

        assert abs(total - 1.0) < 0.01  # Should sum to 1.0

    def test_forbidden_categories(self):
        """Test forbidden categories"""
        risk = RiskSettings()

        assert "politics" in risk.forbidden_auto_categories
        assert "war_geopolitics" in risk.forbidden_auto_categories
        assert "legal" in risk.forbidden_auto_categories
        assert "celebrity" in risk.forbidden_auto_categories
        assert "subjective" in risk.forbidden_auto_categories
