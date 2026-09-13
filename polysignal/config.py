"""

Configuration Module - Load and validate configuration from YAML and environment variables
"""

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# Data Mode Configuration
# =============================================================================

class DataMode(str, Enum):
    """Data source mode"""
    MOCK = "mock"
    REAL_READONLY = "real_readonly"
    HYBRID = "hybrid"


# =============================================================================
# Configuration Models
# =============================================================================

class AppConfig(BaseModel):
    """Application configuration"""
    name: str = "PolySignal Pro"
    version: str = "0.1.0"
    environment: str = "development"


class DataModeConfig(BaseModel):
    """Data mode configuration"""
    data_mode: str = "mock"  # mock, real_readonly, hybrid


class UpdateIntervalsConfig(BaseModel):
    """Update intervals in seconds"""
    orderbook_refresh: int = 5
    market_refresh: int = 60
    health_check: int = 30


class PathsConfig(BaseModel):
    """Path configuration"""
    database: str = "data/polysignal.db"
    logs: str = "logs/polysignal.log"


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"
    format: str = "json"


class APIConfig(BaseModel):
    """API configuration for Polymarket"""
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    timeout_seconds: int = 10
    max_retries: int = 3


class WebSocketConfig(BaseModel):
    """WebSocket configuration for Polymarket CLOB market channel"""
    enabled: bool = True
    url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    subscribe_operation: str = "subscribe"
    ping_interval_seconds: int = 10
    pong_timeout_seconds: int = 10
    max_reconnect_attempts: int = 5
    reconnect_delay_seconds: float = 1.0
    reconnect_backoff_multiplier: float = 2.0
    max_reconnect_delay_seconds: float = 60.0
    stale_threshold_seconds: int = 60
    max_subscriptions: int = 20  # Per token, not per market
    subscribe_batch_size: int = 5
    subscribe_delay_ms: int = 100
    connect_timeout_seconds: int = 10
    message_timeout_seconds: int = 30


