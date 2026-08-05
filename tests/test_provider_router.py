"""
Tests for Provider Router

IMPORTANT: All tests use mock providers.
Tests do NOT depend on real LLM APIs.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from polysignal.llm.provider_router import (
    ProviderRouter,
    AnalysisType,
    create_llm_provider_from_config,
)
from polysignal.llm.llm_config import (
    LLMConfig,
    LLMProviderType,
    RouterConfig,
    DeepSeekConfig,
    GLMConfig,
    MockConfig,
)
from polysignal.llm.mock_provider import MockLLMProvider, MockScenario
from polysignal.llm.deepseek_provider import DeepSeekProvider
from polysignal.llm.glm_provider import GLMProvider
from polysignal.llm.schemas import EventAnalysisSchema, MarketRuleSchema
from polysignal.models.event import LLMResponse


class TestProviderRouter:
    """Test Provider Router"""

    @pytest.fixture
    def router_config(self) -> RouterConfig:
        """Create router config"""
        return RouterConfig(
            default_event_provider="deepseek",
            default_rule_provider="glm",
            fallback_provider="mock",
            allow_cross_provider_fallback=False,
        )

    @pytest.fixture
    def router(self, router_config: RouterConfig) -> ProviderRouter:
        """Create router with test config"""
        return ProviderRouter(
            config=router_config,
            mock_scenario=MockScenario.SUCCESS,
        )

    # =========================================================================
    # Basic Tests
    # =========================================================================

    def test_provider_name(self, router: ProviderRouter):
        """Test provider name"""
        assert router.get_provider_name() == "router"

    def test_provider_status(self, router: ProviderRouter):
        """Test provider status"""
        status = router.get_status()

        assert status["provider"] == "router"
        assert status["default_event_provider"] == "deepseek"
        assert status["default_rule_provider"] == "glm"
        assert status["fallback_provider"] == "mock"
        assert status["allow_cross_provider_fallback"] is False

    def test_lazy_initialization(self, router: ProviderRouter):
        """Test lazy initialization of providers"""
        # Providers should not be initialized yet
        assert router._deepseek is None
        assert router._glm is None
        assert router._mock is None

        # Accessing properties should initialize them
        _ = router.mock
        assert router._mock is not None
        assert isinstance(router._mock, MockLLMProvider)

    # =========================================================================
    # Provider Selection Tests
    # =========================================================================

    def test_get_provider_deepseek(self, router: ProviderRouter):
        """Test getting DeepSeek provider"""
        provider = router._get_provider("deepseek")
        assert isinstance(provider, DeepSeekProvider)

    def test_get_provider_glm(self, router: ProviderRouter):
        """Test getting GLM provider"""
        provider = router._get_provider("glm")
        assert isinstance(provider, GLMProvider)

    def test_get_provider_mock(self, router: ProviderRouter):
        """Test getting Mock provider"""
        provider = router._get_provider("mock")
        assert isinstance(provider, MockLLMProvider)

    def test_get_provider_unknown_raises(self, router: ProviderRouter):
        """Test getting unknown provider raises error"""
        with pytest.raises(ValueError):
            router._get_provider("unknown")

    # =========================================================================
    # Fallback Chain Tests
    # =========================================================================

    def test_fallback_chain_deepseek_no_cross(self, router_config: RouterConfig):
        """Test fallback chain for DeepSeek without cross-provider"""
        router_config.allow_cross_provider_fallback = False
        router = ProviderRouter(config=router_config)

        chain = router._build_fallback_chain("deepseek")

        # Should only have mock
        assert chain == ["mock"]

    def test_fallback_chain_glm_no_cross(self, router_config: RouterConfig):
        """Test fallback chain for GLM without cross-provider"""
        router_config.allow_cross_provider_fallback = False
        router = ProviderRouter(config=router_config)

        chain = router._build_fallback_chain("glm")

        # Should only have mock
        assert chain == ["mock"]

    def test_fallback_chain_deepseek_with_cross(self, router_config: RouterConfig):
        """Test fallback chain for DeepSeek with cross-provider"""
        router_config.allow_cross_provider_fallback = True
        router = ProviderRouter(config=router_config)

        chain = router._build_fallback_chain("deepseek")

        # Should have glm -> mock
        assert chain == ["glm", "mock"]

    def test_fallback_chain_glm_with_cross(self, router_config: RouterConfig):
        """Test fallback chain for GLM with cross-provider"""
        router_config.allow_cross_provider_fallback = True
        router = ProviderRouter(config=router_config)

        chain = router._build_fallback_chain("glm")

        # Should have deepseek -> mock
        assert chain == ["deepseek", "mock"]

    # =========================================================================
    # Analysis Type Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_event_analysis_uses_deepseek(self, router: ProviderRouter):
        """Test event analysis uses DeepSeek"""
        # Create a mock provider
        mock_provider = MagicMock(spec=DeepSeekProvider)
        mock_provider.analyze = AsyncMock(return_value=LLMResponse(
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
            confidence=0.85,
            provider="deepseek",
            latency_seconds=0.5,
        ))

        # Patch _get_provider to return mock
        with patch.object(router, "_get_provider", return_value=mock_provider):
            response = await router.analyze_event(
                prompt="Test",
                response_schema=EventAnalysisSchema,
            )

            assert response.success is True
            assert response.provider == "deepseek"

    @pytest.mark.asyncio
    async def test_rule_analysis_uses_glm(self, router: ProviderRouter):
        """Test rule analysis uses GLM"""
        mock_provider = MagicMock(spec=GLMProvider)
        mock_provider.analyze = AsyncMock(return_value=LLMResponse(
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
            confidence=0.9,
            provider="glm",
            latency_seconds=0.5,
        ))

        with patch.object(router, "_get_provider", return_value=mock_provider):
            response = await router.analyze_rule(
                prompt="Test",
                response_schema=MarketRuleSchema,
            )

            assert response.success is True
            assert response.provider == "glm"

    # =========================================================================
    # Fallback Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_fallback_to_mock_on_deepseek_failure(self, router: ProviderRouter):
        """Test fallback to Mock when DeepSeek fails"""
        # First call (deepseek) fails, second call (mock) succeeds
        call_count = [0]

        async def mock_analyze(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (deepseek) fails
                return LLMResponse(
                    success=False,
                    error="DeepSeek timeout",
                    error_type="timeout",
                    provider="deepseek",
                    latency_seconds=30.0,
                )
            else:
                # Second call (mock) succeeds
                return LLMResponse(
                    success=True,
                    parsed_output=EventAnalysisSchema(
                        event_score=50.0,
                        evidence_strength=50.0,
                        market_relevance=50.0,
                        ambiguity_risk=50.0,
                        suggested_mode="research",
                        risk_flags=["llm_fallback_neutral"],
                        explanation="Fallback to mock",
                        confidence=0.0,
                    ),
                    confidence=0.0,
                    provider="mock",
                    latency_seconds=0.1,
                )

        mock_provider = MagicMock()
        mock_provider.analyze = mock_analyze

        with patch.object(router, "_get_provider", return_value=mock_provider):
            response = await router.analyze_event(
                prompt="Test",
                response_schema=EventAnalysisSchema,
            )

            # Should have tried twice (deepseek + mock)
            assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_all_providers_failed(self, router: ProviderRouter):
        """Test all providers failed"""
        mock_provider = MagicMock()
        mock_provider.analyze = AsyncMock(return_value=LLMResponse(
            success=False,
            error="Provider failed",
            error_type="llm_error",
            provider="deepseek",
            latency_seconds=30.0,
        ))

        with patch.object(router, "_get_provider", return_value=mock_provider):
            response = await router.analyze_event(
                prompt="Test",
                response_schema=EventAnalysisSchema,
            )

            assert response.success is False
            assert response.provider == "router"

    # =========================================================================
    # Create Provider From Config Tests
    # =========================================================================

    def test_create_mock_provider(self):
        """Test creating Mock provider from config"""
        config = LLMConfig(provider=LLMProviderType.MOCK)
        provider = create_llm_provider_from_config(config)

        assert isinstance(provider, MockLLMProvider)

    def test_create_deepseek_provider(self):
        """Test creating DeepSeek provider from config"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            config = LLMConfig(provider=LLMProviderType.DEEPSEEK)
            provider = create_llm_provider_from_config(config)

            assert isinstance(provider, DeepSeekProvider)

    def test_create_glm_provider(self):
        """Test creating GLM provider from config"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            config = LLMConfig(provider=LLMProviderType.GLM)
            provider = create_llm_provider_from_config(config)

            assert isinstance(provider, GLMProvider)

    def test_create_router_provider(self):
        """Test creating Router provider from config"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key", "ZAI_API_KEY": "test-key"}):
            config = LLMConfig(provider=LLMProviderType.ROUTER)
            provider = create_llm_provider_from_config(config)

            assert isinstance(provider, ProviderRouter)

    def test_fallback_to_mock_without_api_key(self):
        """Test fallback to Mock when no API key"""
        config = LLMConfig(provider=LLMProviderType.DEEPSEEK)

        with patch.dict("os.environ", {}, clear=True):
            provider = create_llm_provider_from_config(config)

            # Should fallback to Mock because no API key
            assert isinstance(provider, MockLLMProvider)

    def test_router_fallback_to_mock_without_any_api_key(self):
        """Test Router fallback to Mock when no API keys"""
        config = LLMConfig(provider=LLMProviderType.ROUTER)

        with patch.dict("os.environ", {}, clear=True):
            provider = create_llm_provider_from_config(config)

            # Should fallback to Mock because no API keys for any provider
            assert isinstance(provider, MockLLMProvider)

    def test_env_override_provider(self):
        """Test environment variable override provider"""
        config = LLMConfig(provider=LLMProviderType.MOCK)

        with patch.dict("os.environ", {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"}):
            provider = create_llm_provider_from_config(config)

            assert isinstance(provider, DeepSeekProvider)