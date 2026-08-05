"""
LLM Provider Base - Abstract interface for LLM providers

IMPORTANT: LLM can only provide analysis and suggestions.
LLM CANNOT directly trigger trading execution.
"""

from abc import ABC, abstractmethod
from typing import Optional, TypeVar

from pydantic import BaseModel

from polysignal.models.event import LLMResponse

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """
    Abstract LLM Provider Interface.

    All LLM providers must implement this interface.

    IMPORTANT: LLM output must:
    - Be structured JSON
    - Pass Pydantic validation
    - NOT contain forbidden trading fields (side, size, order, position, buy, sell, action)
    """

    @abstractmethod
    async def analyze(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> LLMResponse:
        """
        Analyze prompt and return structured response.

        Args:
            prompt: Input prompt
            response_schema: Pydantic model for response validation
            timeout_seconds: Request timeout
            max_retries: Maximum retry attempts

        Returns:
            LLMResponse with parsed output and metadata
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider name"""
        pass

    @abstractmethod
    def get_status(self) -> dict:
        """Return provider status"""
        pass