class AppSettings(BaseModel):
    """Full application settings from app.yaml"""
    app: AppConfig = Field(default_factory=AppConfig)
    data_mode: str = "mock"  # mock, real_readonly, hybrid
    update_intervals: UpdateIntervalsConfig = Field(default_factory=UpdateIntervalsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    api: APIConfig = Field(default_factory=APIConfig)


class ScoringWeights(BaseModel):
    """Scoring weights for Risk Governor"""
    microstructure: float = 0.30
    liquidity: float = 0.20
    event: float = 0.20
    wallet: float = 0.15
    lifecycle: float = 0.15


class Thresholds(BaseModel):
    """Decision thresholds"""
    ignore: int = 70
    log_only: int = 80
    alert: int = 90
    manual_review: int = 95


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration"""
    max_api_failures: int = 5
    max_ws_disconnects: int = 3
    stale_data_threshold_seconds: int = 60


class RiskSettings(BaseModel):
    """Full risk settings from risk.yaml"""
    live_trading_enabled: bool = False
    allow_auto_execution: bool = False
    paper_trading_enabled: bool = True

    max_account_capital_usd: float = 100.0
    max_position_pct: float = 0.01
    max_market_exposure_pct: float = 0.03
    max_strategy_exposure_pct: float = 0.08

    daily_max_loss_pct: float = 0.03
    weekly_max_loss_pct: float = 0.08
    max_consecutive_losses: int = 3

    min_total_volume_usd: float = 100000
    min_24h_volume_usd: float = 50000
    max_spread_pct: float = 0.05
    min_depth_usd: float = 20
    max_price_drift_pct: float = 0.02

    order_timeout_seconds: int = 20
    default_order_size_usd: float = 1.0
    slippage_assumption_pct: float = 0.01

    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    forbidden_auto_categories: list[str] = Field(
        default_factory=lambda: ["politics", "war_geopolitics", "legal", "celebrity", "subjective"]
    )
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)


class MockMarketConfig(BaseModel):
    """Mock market configuration"""
    num_markets: int = 10
    price_range: list[float] = Field(default_factory=lambda: [0.1, 0.9])
    volume_range_usd: list[float] = Field(default_factory=lambda: [100000.0, 1000000.0])


class MarketFilters(BaseModel):
    """Market filters"""
    min_volume_usd: float = 100000
    min_24h_volume_usd: float = 50000
    max_spread_pct: float = 0.05
    min_depth_usd: float = 20


class MarketSettings(BaseModel):
    """Full market settings from markets.yaml"""
    enabled_categories: list[str] = Field(
        default_factory=lambda: ["crypto", "sports", "weather", "macro"]
    )
    excluded_categories: list[str] = Field(
        default_factory=lambda: ["politics", "war_geopolitics", "legal", "celebrity", "subjective"]
    )
    filters: MarketFilters = Field(default_factory=MarketFilters)
    mock: MockMarketConfig = Field(default_factory=MockMarketConfig)


class WalletWatchlistEntry(BaseModel):
    """Wallet watchlist entry"""
    address: str
    alias: str = ""
    score: float = 50.0


class WalletScoringConfig(BaseModel):
    """Wallet scoring configuration"""
    min_trades_for_profile: int = 10
    min_volume_for_profile_usd: float = 1000
    max_copy_risk_score: float = 30


class AntiCopyConfig(BaseModel):
    """Anti-copy trading configuration"""
    enabled: bool = True
    max_follow_ratio: float = 0.5
    min_unique_trades_pct: float = 0.3


class WalletSettings(BaseModel):
    """Full wallet settings from wallets.yaml"""
    watchlist: list[WalletWatchlistEntry] = Field(default_factory=list)
    scoring: WalletScoringConfig = Field(default_factory=WalletScoringConfig)
    anti_copy: AntiCopyConfig = Field(default_factory=AntiCopyConfig)


class LLMSettings(BaseModel):
    """Full LLM settings from llm.yaml"""
    provider: str = "mock"


class TelegramConfig(BaseModel):
    """Telegram configuration"""
    enabled: bool = False  # Auto-detected from env
    timeout_seconds: int = 10
    max_retries: int = 3
    alert_cooldown_seconds: int = 60
    show_paper_trade_details: bool = True
    show_component_scores: bool = True


# =============================================================================
# Environment Variables
# =============================================================================

class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    """Environment variables settings"""
    live_trading_enabled: bool = False
    allow_auto_execution: bool = False
    paper_trading_enabled: bool = True

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # LLM API keys
    deepseek_api_key: str | None = None
    glm_api_key: str | None = None
    zai_api_key: str | None = None
    sensenova_api_key: str | None = None
    xfyun_api_key: str | None = None

    # LLM model overrides
    llm_provider: str = "mock"
    deepseek_model: str = "deepseek-chat"
    zai_model: str = "glm-5"
    glm_model: str = "glm-5"
    sensenova_model: str = "sensenova-6.7-flash-lite"
    xfyun_model: str = "astron-code-latest"

    database_path: str = "data/polysignal.db"
    log_level: str = "INFO"
    log_file: str = "logs/polysignal.log"

    polymarket_api_key: str | None = None

    # Data mode: mock, real_readonly, hybrid
    data_mode: str = "mock"

    # API settings
    api_timeout_seconds: int = 10
    api_max_retries: int = 3

# =============================================================================
# Configuration Loader
# =============================================================================

class Config:
    """
    Configuration loader that combines YAML files and environment variables.

    Priority: Environment variables > YAML files > Defaults
    """

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self._app: AppSettings | None = None
        self._risk: RiskSettings | None = None
        self._markets: MarketSettings | None = None
        self._wallets: WalletSettings | None = None
        self._llm: LLMSettings | None = None
        self._env: EnvSettings | None = None
        self._telegram: TelegramConfig | None = None
        self._websocket: WebSocketConfig | None = None

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        """Load a YAML file"""
        filepath = self.config_dir / filename
        if filepath.exists():
            with open(filepath) as f:
                return yaml.safe_load(f) or {}
        return {}

    @property
    def env(self) -> EnvSettings:
        """Get environment settings"""
        if self._env is None:
            self._env = EnvSettings()
        return self._env

    @property
    def app(self) -> AppSettings:
        """Get application settings"""
        if self._app is None:
            data = self._load_yaml("app.yaml")
            self._app = AppSettings(**data)
        return self._app

    @property
    def risk(self) -> RiskSettings:
        """Get risk settings (with env override)"""
        if self._risk is None:
            data = self._load_yaml("risk.yaml")
            self._risk = RiskSettings(**data)

            # Override with environment variables
            if self.env.live_trading_enabled is not None:
                self._risk.live_trading_enabled = self.env.live_trading_enabled
            if self.env.allow_auto_execution is not None:
                self._risk.allow_auto_execution = self.env.allow_auto_execution
            if self.env.paper_trading_enabled is not None:
                self._risk.paper_trading_enabled = self.env.paper_trading_enabled

        return self._risk

    @property
    def markets(self) -> MarketSettings:
        """Get market settings"""
        if self._markets is None:
            data = self._load_yaml("markets.yaml")
            self._markets = MarketSettings(**data)
        return self._markets

    @property
    def wallets(self) -> WalletSettings:
        """Get wallet settings"""
        if self._wallets is None:
            data = self._load_yaml("wallets.yaml")
            self._wallets = WalletSettings(**data)
        return self._wallets

    @property
    def llm(self) -> LLMSettings:
        """Get LLM settings"""
        if self._llm is None:
            data = self._load_yaml("llm.yaml")
            self._llm = LLMSettings(**data)
        return self._llm

    @property
    def telegram(self) -> TelegramConfig:
        """Get Telegram settings"""
        if self._telegram is None:
            data = self._load_yaml("app.yaml").get("telegram", {})
            self._telegram = TelegramConfig(**data)
            # Auto-detect enabled from environment
            self._telegram.enabled = self.is_telegram_enabled()
        return self._telegram

    @property
    def websocket(self) -> WebSocketConfig:
        """Get WebSocket settings"""
        if self._websocket is None:
            data = self._load_yaml("websocket.yaml").get("websocket", {})
            self._websocket = WebSocketConfig(**data)
        return self._websocket

    def is_live_trading_enabled(self) -> bool:
        """Check if live trading is enabled (must check both config and env)"""
        return self.risk.live_trading_enabled and self.env.live_trading_enabled

    def is_auto_execution_allowed(self) -> bool:
        """Check if auto execution is allowed"""
        return self.risk.allow_auto_execution and self.env.allow_auto_execution

    def is_telegram_enabled(self) -> bool:
        """Check if Telegram is configured"""
        return bool(self.env.telegram_bot_token and self.env.telegram_chat_id)

    def get_data_mode(self) -> DataMode:
        """Get data mode from config/env"""
        mode_str = self.env.data_mode or self.app.data_mode or "mock"
        try:
            return DataMode(mode_str.lower())
        except ValueError:
            return DataMode.MOCK

    def get_api_config(self) -> APIConfig:
        """Get API configuration"""
        return APIConfig(
            gamma_base_url=self.app.api.gamma_base_url,
            clob_base_url=self.app.api.clob_base_url,
            timeout_seconds=self.env.api_timeout_seconds or self.app.api.timeout_seconds,
            max_retries=self.env.api_max_retries or self.app.api.max_retries,
        )

    def get_summary(self) -> dict[str, Any]:
        """Get configuration summary for logging"""
        return {
            "app": {
                "name": self.app.app.name,
                "version": self.app.app.version,
                "environment": self.app.app.environment,
                "data_mode": self.app.data_mode,
            },
            "risk": {
                "live_trading_enabled": self.risk.live_trading_enabled,
                "allow_auto_execution": self.risk.allow_auto_execution,
                "paper_trading_enabled": self.risk.paper_trading_enabled,
            },
            "telegram_enabled": self.is_telegram_enabled(),
            "database_path": self.env.database_path,
        }


# Global configuration instance
config = Config()
