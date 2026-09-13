"""
Tests for Paper Trading Runner - Phase 5A

Coverage:
- Runner initialization
- Safety checks
- Conservative default config
- Run ID generation
- Report file creation
- Rate limits
- LLM call limit
- Telegram disabled by default
- Graceful shutdown
- API fallback
- No live trading path
- No private key requirement
"""

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_paper import (
    PaperTradingRunner,
    RunConfig,
    RunStatistics,
    parse_args,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """Create mock config with safe defaults"""
    config = MagicMock()
    config.env = MagicMock()
    config.env.live_trading_enabled = False
    config.env.allow_auto_execution = False
    config.env.paper_trading_enabled = True
    return config


@pytest.fixture
def conservative_run_config():
    """Create conservative run config"""
    return RunConfig(
        duration_minutes=30,
        duration_hours=0.5,
        max_markets=10,
        scan_interval_seconds=120,
        data_mode="hybrid",
        use_websocket=True,
        llm_provider="mock",
        max_llm_calls_per_hour=0,
        max_signals_per_hour=20,
        telegram_enabled=False,
        max_telegram_messages_per_hour=0,
    )


@pytest.fixture
def temp_db_path(tmp_path):
    """Create temporary database path"""
    return str(tmp_path / "test_polysignal.db")


# =============================================================================
# Test Runner Initialization
# =============================================================================

class TestRunnerInitialization:
    """Test runner initialization"""

    def test_runner_init_basic(self, mock_config, conservative_run_config):
        """Test basic runner initialization"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        assert runner.config == mock_config
        assert runner.run_config == conservative_run_config
        assert runner.stats is None
        assert runner.db is None
        assert runner.run_dir is None
        assert runner._shutdown_requested is False
        assert runner._scan_count == 0

    def test_runner_init_with_different_configs(self, mock_config):
        """Test runner with different config values"""
        run_config = RunConfig(
            duration_minutes=60,
            duration_hours=1.0,
            max_markets=20,
            scan_interval_seconds=60,
            data_mode="real_readonly",
            use_websocket=False,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            max_signals_per_hour=30,
            telegram_enabled=True,
            max_telegram_messages_per_hour=5,
        )

        runner = PaperTradingRunner(mock_config, run_config)

        assert runner.run_config.duration_minutes == 60
        assert runner.run_config.max_markets == 20
        assert runner.run_config.llm_provider == "xfyun_anthropic"
        assert runner.run_config.max_llm_calls_per_hour == 10
        assert runner.run_config.telegram_enabled is True


# =============================================================================
# Test Safety Checks
# =============================================================================

class TestSafetyChecks:
    """Test safety checks"""

    def test_safety_checks_pass(self, mock_config, conservative_run_config, capsys):
        """Test safety checks pass with safe config"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        result = runner._safety_checks()

        assert result is True

        captured = capsys.readouterr()
        assert "live_trading_enabled: false" in captured.out
        assert "allow_auto_execution: false" in captured.out
        assert "paper_trading_enabled: true" in captured.out

    def test_safety_checks_fail_live_trading(self, mock_config, conservative_run_config, capsys):
        """Test safety checks fail when live_trading_enabled is True"""
        mock_config.env.live_trading_enabled = True
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        result = runner._safety_checks()

        assert result is False

        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "live_trading_enabled must be false" in captured.out

    def test_safety_checks_fail_auto_execution(self, mock_config, conservative_run_config, capsys):
        """Test safety checks fail when allow_auto_execution is True"""
        mock_config.env.allow_auto_execution = True
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        result = runner._safety_checks()

        assert result is False

        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "allow_auto_execution must be false" in captured.out

    def test_safety_checks_fail_paper_trading_disabled(self, mock_config, conservative_run_config, capsys):
        """Test safety checks fail when paper_trading_enabled is False"""
        mock_config.env.paper_trading_enabled = False
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        result = runner._safety_checks()

        assert result is False

        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "paper_trading_enabled must be true" in captured.out

    def test_safety_checks_fail_real_llm_without_limit(self, mock_config, capsys):
        """Test safety checks fail when real LLM is used without call limit"""
        run_config = RunConfig(
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=0,  # No limit set
        )
        runner = PaperTradingRunner(mock_config, run_config)
        result = runner._safety_checks()

        assert result is False

        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "requires --max_llm_calls_per_hour > 0" in captured.out

    def test_safety_checks_pass_real_llm_with_limit(self, mock_config, capsys):
        """Test safety checks pass when real LLM has call limit"""
        run_config = RunConfig(
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )
        runner = PaperTradingRunner(mock_config, run_config)
        result = runner._safety_checks()

        assert result is True

        captured = capsys.readouterr()
        assert "LLM provider: xfyun_anthropic" in captured.out
        assert "max 10 calls/hour" in captured.out


# =============================================================================
# Test Conservative Default Config
# =============================================================================

class TestConservativeDefaultConfig:
    """Test conservative default configuration"""

    def test_run_config_defaults(self):
        """Test RunConfig has conservative defaults"""
        config = RunConfig()

        assert config.duration_minutes == 30
        assert config.duration_hours == 0.5
        assert config.max_markets == 10
        assert config.scan_interval_seconds == 120
        assert config.data_mode == "hybrid"
        assert config.use_websocket is True
        assert config.llm_provider == "mock"
        assert config.max_llm_calls_per_hour == 0
        assert config.max_signals_per_hour == 20
        assert config.telegram_enabled is False
        assert config.max_telegram_messages_per_hour == 0

    def test_run_statistics_defaults(self):
        """Test RunStatistics has safe defaults"""
        stats = RunStatistics(run_id="test_run", start_time=datetime.now(UTC))

        assert stats.status == "running"
        assert stats.end_time is None
        assert stats.markets_checked == 0
        assert stats.signals_generated == 0
        assert stats.paper_trades_created == 0
        assert stats.llm_calls == 0
        assert stats.telegram_messages_sent == 0
        assert stats.simulated_pnl_usd == 0.0
        # duration_minutes and duration_hours are set dynamically, not in __init__

    def test_cli_args_defaults(self):
        """Test CLI argument defaults are conservative"""
        with patch("sys.argv", ["run_paper.py"]):
            args = parse_args()

            assert args.duration_minutes == 30
            assert args.max_markets == 10
            assert args.scan_interval_seconds == 120
            assert args.data_mode == "hybrid"
            assert args.llm_provider == "mock"
            assert args.max_llm_calls_per_hour == 0
            assert args.max_signals_per_hour == 20
            assert args.telegram_enabled is False
            assert args.max_telegram_messages_per_hour == 0


# =============================================================================
# Test Run ID Generation
# =============================================================================

class TestRunIDGeneration:
    """Test run ID generation"""

    def test_generate_run_id_format(self, mock_config, conservative_run_config):
        """Test run ID format"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        run_id = runner._generate_run_id()

        assert run_id.startswith("run_")
        assert len(run_id) > 10  # Should have timestamp and UUID

        # Check format: run_YYYYMMDD_HHMMSS_XXXXXXXX
        parts = run_id.split("_")
        assert len(parts) == 4
        assert parts[0] == "run"
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS
        assert len(parts[3]) == 8  # UUID

    def test_generate_run_id_unique(self, mock_config, conservative_run_config):
        """Test run IDs are unique"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        run_ids = [runner._generate_run_id() for _ in range(100)]
        unique_ids = set(run_ids)

        assert len(unique_ids) == 100  # All unique


# =============================================================================
# Test Report File Creation
# =============================================================================

class TestReportFileCreation:
    """Test report file creation"""

    @pytest.mark.asyncio
    async def test_report_files_created(self, mock_config, conservative_run_config, tmp_path):
        """Test that report files are created"""
        # Use temp directory for runs
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            runner = PaperTradingRunner(mock_config, conservative_run_config)

            # Mock database
            runner.db = MagicMock()
            runner.db._db = MagicMock()
            runner.db._db.execute = AsyncMock()
            runner.db._db.commit = AsyncMock()
            runner.db.close = AsyncMock()

            # Initialize stats
            runner.stats = RunStatistics(
                run_id="test_run_001",
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                status="completed",
            )
            # Set duration fields dynamically
            runner.stats.duration_minutes = 30
            runner.stats.duration_hours = 0.5

            # Create run directory
            runner.run_dir = tmp_path / "runs" / runner.stats.run_id
            runner.run_dir.mkdir(parents=True, exist_ok=True)

            # Create events file
            runner.events_file = open(runner.run_dir / "events.jsonl", "w")

            # Generate reports
            runner._generate_reports()

            # Check files exist
            assert (runner.run_dir / "summary.json").exists()
            assert (runner.run_dir / "report.md").exists()
            assert (runner.run_dir / "events.jsonl").exists()

            # Check summary.json content
            with open(runner.run_dir / "summary.json") as f:
                summary = json.load(f)
                assert summary["run_id"] == "test_run_001"
                assert summary["status"] == "completed"

            # Check report.md content
            with open(runner.run_dir / "report.md") as f:
                content = f.read()
                assert "# Paper Trading Run Report" in content
                assert "test_run_001" in content
                assert "Safety Verification" in content

        finally:
            if runner.events_file:
                runner.events_file.close()
            os.chdir(original_cwd)

    def test_markdown_report_content(self, mock_config, conservative_run_config):
        """Test markdown report content"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        runner.stats = RunStatistics(
            run_id="test_run_002",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(minutes=30),
            status="completed",
            markets_checked=50,
            signals_generated=10,
            signals_paper_trade=3,
        )
        # Set duration fields dynamically
        runner.stats.duration_minutes = 30
        runner.stats.duration_hours = 0.5

        report = runner._generate_markdown_report()

        assert "test_run_002" in report
        assert "completed" in report
        assert "Markets Checked" in report
        assert "50" in report
        assert "Safety Verification" in report
        assert "live_trading_enabled: false" in report


# =============================================================================
# Test Rate Limits
# =============================================================================

class TestRateLimits:
    """Test rate limiting"""

    def test_hourly_limit_reset(self, mock_config, conservative_run_config):
        """Test hourly rate limit reset"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            hour_start=datetime.now(UTC) - timedelta(hours=1),
            llm_calls_this_hour=10,
            signals_this_hour=20,
            telegram_messages_this_hour=5,
        )

        runner._check_hourly_limits()

        assert runner.stats.llm_calls_this_hour == 0
        assert runner.stats.signals_this_hour == 0
        assert runner.stats.telegram_messages_this_hour == 0

    def test_hourly_limit_not_reset_within_hour(self, mock_config, conservative_run_config):
        """Test rate limits not reset within the hour"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            hour_start=datetime.now(UTC) - timedelta(minutes=30),
            llm_calls_this_hour=10,
            signals_this_hour=20,
            telegram_messages_this_hour=5,
        )

        runner._check_hourly_limits()

        assert runner.stats.llm_calls_this_hour == 10
        assert runner.stats.signals_this_hour == 20
        assert runner.stats.telegram_messages_this_hour == 5

    def test_signal_rate_limit_respected(self, mock_config):
        """Test signal rate limit is respected"""
        run_config = RunConfig(max_signals_per_hour=5)
        runner = PaperTradingRunner(mock_config, run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            signals_this_hour=5,  # At limit
        )

        # Should not generate more signals
        can_generate = runner.stats.signals_this_hour < run_config.max_signals_per_hour
        assert can_generate is False


# =============================================================================
# Test LLM Call Limit
# =============================================================================

class TestLLMCallLimit:
    """Test LLM call limiting"""

    def test_llm_disabled_by_default(self):
        """Test LLM is disabled by default"""
        config = RunConfig()
        assert config.llm_provider == "mock"
        assert config.max_llm_calls_per_hour == 0

    def test_real_llm_requires_explicit_limit(self, mock_config, capsys):
        """Test real LLM requires explicit limit"""
        run_config = RunConfig(
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=0,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        result = runner._safety_checks()

        assert result is False
        captured = capsys.readouterr()
        assert "requires --max_llm_calls_per_hour > 0" in captured.out

    def test_real_llm_with_limit_passes(self, mock_config, capsys):
        """Test real LLM with limit passes safety checks"""
        run_config = RunConfig(
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        result = runner._safety_checks()

        assert result is True
        captured = capsys.readouterr()
        assert "max 10 calls/hour" in captured.out


# =============================================================================
# Test Telegram Disabled by Default
# =============================================================================

class TestTelegramDisabled:
    """Test Telegram is disabled by default"""

    def test_telegram_disabled_in_defaults(self):
        """Test Telegram is disabled in default config"""
        config = RunConfig()
        assert config.telegram_enabled is False
        assert config.max_telegram_messages_per_hour == 0

    def test_telegram_disabled_in_cli_defaults(self):
        """Test Telegram is disabled in CLI defaults"""
        with patch("sys.argv", ["run_paper.py"]):
            args = parse_args()
            assert args.telegram_enabled is False

    def test_telegram_can_be_enabled(self):
        """Test Telegram can be enabled with explicit flag"""
        with patch("sys.argv", ["run_paper.py", "--telegram_enabled", "true"]):
            args = parse_args()
            assert args.telegram_enabled is True


# =============================================================================
# Test Graceful Shutdown
# =============================================================================

class TestGracefulShutdown:
    """Test graceful shutdown"""

    def test_signal_handler_sets_flag(self, mock_config, conservative_run_config):
        """Test signal handler sets shutdown flag"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        assert runner._shutdown_requested is False

        # Simulate signal
        runner._signal_handler(15, None)  # SIGTERM

        assert runner._shutdown_requested is True

    @pytest.mark.asyncio
    async def test_run_loop_respects_shutdown(self, mock_config, conservative_run_config):
        """Test run loop respects shutdown flag"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        # Initialize stats
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
        )
        runner.stats.duration_minutes = 30

        # Set shutdown flag immediately
        runner._shutdown_requested = True

        # Run loop should exit immediately
        await runner._run_loop()

        assert runner.stats.status == "shutdown"

    def test_setup_signal_handlers(self, mock_config, conservative_run_config):
        """Test signal handlers are set up"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        runner._setup_signal_handlers()

        # Handlers should be set (we can't easily test they work without signals)
        # Just verify no exception is raised
        assert True


