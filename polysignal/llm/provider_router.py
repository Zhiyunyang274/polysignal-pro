"""
Provider Router - Intelligent routing between LLM providers

IMPORTANT: This router manages fallback between providers.
- Default: DeepSeek for event analysis, GLM for rule analysis
- Fallback: Mock provider (NOT cross-provider by default)
- Cross-provider fallback only when allow_cross_provider_fallback=true

Fallback chains:
- Event analysis: DeepSeek -> Mock -> Neutral
- Rule analysis: GLM -> Mock -> Neutral
- Cross-provider (if enabled): DeepSeek <-> GLM -> Mock -> Neutral

LLM CANNOT directly trigger trading execution.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel

from polysignal.llm.base import LLMProvider
from polysignal.llm.deepseek_provider import DeepSeekProvider
from polysignal.llm.glm_provider import GLMProvider
from polysignal.llm.llm_config import (
    DeepSeekConfig,
    GLMConfig,
    LLMConfig,
    RouterConfig,
    SenseNovaConfig,
    XFyunAnthropicConfig,
)
from polysignal.llm.llm_errors import LLMError
from polysignal.llm.mock_provider import MockLLMProvider, MockScenario
from polysignal.llm.sensenova_provider import SenseNovaProvider
from polysignal.llm.xfyun_anthropic_provider import XFyunAnthropicProvider
from polysignal.models.event import LLMResponse

T = TypeVar("T", bound=BaseModel)


class AnalysisType(str, Enum):
    """Type of LLM analysis"""
    EVENT = "event"  # Event analysis (default: DeepSeek)
    RULE = "rule"    # Rule analysis (default: GLM)


class ProviderRouter(LLMProvider):
    """
    Provider Router - Routes requests to appropriate LLM provider.

    IMPORTANT:
    - Default: DeepSeek for event, GLM for rule
    - Fallback: Mock provider
    - Cross-provider fallback disabled by default
    - LLM CANNOT directly trigger trading execution
    """

    def __init__(
        self,
        config: RouterConfig | None = None,
        deepseek_config: DeepSeekConfig | None = None,
        glm_config: GLMConfig | None = None,
        sensenova_config: SenseNovaConfig | None = None,
        xfyun_anthropic_config: XFyunAnthropicConfig | None = None,
        mock_scenario: MockScenario = MockScenario.SUCCESS,
    ):
        """
        Initialize Provider Router.

        Args:
            config: Router configuration
            deepseek_config: DeepSeek provider config
            glm_config: GLM provider config
            sensenova_config: SenseNova provider config
            xfyun_anthropic_config: XFyun Anthropic provider config
            mock_scenario: Mock provider scenario
        """
        self.config = config or RouterConfig()

        # Initialize providers
        self._deepseek: DeepSeekProvider | None = None
        self._glm: GLMProvider | None = None
        self._sensenova: SenseNovaProvider | None = None
        self._xfyun_anthropic: XFyunAnthropicProvider | None = None
        self._mock: MockLLMProvider | None = None

        # Store configs for lazy initialization
        self._deepseek_config = deepseek_config
        self._glm_config = glm_config
        self._sensenova_config = sensenova_config
        self._xfyun_anthropic_config = xfyun_anthropic_config
        self._mock_scenario = mock_scenario

        self._call_count = 0

    @property
    def deepseek(self) -> DeepSeekProvider:
        """Get DeepSeek provider (lazy initialization)"""
        if self._deepseek is None:
            self._deepseek = DeepSeekProvider(config=self._deepseek_config)
        return self._deepseek

    @property
    def glm(self) -> GLMProvider:
        """Get GLM provider (lazy initialization)"""
        if self._glm is None:
            self._glm = GLMProvider(config=self._glm_config)
        return self._glm

    @property
    def sensenova(self) -> SenseNovaProvider:
        """Get SenseNova provider (lazy initialization)"""
        if self._sensenova is None:
            config = self._sensenova_config or SenseNovaConfig()
            self._sensenova = SenseNovaProvider(config=config)
        return self._sensenova

    @property
    def xfyun_anthropic(self) -> XFyunAnthropicProvider:
        """Get XFyun Anthropic provider (lazy initialization)"""
        if self._xfyun_anthropic is None:
            config = self._xfyun_anthropic_config or XFyunAnthropicConfig()
            self._xfyun_anthropic = XFyunAnthropicProvider(config=config)
        return self._xfyun_anthropic

    @property
    def mock(self) -> MockLLMProvider:
        """Get Mock provider (lazy initialization)"""
        if self._mock is None:
            self._mock = MockLLMProvider(scenario=self._mock_scenario)
        return self._mock

    def get_provider_name(self) -> str:
        """Return provider name"""
        return "router"

    def get_status(self) -> dict:
        """Return provider status"""
        return {
            "provider": "router",
            "default_event_provider": self.config.default_event_provider,
            "default_rule_provider": self.config.default_rule_provider,
            "fallback_provider": self.config.fallback_provider,
            "allow_cross_provider_fallback": self.config.allow_cross_provider_fallback,
            "call_count": self._call_count,
            "deepseek_configured": self.deepseek.config.is_configured() if self._deepseek else False,
            "glm_configured": self.glm.config.is_configured() if self._glm else False,
            "sensenova_configured": self.sensenova.config.is_configured() if self._sensenova else False,
            "xfyun_anthropic_configured": self.xfyun_anthropic.config.is_configured() if self._xfyun_anthropic else False,
        }

    async def analyze(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        analysis_type: AnalysisType = AnalysisType.EVENT,
    ) -> LLMResponse:
        """
        Analyze prompt using appropriate provider.

        Args:
            prompt: Input prompt
            response_schema: Pydantic model for response validation
            timeout_seconds: Request timeout
            max_retries: Maximum retry attempts
            analysis_type: Type of analysis (event or rule)

        Returns:
            LLMResponse with parsed output and metadata
        """
        self._call_count += 1
        start_time = time.time()

        # Select primary provider based on analysis type
        primary_provider_name = (
            self.config.default_event_provider
            if analysis_type == AnalysisType.EVENT
            else self.config.default_rule_provider
        )

        # Get primary provider
        primary_provider = self._get_provider(primary_provider_name)

        # Build fallback chain
        fallback_chain = self._build_fallback_chain(primary_provider_name)

        # Try primary provider
        last_response: LLMResponse | None = None

        try:
            response = await primary_provider.analyze(
                prompt=prompt,
                response_schema=response_schema,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )

            if response.success:
                return response

            last_response = response

        except LLMError as e:
            # Provider error, try fallback
            last_response = LLMResponse(
                success=False,
                error=str(e),
                error_type=e.error_type,
                provider=e.provider,
                latency_seconds=time.time() - start_time,
            )

        # Try fallback providers
        for fallback_name in fallback_chain:
            try:
                fallback_provider = self._get_provider(fallback_name)

                response = await fallback_provider.analyze(
                    prompt=prompt,
                    response_schema=response_schema,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                )

                if response.success:
                    # Add fallback info to response
                    response.fallback_from = primary_provider_name
                    return response

                last_response = response

            except LLMError as e:
                last_response = LLMResponse(
                    success=False,
                    error=str(e),
                    error_type=e.error_type,
                    provider=e.provider,
                    latency_seconds=time.time() - start_time,
                )
                continue

        # All providers failed, return last error
        latency = time.time() - start_time
        return LLMResponse(
            success=False,
            error=last_response.error if last_response else "All providers failed",
            error_type=last_response.error_type if last_response else "all_providers_failed",
            provider="router",
            latency_seconds=latency,
        )

    def _get_provider(self, name: str) -> LLMProvider:
        """Get provider by name"""
        if name == "deepseek":
            return self.deepseek
        elif name == "glm":
            return self.glm
        elif name == "sensenova":
            return self.sensenova
        elif name == "xfyun_anthropic":
            return self.xfyun_anthropic
        elif name == "mock":
            return self.mock
        else:
            raise ValueError(f"Unknown provider: {name}")

    def _build_fallback_chain(self, primary_provider: str) -> list[str]:
        """
        Build fallback chain for a provider.

        Default (allow_cross_provider_fallback=False):
        - DeepSeek -> Mock
        - GLM -> Mock

        Cross-provider enabled (allow_cross_provider_fallback=True):
        - DeepSeek -> GLM -> Mock
        - GLM -> DeepSeek -> Mock
        """
        chain = []

        # Always add mock as final fallback
        chain.append("mock")

        # Add cross-provider fallback if enabled
        if self.config.allow_cross_provider_fallback:
            if primary_provider == "deepseek":
                chain.insert(0, "glm")
            elif primary_provider == "glm":
                chain.insert(0, "deepseek")

        return chain

    async def analyze_event(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> LLMResponse:
        """
        Analyze event (convenience method).

        Uses default_event_provider.
        """
        return await self.analyze(
            prompt=prompt,
            response_schema=response_schema,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            analysis_type=AnalysisType.EVENT,
        )

    async def analyze_rule(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> LLMResponse:
        """
        Analyze rule (convenience method).

        Uses default_rule_provider.
        """
        return await self.analyze(
            prompt=prompt,
            response_schema=response_schema,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            analysis_type=AnalysisType.RULE,
        )


def create_llm_provider_from_config(
    config: LLMConfig,
) -> LLMProvider:
    """
    Create LLM provider from configuration.

    Args:
        config: LLM configuration

    Returns:
        LLMProvider instance
    """
    from polysignal.llm.llm_config import LLMProviderType

    effective_provider = config.get_effective_provider()

    if effective_provider == LLMProviderType.MOCK:
        return MockLLMProvider(scenario=MockScenario(config.mock.scenario))

    elif effective_provider == LLMProviderType.DEEPSEEK:
        return DeepSeekProvider(config=config.deepseek)

    elif effective_provider in (LLMProviderType.GLM, LLMProviderType.ZAI):
        return GLMProvider(config=config.glm)

    elif effective_provider == LLMProviderType.SENSENOVA:
        return SenseNovaProvider(config=config.sensenova)

    elif effective_provider == LLMProviderType.XFYUN_ANTHROPIC:
        return XFyunAnthropicProvider(config=config.xfyun_anthropic)

    elif effective_provider == LLMProviderType.ROUTER:
        return ProviderRouter(
            config=config.router,
            deepseek_config=config.deepseek,
            glm_config=config.glm,
            sensenova_config=config.sensenova,
            xfyun_anthropic_config=config.xfyun_anthropic,
            mock_scenario=MockScenario(config.mock.scenario),
        )

    else:
        # Fallback to mock
        return MockLLMProvider(scenario=MockScenario(config.mock.scenario))