"""
Tests for GLM/Z.AI LLM Provider

IMPORTANT: All tests use mock HTTP transport.
Tests do NOT depend on real GLM/Z.AI API.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import httpx

from polysignal.llm.glm_provider import (
    GLMProvider,
    check_forbidden_trading_fields_in_keys,
)
from polysignal.llm.llm_config import GLMConfig
from polysignal.llm.llm_errors import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMForbiddenFieldsError,
    LLMInvalidJSON,
    LLMRateLimit,
    LLMSchemaError,
    LLMTimeout,
    LLMProviderNotConfigured,
)
from polysignal.llm.schemas import EventAnalysisSchema, MarketRuleSchema
from polysignal.models.event import LLMResponse


class TestGLMConfig:
    """Test GLM Configuration"""

    def test_default_model_is_glm5(self):
        """Test default model is glm-5 (NOT glm-4-flash)"""
        config = GLMConfig()
        assert config.model == "glm-5"

    def test_api_key_from_zai_preferred(self):
        """Test ZAI_API_KEY takes precedence"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "zai-key", "GLM_API_KEY": "glm-key"}):
            config = GLMConfig()
            assert config.get_api_key() == "zai-key"

    def test_api_key_from_glm_fallback(self):
        """Test GLM_API_KEY as fallback"""
        with patch.dict("os.environ", {"GLM_API_KEY": "glm-key"}, clear=True):
            config = GLMConfig()
            assert config.get_api_key() == "glm-key"

    def test_model_from_zai_model_preferred(self):
        """Test ZAI_MODEL takes precedence"""
        with patch.dict("os.environ", {"ZAI_MODEL": "glm-5-flash", "GLM_MODEL": "glm-4"}):
            config = GLMConfig()
            assert config.get_model() == "glm-5-flash"

    def test_model_from_glm_model_fallback(self):
        """Test GLM_MODEL as fallback"""
        with patch.dict("os.environ", {"GLM_MODEL": "glm-4-flash"}, clear=True):
            config = GLMConfig()
            assert config.get_model() == "glm-4-flash"

    def test_model_default_without_env(self):
        """Test default model without env override"""
        with patch.dict("os.environ", {}, clear=True):
            config = GLMConfig()
            assert config.get_model() == "glm-5"

    def test_not_configured_without_api_key(self):
        """Test not configured without API key"""
        with patch.dict("os.environ", {}, clear=True):
            config = GLMConfig()
            assert config.is_configured() is False

    def test_configured_with_zai_key(self):
        """Test configured with ZAI_API_KEY"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            config = GLMConfig()
            assert config.is_configured() is True

    def test_configured_with_glm_key(self):
        """Test configured with GLM_API_KEY"""
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            config = GLMConfig()
            assert config.is_configured() is True


class TestGLMProvider:
    """Test GLM Provider"""

    @pytest.fixture
    def config(self) -> GLMConfig:
        """Create test config"""
        return GLMConfig(
            model="glm-5",
            timeout_seconds=30.0,
            max_retries=2,
            temperature=0.1,
            max_tokens=2000,
            supports_json_mode=False,  # GLM may not support JSON mode
        )

    @pytest.fixture
    def provider(self, config: GLMConfig) -> GLMProvider:
        """Create provider with test config"""
        return GLMProvider(config=config)

    # =========================================================================
    # Basic Tests
    # =========================================================================

    def test_provider_name(self, provider: GLMProvider):
        """Test provider name"""
        assert provider.get_provider_name() == "glm"

    def test_provider_status(self, provider: GLMProvider):
        """Test provider status"""
        status = provider.get_status()

        assert status["provider"] == "glm"
        assert status["model"] == "glm-5"
        assert status["supports_json_mode"] is False

    def test_not_configured_without_api_key(self, provider: GLMProvider):
        """Test provider not configured without API key"""
        with patch.dict("os.environ", {}, clear=True):
            assert provider.config.is_configured() is False

    # =========================================================================
    # Provider Not Configured Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_raises_not_configured_without_api_key(self, provider: GLMProvider):
        """Test raises LLMProviderNotConfigured without API key"""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(LLMProviderNotConfigured):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                )

    # =========================================================================
    # Success Response Tests (Mock HTTP)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_success_response(self, config: GLMConfig):
        """Test successful response from GLM"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                return LLMResponse(
                    success=True,
                    parsed_output=EventAnalysisSchema(
                        event_score=75.0,
                        evidence_strength=80.0,
                        market_relevance=70.0,
                        ambiguity_risk=30.0,
                        suggested_mode="research",
                        risk_flags=[],
                        explanation="Test explanation",
                        confidence=0.85,
                    ),
                    raw_output='{"event_score": 75.0, ...}',
                    confidence=0.85,
                    provider="glm",
                    latency_seconds=0.5,
                )

            with patch.object(provider, "_make_request", mock_make_request):
                response = await provider.analyze(
                    prompt="Test prompt",
                    response_schema=EventAnalysisSchema,
                )

                assert response.success is True
                assert response.parsed_output is not None
                assert response.parsed_output.event_score == 75.0
                assert response.confidence == 0.85
                assert response.provider == "glm"

    @pytest.mark.asyncio
    async def test_success_with_glm_api_key(self, config: GLMConfig):
        """Test successful response with GLM_API_KEY (fallback)"""
        # Only GLM_API_KEY, no ZAI_API_KEY
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}, clear=True):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                return LLMResponse(
                    success=True,
                    parsed_output=EventAnalysisSchema(
                        event_score=75.0,
                        evidence_strength=80.0,
                        market_relevance=70.0,
                        ambiguity_risk=30.0,
                        suggested_mode="research",
                        risk_flags=[],
                        explanation="Test",
                        confidence=0.85,
                    ),
                    raw_output='{"event_score": 75.0, ...}',
                    confidence=0.85,
                    provider="glm",
                    latency_seconds=0.5,
                )

            with patch.object(provider, "_make_request", mock_make_request):
                response = await provider.analyze(
                    prompt="Test prompt",
                    response_schema=EventAnalysisSchema,
                )

                assert response.success is True

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_authentication_error(self, config: GLMConfig):
        """Test authentication error (401)"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "invalid-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMAuthenticationError(
                    message="GLM/Z.AI API authentication failed",
                    provider="glm",
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMAuthenticationError):
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, config: GLMConfig):
        """Test rate limit error (429)"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMRateLimit(
                    message="GLM/Z.AI API rate limit exceeded",
                    provider="glm",
                    retry_after=30.0,
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMRateLimit) as exc_info:
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

            assert exc_info.value.retry_after == 30.0

    @pytest.mark.asyncio
    async def test_timeout_error(self, config: GLMConfig):
        """Test timeout error"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMTimeout(
                    message="GLM/Z.AI API request timed out",
                    provider="glm",
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMTimeout):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

    @pytest.mark.asyncio
    async def test_connection_error(self, config: GLMConfig):
        """Test connection error"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMConnectionError(
                    message="Failed to connect to GLM/Z.AI API",
                    provider="glm",
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMConnectionError):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, config: GLMConfig):
        """Test invalid JSON response"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMInvalidJSON(
                    message="Invalid JSON from GLM/Z.AI",
                    provider="glm",
                    raw_output="not valid json",
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMInvalidJSON):
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

    @pytest.mark.asyncio
    async def test_schema_validation_error(self, config: GLMConfig):
        """Test schema validation error"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMSchemaError(
                    message="Schema validation failed",
                    provider="glm",
                    raw_output='{"event_score": "not_a_number"}',
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMSchemaError):
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

    @pytest.mark.asyncio
    async def test_forbidden_fields_in_response(self, config: GLMConfig):
        """Test forbidden fields detection in response"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMForbiddenFieldsError(
                    message="GLM/Z.AI output contains forbidden trading fields",
                    provider="glm",
                    forbidden_fields=["action"],
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMForbiddenFieldsError) as exc_info:
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

                assert "action" in exc_info.value.forbidden_fields

    @pytest.mark.asyncio
    async def test_server_error_500(self, config: GLMConfig):
        """Test server error (500)"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMConnectionError(
                    message="GLM/Z.AI API server error: 500",
                    provider="glm",
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMConnectionError):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

    @pytest.mark.asyncio
    async def test_empty_response(self, config: GLMConfig):
        """Test empty response"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                return LLMResponse(
                    success=False,
                    error="Empty response from GLM/Z.AI",
                    error_type="empty_response",
                    provider="glm",
                    latency_seconds=0.5,
                )

            with patch.object(provider, "_make_request", mock_make_request):
                response = await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                )

                assert response.success is False
                assert response.error_type == "empty_response"

    # =========================================================================
    # Market Rule Schema Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_market_rule_schema(self, config: GLMConfig):
        """Test with MarketRuleSchema"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            provider = GLMProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                return LLMResponse(
                    success=True,
                    parsed_output=MarketRuleSchema(
                        rule_clarity=80.0,
                        resolution_source_type="oracle",
                        resolution_source_reliability=85.0,
                        has_ambiguity=False,
                        ambiguity_keywords=[],
                        ambiguity_explanation="",
                        suggested_category="crypto",
                        is_forbidden_category=False,
                        confidence=0.9,
                        explanation="Clear rules",
                    ),
                    raw_output='{"rule_clarity": 80.0, ...}',
                    confidence=0.9,
                    provider="glm",
                    latency_seconds=0.5,
                )

            with patch.object(provider, "_make_request", mock_make_request):
                response = await provider.analyze(
                    prompt="Analyze rules",
                    response_schema=MarketRuleSchema,
                )

                assert response.success is True
                assert response.parsed_output is not None
                assert isinstance(response.parsed_output, MarketRuleSchema)
                assert response.parsed_output.rule_clarity == 80.0