# =============================================================================
# Test API Fallback
# =============================================================================

class TestAPIFallback:
    """Test API fallback behavior"""

    def test_hybrid_mode_supports_fallback(self):
        """Test hybrid mode supports fallback"""
        config = RunConfig(data_mode="hybrid")
        assert config.data_mode == "hybrid"

    def test_mock_mode_no_real_api(self):
        """Test mock mode doesn't use real API"""
        config = RunConfig(data_mode="mock")
        assert config.data_mode == "mock"

    def test_real_readonly_mode(self):
        """Test real_readonly mode"""
        config = RunConfig(data_mode="real_readonly")
        assert config.data_mode == "real_readonly"

    def test_statistics_track_api_fallbacks(self):
        """Test statistics track API fallbacks"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            api_fallbacks=5,
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        data = stats.to_dict()
        assert data["api_fallbacks"] == 5


# =============================================================================
# Test No Live Trading Path
# =============================================================================

class TestNoLiveTradingPath:
    """Test there is no live trading path"""

    def test_safety_checks_reject_live_trading(self, mock_config, conservative_run_config):
        """Test safety checks reject live trading config"""
        mock_config.env.live_trading_enabled = True
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        result = runner._safety_checks()

        assert result is False

    def test_safety_checks_reject_auto_execution(self, mock_config, conservative_run_config):
        """Test safety checks reject auto execution"""
        mock_config.env.allow_auto_execution = True
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        result = runner._safety_checks()

        assert result is False

    def test_report_verifies_no_live_trading(self, mock_config, conservative_run_config):
        """Test report verifies no live trading"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
        )
        runner.stats.duration_minutes = 30
        runner.stats.duration_hours = 0.5

        report = runner._generate_markdown_report()

        assert "live_trading_enabled: false" in report
        assert "allow_auto_execution: false" in report
        assert "No real orders placed" in report


