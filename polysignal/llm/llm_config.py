"""
LLM Configuration - Configuration models and loading for LLM providers

IMPORTANT: API keys are loaded from environment variables ONLY.
They are NEVER stored in config files or logged.

Environment variables:
- LLM_PROVIDER: Override provider selection (mock, deepseek, glm, sensenova, xfyun_anthropic, router)
- DEEPSEEK_API_KEY: DeepSeek API key
- DEEPSEEK_MODEL: DeepSeek model override
- ZAI_API_KEY: Z.AI API key (preferred for GLM)
- GLM_API_KEY: GLM API key (fallback for GLM)
- ZAI_MODEL: Z.AI model override (preferred)
- GLM_MODEL: GLM model override (fallback)
- SENSENOVA_API_KEY: SenseNova API key
- SENSENOVA_MODEL: SenseNova model override
- XFYUN_API_KEY: XFyun API key
- XFYUN_MODEL: XFyun model override
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class LLMProviderType(str, Enum):
    """LLM provider types"""
    MOCK = "mock"
    DEEPSEEK = "deepseek"
    GLM = "glm"
    ZAI = "zai"  # Z.AI (same as GLM, different naming)
    SENSENOVA = "sensenova"
    XFYUN_ANTHROPIC = "xfyun_anthropic"
    ROUTER = "router"


class DeepSeekConfig(BaseModel):
    """DeepSeek provider configuration"""

    # Model ID (config-driven, can be overridden by env)
    model: str = Field(
        default="deepseek-chat",
        description="DeepSeek model ID",
    )

    # API base URL
    base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="DeepSeek API base URL",
    )

    # Timeout and retry
    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)

    # Rate limiting
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)

    # Generation parameters
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=100, le=8000)

    # JSON mode support (DeepSeek supports response_format)
    supports_json_mode: bool = Field(default=True)

    def get_api_key(self) -> str | None:
        """Get API key from environment variable"""
        return os.environ.get("DEEPSEEK_API_KEY")

    def get_model(self) -> str:
        """Get model ID (env override takes precedence)"""
        env_model = os.environ.get("DEEPSEEK_MODEL")
        return env_model if env_model else self.model

    def is_configured(self) -> bool:
        """Check if provider is configured (has API key)"""
        return self.get_api_key() is not None


class GLMConfig(BaseModel):
    """GLM/Z.AI provider configuration"""

    # Model ID (config-driven, can be overridden by env)
    # Default to glm-5 (not glm-4-flash)
    model: str = Field(
        default="glm-5",
        description="GLM/Z.AI model ID",
    )

    # API base URL (Z.AI/GLM use same endpoint)
    base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="GLM/Z.AI API base URL",
    )

    # Timeout and retry
    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)

    # Rate limiting
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)

    # Generation parameters
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=100, le=8000)

    # JSON mode support (GLM may not support response_format, use prompt constraint)
    supports_json_mode: bool = Field(default=False)

    def get_api_key(self) -> str | None:
        """Get API key from environment variable (ZAI_API_KEY preferred, GLM_API_KEY fallback)"""
        # ZAI_API_KEY takes precedence
        zai_key = os.environ.get("ZAI_API_KEY")
        if zai_key:
            return zai_key
        # GLM_API_KEY as fallback
        return os.environ.get("GLM_API_KEY")

    def get_model(self) -> str:
        """Get model ID (ZAI_MODEL preferred, GLM_MODEL fallback, then config default)"""
        # ZAI_MODEL takes precedence
        zai_model = os.environ.get("ZAI_MODEL")
        if zai_model:
            return zai_model
        # GLM_MODEL as fallback
        glm_model = os.environ.get("GLM_MODEL")
        if glm_model:
            return glm_model
        # Config default
        return self.model

    def is_configured(self) -> bool:
        """Check if provider is configured (has API key)"""
        return self.get_api_key() is not None


class MockConfig(BaseModel):
    """Mock provider configuration"""

    scenario: Literal[
        "success",
        "invalid_json",
        "low_confidence",
        "timeout",
        "schema_error",
        "missing_fields",
    ] = Field(default="success")

    default_latency: float = Field(default=0.1, ge=0.0, le=5.0)


class SenseNovaConfig(BaseModel):
    """SenseNova provider configuration (OpenAI-compatible)"""

    model: str = Field(
        default="sensenova-6.7-flash-lite",
        description="SenseNova model ID",
    )

    base_url: str = Field(
        default="https://token.sensenova.cn/v1",
        description="SenseNova API base URL",
    )

    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=100, le=8000)
    supports_json_mode: bool = Field(default=False)

    def get_api_key(self) -> str | None:
        """Get API key from environment variable"""
        return os.environ.get("SENSENOVA_API_KEY")

    def get_model(self) -> str:
        """Get model ID (env override takes precedence)"""
        env_model = os.environ.get("SENSENOVA_MODEL")
        return env_model if env_model else self.model

    def is_configured(self) -> bool:
        """Check if provider is configured (has API key)"""
        return self.get_api_key() is not None


class XFyunAnthropicConfig(BaseModel):
    """XFyun Anthropic provider configuration"""

    model: str = Field(
        default="astron-code-latest",
        description="XFyun Anthropic model ID",
    )

    base_url: str = Field(
        default="https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic",
        description="XFyun Anthropic API base URL",
    )

    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=100, le=8000)
    supports_json_mode: bool = Field(default=False)

    def get_api_key(self) -> str | None:
        """Get API key from environment variable"""
        return os.environ.get("XFYUN_API_KEY")

    def get_model(self) -> str:
        """Get model ID (env override takes precedence)"""
        env_model = os.environ.get("XFYUN_MODEL")
        return env_model if env_model else self.model

    def is_configured(self) -> bool:
        """Check if provider is configured (has API key)"""
        return self.get_api_key() is not None


class RouterConfig(BaseModel):
    """Provider router configuration"""

    # Default providers for different analysis types
    default_event_provider: Literal["deepseek", "glm", "mock"] = Field(
        default="deepseek",
        description="Default provider for event analysis",
    )

    default_rule_provider: Literal["deepseek", "glm", "mock"] = Field(
        default="glm",
        description="Default provider for rule analysis",
    )

    # Fallback provider (always mock for safety)
    fallback_provider: Literal["mock"] = Field(
        default="mock",
        description="Fallback provider when real providers fail",
    )

    # Cross-provider fallback (disabled by default)
    # When True, DeepSeek can fallback to GLM and vice versa
    # When False, only fallback to Mock
    allow_cross_provider_fallback: bool = Field(
        default=False,
        description="Allow fallback between real providers",
    )


class ValidationConfig(BaseModel):
    """Output validation configuration"""

    # Forbidden trading fields (checked in JSON keys only, not in text values)
    forbidden_fields: list[str] = Field(
        default_factory=lambda: [
            "side",
            "size",
            "order",
            "position",
            "buy",
            "sell",
            "action",
        ],
        description="Forbidden trading fields in LLM output",
    )

    # Minimum confidence threshold
    min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    )

    # Require JSON output
    require_json: bool = Field(default=True)

    # Require confidence field
    require_confidence: bool = Field(default=True)


class LLMConfig(BaseModel):
    """Top-level LLM configuration"""

    # Provider selection (mock by default, must be explicitly changed)
    provider: LLMProviderType = Field(
        default=LLMProviderType.MOCK,
        description="LLM provider to use",
    )

    # Provider-specific configs
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)
    glm: GLMConfig = Field(default_factory=GLMConfig)
    sensenova: SenseNovaConfig = Field(default_factory=SenseNovaConfig)
    xfyun_anthropic: XFyunAnthropicConfig = Field(default_factory=XFyunAnthropicConfig)
    mock: MockConfig = Field(default_factory=MockConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)

    # Validation config
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    def get_effective_provider(self) -> LLMProviderType:
        """
        Get effective provider type.

        Environment variable LLM_PROVIDER takes precedence.
        If no API key for selected provider, fallback to mock.
        """
        # Check environment override
        env_provider = os.environ.get("LLM_PROVIDER")
        if env_provider:
            try:
                provider_type = LLMProviderType(env_provider.lower())
            except ValueError:
                # Invalid provider name, use config default
                provider_type = self.provider
        else:
            provider_type = self.provider

        # Check if provider is configured (has API key)
        if provider_type == LLMProviderType.DEEPSEEK:
            if not self.deepseek.is_configured():
                return LLMProviderType.MOCK

        elif provider_type == LLMProviderType.GLM or provider_type == LLMProviderType.ZAI:
            if not self.glm.is_configured():
                return LLMProviderType.MOCK

        elif provider_type == LLMProviderType.SENSENOVA:
            if not self.sensenova.is_configured():
                return LLMProviderType.MOCK

        elif provider_type == LLMProviderType.XFYUN_ANTHROPIC:
            if not self.xfyun_anthropic.is_configured():
                return LLMProviderType.MOCK

        elif provider_type == LLMProviderType.ROUTER:
            # Router needs at least one real provider configured
            if not self.deepseek.is_configured() and not self.glm.is_configured() \
               and not self.sensenova.is_configured() and not self.xfyun_anthropic.is_configured():
                return LLMProviderType.MOCK

        return provider_type

    def is_mock_mode(self) -> bool:
        """Check if using mock provider"""
        return self.get_effective_provider() == LLMProviderType.MOCK


def load_llm_config(config_path: str | None = None) -> LLMConfig:
    """
    Load LLM configuration from YAML file.

    Args:
        config_path: Path to config file (default: config/llm.yaml)

    Returns:
        LLMConfig instance
    """
    import yaml

    if config_path is None:
        # Default path
        config_path = "config/llm.yaml"

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        return LLMConfig.model_validate(data)
    except FileNotFoundError:
        # Return default config if file not found
        return LLMConfig()
    except Exception as e:
        # Return default config on error
        print(f"Warning: Failed to load LLM config: {e}")
        return LLMConfig()