"""
LLM Package - LLM Provider abstraction and implementations

IMPORTANT: LLM can only provide analysis and suggestions.
LLM CANNOT directly trigger trading execution.

Available providers:
- MockLLMProvider: Deterministic mock for testing
- DeepSeekProvider: DeepSeek API (requires DEEPSEEK_API_KEY)
- GLMProvider: GLM/Z.AI API (requires ZAI_API_KEY or GLM_API_KEY)
- ProviderRouter: Intelligent routing between providers

Environment variables:
- LLM_PROVIDER: Override provider (mock, deepseek, glm, router)
- DEEPSEEK_API_KEY: DeepSeek API key
- DEEPSEEK_MODEL: DeepSeek model override
- ZAI_API_KEY: Z.AI API key (preferred for GLM)
- GLM_API_KEY: GLM API key (fallback)
- ZAI_MODEL: Z.AI model override (preferred)
- GLM_MODEL: GLM model override (fallback)
"""

from polysignal.llm.base import LLMProvider
from polysignal.llm.mock_provider import MockLLMProvider, MockScenario
from polysignal.llm.deepseek_provider import DeepSeekProvider
from polysignal.llm.glm_provider import GLMProvider
from polysignal.llm.provider_router import ProviderRouter, AnalysisType, create_llm_provider_from_config
from polysignal.llm.llm_config import (
    LLMConfig,
    LLMProviderType,
    DeepSeekConfig,
    GLMConfig,
    MockConfig,
    RouterConfig,
    ValidationConfig,
    load_llm_config,
)
from polysignal.llm.llm_errors import (
    LLMError,
    LLMTimeout,
    LLMConnectionError,
    LLMAuthenticationError,
    LLMRateLimit,
    LLMInvalidJSON,
    LLMSchemaError,
    LLMForbiddenFieldsError,
    LLMLowConfidence,
    LLMProviderNotConfigured,
)
from polysignal.llm.schemas import (
    EventAnalysisSchema,
    MarketRuleSchema,
)

__all__ = [
    # Base
    "LLMProvider",
    # Providers
    "MockLLMProvider",
    "MockScenario",
    "DeepSeekProvider",
    "GLMProvider",
    "ProviderRouter",
    "AnalysisType",
    # Config
    "LLMConfig",
    "LLMProviderType",
    "DeepSeekConfig",
    "GLMConfig",
    "MockConfig",
    "RouterConfig",
    "ValidationConfig",
    "load_llm_config",
    "create_llm_provider_from_config",
    # Errors
    "LLMError",
    "LLMTimeout",
    "LLMConnectionError",
    "LLMAuthenticationError",
    "LLMRateLimit",
    "LLMInvalidJSON",
    "LLMSchemaError",
    "LLMForbiddenFieldsError",
    "LLMLowConfidence",
    "LLMProviderNotConfigured",
    # Schemas
    "EventAnalysisSchema",
    "MarketRuleSchema",
]