# =============================================================================
# Test No Private Key Requirement
# =============================================================================

class TestNoPrivateKeyRequirement:
    """Test no private key is required"""

    def test_runner_does_not_require_private_key(self, mock_config, conservative_run_config):
        """Test runner doesn't require private key"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)

        # Should not have any private key attribute
        assert not hasattr(runner, "private_key")
        assert not hasattr(runner, "wallet_key")

    def test_run_config_no_private_key(self):
        """Test run config doesn't have private key"""
        config = RunConfig()

        assert not hasattr(config, "private_key")
        assert not hasattr(config, "wallet_key")

    def test_report_verifies_no_private_keys(self, mock_config, conservative_run_config):
        """Test report verifies no private keys used"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
        )
        runner.stats.duration_minutes = 30
        runner.stats.duration_hours = 0.5

        report = runner._generate_markdown_report()

        assert "No private keys used" in report


# =============================================================================
# Test RunStatistics
# =============================================================================

class TestRunStatistics:
    """Test RunStatistics"""

    def test_to_dict(self):
        """Test to_dict conversion"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime(2026, 5, 8, 12, 0, 0),
            end_time=datetime(2026, 5, 8, 12, 30, 0),
            status="completed",
            markets_checked=100,
            signals_generated=20,
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        data = stats.to_dict()

        assert data["run_id"] == "test_run"
        assert data["status"] == "completed"
        assert data["markets_checked"] == 100
        assert data["signals_generated"] == 20

    def test_llm_avg_latency_calculation(self):
        """Test LLM average latency calculation"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            llm_latencies=[1.0, 2.0, 3.0],
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        data = stats.to_dict()
        assert data["llm_avg_latency_seconds"] == 2.0

    def test_llm_avg_latency_empty(self):
        """Test LLM average latency with no data"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            llm_latencies=[],
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        data = stats.to_dict()
        assert data["llm_avg_latency_seconds"] is None


