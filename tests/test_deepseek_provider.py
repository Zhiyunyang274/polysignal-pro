"""
Tests for DeepSeek LLM Provider

IMPORTANT: All tests use mock HTTP transport.
Tests do NOT depend on real DeepSeek API.
"""

import json
from unittest.mock import patch

import pytest

from polysignal.llm.deepseek_provider import (
    DeepSeekProvider,
    check_forbidden_trading_fields_in_keys,
)
from polysignal.llm.llm_config import DeepSeekConfig
from polysignal.llm.llm_errors import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMForbiddenFieldsError,
    LLMInvalidJSON,
    LLMProviderNotConfigured,
    LLMRateLimit,
    LLMSchemaError,
    LLMTimeout,
)
from polysignal.llm.schemas import EventAnalysisSchema, MarketRuleSchema
from polysignal.models.event import LLMResponse


class TestCheckForbiddenTradingFields:
    """Test forbidden trading fields detection"""

    def test_no_forbidden_fields(self):
        """Test data with no forbidden fields"""
        data = {
            "event_score": 75.0,
            "evidence_strength": 80.0,
            "explanation": "The market shows a clear trend",
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is False
        assert fields == []

    def test_forbidden_field_side(self):
        """Test data with forbidden field 'side'"""
        data = {
            "event_score": 75.0,
            "side": "buy",  # Forbidden!
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is True
        assert "side" in fields

    def test_forbidden_field_size(self):
        """Test data with forbidden field 'size'"""
        data = {
            "event_score": 75.0,
            "size": 100,  # Forbidden!
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is True
        assert "size" in fields

    def test_forbidden_field_action(self):
        """Test data with forbidden field 'action'"""
        data = {
            "event_score": 75.0,
            "action": "execute",  # Forbidden!
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is True
        assert "action" in fields

    def test_forbidden_fields_in_nested_dict(self):
        """Test forbidden fields in nested dict"""
        data = {
            "event_score": 75.0,
            "nested": {
                "order": "limit",  # Forbidden in nested!
            },
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is True
        assert "order" in fields

    def test_forbidden_fields_in_list(self):
        """Test forbidden fields in list"""
        data = {
            "event_score": 75.0,
            "items": [
                {"position": "long"},  # Forbidden in list item!
            ],
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is True
        assert "position" in fields

    def test_forbidden_word_in_text_value_not_flagged(self):
        """Test forbidden word in text value is NOT flagged"""
        # IMPORTANT: Only JSON keys are checked, NOT text values
        data = {
            "event_score": 75.0,
            "explanation": "The market shows a buy signal",  # "buy" in text, NOT flagged
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is False
        assert fields == []

    def test_case_insensitive_detection(self):
        """Test case-insensitive detection"""
        data = {
            "event_score": 75.0,
            "SIDE": "buy",  # Upper case
            "Buy": "yes",   # Mixed case
        }
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)
        assert has_forbidden is True
        assert "SIDE" in fields
        assert "Buy" in fields


class TestDeepSeekProvider:
    """Test DeepSeek Provider"""

    @pytest.fixture
    def config(self) -> DeepSeekConfig:
        """Create test config"""
        return DeepSeekConfig(
            model="deepseek-chat",
            timeout_seconds=30.0,
            max_retries=2,
            temperature=0.1,
            max_tokens=2000,
        )

    @pytest.fixture
    def provider(self, config: DeepSeekConfig) -> DeepSeekProvider:
        """Create provider with test config"""
        return DeepSeekProvider(config=config)

    # =========================================================================
    # Basic Tests
    # =========================================================================

    def test_provider_name(self, provider: DeepSeekProvider):
        """Test provider name"""
        assert provider.get_provider_name() == "deepseek"

    def test_provider_status(self, provider: DeepSeekProvider, monkeypatch: pytest.MonkeyPatch):
        """Test provider status"""
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        status = provider.get_status()

        assert status["provider"] == "deepseek"
        assert status["model"] == "deepseek-chat"
        assert status["supports_json_mode"] is True

    def test_not_configured_without_api_key(self, provider: DeepSeekProvider):
        """Test provider not configured without API key"""
        with patch.dict("os.environ", {}, clear=True):
            assert provider.config.is_configured() is False

    def test_configured_with_api_key(self, config: DeepSeekConfig):
        """Test provider configured with API key"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            assert config.is_configured() is True

    def test_model_override_from_env(self, config: DeepSeekConfig):
        """Test model override from environment"""
        with patch.dict("os.environ", {"DEEPSEEK_MODEL": "deepseek-v4-flash"}):
            assert config.get_model() == "deepseek-v4-flash"

    def test_default_model_without_override(self, config: DeepSeekConfig):
        """Test default model without env override"""
        with patch.dict("os.environ", {}, clear=True):
            assert config.get_model() == "deepseek-chat"

    # =========================================================================
    # Provider Not Configured Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_raises_not_configured_without_api_key(self, provider: DeepSeekProvider):
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
    async def test_success_response(self, config: DeepSeekConfig):
        """Test successful response from DeepSeek"""
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "event_score": 75.0,
                            "evidence_strength": 80.0,
                            "market_relevance": 70.0,
                            "ambiguity_risk": 30.0,
                            "suggested_mode": "research",
                            "risk_flags": [],
                            "explanation": "Test explanation",
                            "confidence": 0.85,
                        })
                    }
                }
            ]
        }

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            # Mock the entire _make_request method
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
                    raw_output=json.dumps({
                        "event_score": 75.0,
                        "evidence_strength": 80.0,
                        "market_relevance": 70.0,
                        "ambiguity_risk": 30.0,
                        "suggested_mode": "research",
                        "risk_flags": [],
                        "explanation": "Test explanation",
                        "confidence": 0.85,
                    }),
                    confidence=0.85,
                    provider="deepseek",
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
                assert response.provider == "deepseek"

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_authentication_error(self, config: DeepSeekConfig):
        """Test authentication error (401)"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "invalid-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMAuthenticationError(
                    message="DeepSeek API authentication failed",
                    provider="deepseek",
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMAuthenticationError):
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, config: DeepSeekConfig):
        """Test rate limit error (429)"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            # Mock the _make_request method to raise the error

            async def mock_make_request(*args, **kwargs):
                raise LLMRateLimit(
                    message="DeepSeek API rate limit exceeded",
                    provider="deepseek",
                    retry_after=60.0,
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMRateLimit) as exc_info:
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

            assert exc_info.value.retry_after == 60.0

    @pytest.mark.asyncio
    async def test_timeout_error(self, config: DeepSeekConfig):
        """Test timeout error"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMTimeout(
                    message="DeepSeek API request timed out",
                    provider="deepseek",
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMTimeout):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

    @pytest.mark.asyncio
    async def test_connection_error(self, config: DeepSeekConfig):
        """Test connection error"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMConnectionError(
                    message="Failed to connect to DeepSeek API",
                    provider="deepseek",
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMConnectionError):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, config: DeepSeekConfig):
        """Test invalid JSON response"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMInvalidJSON(
                    message="Invalid JSON from DeepSeek",
                    provider="deepseek",
                    raw_output="not valid json",
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMInvalidJSON):
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

    @pytest.mark.asyncio
    async def test_schema_validation_error(self, config: DeepSeekConfig):
        """Test schema validation error"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMSchemaError(
                    message="Schema validation failed",
                    provider="deepseek",
                    raw_output='{"event_score": "not_a_number"}',
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMSchemaError):
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

    @pytest.mark.asyncio
    async def test_forbidden_fields_in_response(self, config: DeepSeekConfig):
        """Test forbidden fields detection in response"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMForbiddenFieldsError(
                    message="DeepSeek output contains forbidden trading fields",
                    provider="deepseek",
                    forbidden_fields=["side"],
                )

            with patch.object(provider, "_make_request", mock_make_request):
                with pytest.raises(LLMForbiddenFieldsError) as exc_info:
                    await provider.analyze(
                        prompt="Test",
                        response_schema=EventAnalysisSchema,
                    )

                assert "side" in exc_info.value.forbidden_fields

    @pytest.mark.asyncio
    async def test_server_error_500(self, config: DeepSeekConfig):
        """Test server error (500)"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                raise LLMConnectionError(
                    message="DeepSeek API server error: 500",
                    provider="deepseek",
                )

            provider._make_request = mock_make_request

            with pytest.raises(LLMConnectionError):
                await provider.analyze(
                    prompt="Test",
                    response_schema=EventAnalysisSchema,
                    max_retries=0,
                )

    @pytest.mark.asyncio
    async def test_empty_response(self, config: DeepSeekConfig):
        """Test empty response"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

            async def mock_make_request(*args, **kwargs):
                return LLMResponse(
                    success=False,
                    error="Empty response from DeepSeek",
                    error_type="empty_response",
                    provider="deepseek",
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
    async def test_market_rule_schema(self, config: DeepSeekConfig):
        """Test with MarketRuleSchema"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            provider = DeepSeekProvider(config=config)

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
                    provider="deepseek",
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