# =============================================================================
# Test CLI Argument Parsing
# =============================================================================

class TestCLIArgumentParsing:
    """Test CLI argument parsing"""

    def test_duration_minutes_default(self):
        """Test default duration minutes"""
        with patch("sys.argv", ["run_paper.py"]):
            args = parse_args()
            assert args.duration_minutes == 30

    def test_duration_hours_override(self):
        """Test duration hours override"""
        with patch("sys.argv", ["run_paper.py", "--duration_hours", "3"]):
            args = parse_args()
            assert args.duration_hours == 3.0

    def test_max_markets(self):
        """Test max markets argument"""
        with patch("sys.argv", ["run_paper.py", "--max_markets", "50"]):
            args = parse_args()
            assert args.max_markets == 50

    def test_llm_provider(self):
        """Test LLM provider argument"""
        with patch("sys.argv", ["run_paper.py", "--llm_provider", "xfyun_anthropic", "--max_llm_calls_per_hour", "10"]):
            args = parse_args()
            assert args.llm_provider == "xfyun_anthropic"
            assert args.max_llm_calls_per_hour == 10

    def test_data_mode(self):
        """Test data mode argument"""
        with patch("sys.argv", ["run_paper.py", "--data_mode", "mock"]):
            args = parse_args()
            assert args.data_mode == "mock"

    def test_telegram_enabled(self):
        """Test Telegram enabled argument"""
        with patch("sys.argv", ["run_paper.py", "--telegram_enabled", "true"]):
            args = parse_args()
            assert args.telegram_enabled is True


# =============================================================================
# Test Real Data Integration
# =============================================================================

class TestRealDataIntegration:
    """Test real data integration"""

    def test_run_statistics_tracks_real_markets(self):
        """Test RunStatistics tracks real_markets_fetched"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            real_markets_fetched=100,
            orderbooks_fetched=50,
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        assert stats.real_markets_fetched == 100
        assert stats.orderbooks_fetched == 50

        data = stats.to_dict()
        assert data["real_markets_fetched"] == 100
        assert data["orderbooks_fetched"] == 50

    def test_mock_mode_does_not_track_real_markets(self):
        """Test mock mode doesn't count as real markets"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            data_mode="mock",
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        # In mock mode, real_markets_fetched should stay 0
        assert stats.real_markets_fetched == 0

    def test_real_readonly_mode_config(self):
        """Test real_readonly mode config"""
        config = RunConfig(data_mode="real_readonly")
        assert config.data_mode == "real_readonly"

    def test_hybrid_mode_config(self):
        """Test hybrid mode config"""
        config = RunConfig(data_mode="hybrid")
        assert config.data_mode == "hybrid"

    def test_api_errors_tracked(self):
        """Test API errors are tracked"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            api_errors=5,
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        assert stats.api_errors == 5
        data = stats.to_dict()
        assert data["api_errors"] == 5

    def test_fallback_count_tracked(self):
        """Test fallback count is tracked"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            api_fallbacks=3,
        )
        stats.duration_minutes = 30
        stats.duration_hours = 0.5

        assert stats.api_fallbacks == 3
        data = stats.to_dict()
        assert data["api_fallbacks"] == 3

    @pytest.mark.asyncio
    async def test_initialize_components_creates_data_provider(self, mock_config):
        """Test _initialize_components creates DataProviderManager"""
        run_config = RunConfig(data_mode="mock")
        runner = PaperTradingRunner(mock_config, run_config)

        # Initialize stats for logging
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
        )
        runner.run_dir = Path("runs") / "test_run"
        runner.run_dir.mkdir(parents=True, exist_ok=True)
        runner.events_file = open(runner.run_dir / "events.jsonl", "w")

        try:
            await runner._initialize_components()

            assert runner.data_provider is not None
            assert runner.microstructure_engine is not None
            assert runner.lifecycle_engine is not None
            assert runner.wallet_engine is not None
            assert runner.event_engine is not None
            assert runner.strategy is not None
            assert runner.risk_governor is not None
            assert runner.paper_trader is not None

            # Close data provider
            await runner.data_provider.close()
        finally:
            if runner.events_file:
                runner.events_file.close()
            # Cleanup run dir
            import shutil
            if runner.run_dir.exists():
                shutil.rmtree(runner.run_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_data_mode_real_readonly_creates_real_provider(self, mock_config):
        """Test data_mode=real_readonly creates real provider"""
        run_config = RunConfig(data_mode="real_readonly")
        runner = PaperTradingRunner(mock_config, run_config)

        # Initialize stats for logging
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            data_mode="real_readonly",
        )
        runner.run_dir = Path("runs") / "test_run_real"
        runner.run_dir.mkdir(parents=True, exist_ok=True)
        runner.events_file = open(runner.run_dir / "events.jsonl", "w")

        try:
            await runner._initialize_components()

            assert runner.data_provider is not None
            # The data provider should be in REAL_READONLY mode
            from polysignal.ingestion.data_provider_manager import DataMode
            assert runner.data_provider.mode == DataMode.REAL_READONLY

            await runner.data_provider.close()
        finally:
            if runner.events_file:
                runner.events_file.close()
            import shutil
            if runner.run_dir.exists():
                shutil.rmtree(runner.run_dir, ignore_errors=True)

    def test_report_includes_real_data_stats(self, mock_config, conservative_run_config):
        """Test report includes real data statistics"""
        runner = PaperTradingRunner(mock_config, conservative_run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            real_markets_fetched=150,
            orderbooks_fetched=75,
        )
        runner.stats.duration_minutes = 30
        runner.stats.duration_hours = 0.5

        report = runner._generate_markdown_report()

        assert "Real Markets Fetched" in report
        assert "Orderbooks Fetched" in report
        assert "150" in report
        assert "75" in report


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests"""

    @pytest.mark.asyncio
    async def test_full_run_with_mock_data(self, mock_config, tmp_path):
        """Test full run with mock data"""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            # Use very short duration for testing
            run_config = RunConfig(
                duration_minutes=0,  # Will exit immediately
                duration_hours=0,
                max_markets=5,
                scan_interval_seconds=1,
                data_mode="mock",
                llm_provider="mock",
                telegram_enabled=False,
            )

            runner = PaperTradingRunner(mock_config, run_config)

            # Mock database
            runner.db = MagicMock()
            runner.db._db = MagicMock()
            runner.db._db.execute = AsyncMock()
            runner.db._db.commit = AsyncMock()
            runner.db.close = AsyncMock()

            # Run
            result = await runner.run()

            assert result is not None
            assert "run_id" in result
            assert result["status"] in ["completed", "shutdown"]

        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_safety_check_failure_returns_error(self, mock_config, tmp_path):
        """Test safety check failure returns error"""
        mock_config.env.live_trading_enabled = True

        run_config = RunConfig()
        runner = PaperTradingRunner(mock_config, run_config)

        result = await runner.run()

        assert result["status"] == "rejected"
        assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
