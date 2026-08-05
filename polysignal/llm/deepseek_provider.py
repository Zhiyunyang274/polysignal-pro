"""
DeepSeek LLM Provider - Implementation for DeepSeek API

IMPORTANT: This provider calls external DeepSeek API.
- API key is loaded from DEEPSEEK_API_KEY environment variable ONLY
- Model ID is config-driven (DEEPSEEK_MODEL env override)
- LLM output is validated and checked for forbidden trading fields
- LLM CANNOT directly trigger trading execution

Model selection:
- Default: deepseek-chat (config-driven)
- Override: DEEPSEEK_MODEL environment variable
- User can specify DeepSeek V4 Flash via DEEPSEEK_MODEL
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from polysignal.llm.base import LLMProvider
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
from polysignal.models.event import LLMResponse

T = TypeVar("T", bound=BaseModel)


# Forbidden trading fields (checked in JSON keys only)
FORBIDDEN_TRADING_FIELDS = {
    "side",
    "size",
    "order",
    "position",
    "buy",
    "sell",
    "action",
}


def check_forbidden_trading_fields_in_keys(data: dict) -> tuple[bool, list[str]]:
    """
    Check if data contains forbidden trading fields as JSON keys.

    IMPORTANT: This only checks JSON keys, NOT text values.
    If "side" appears in an explanation string, it's NOT flagged.
    If "side" appears as a JSON key, it IS flagged.

    Args:
        data: Dictionary to check

    Returns:
        Tuple of (has_forbidden, list of forbidden field names)
    """
    found = []

    def _check_keys(obj: dict | list, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Check if key is a forbidden field (case-insensitive)
                if key.lower() in FORBIDDEN_TRADING_FIELDS:
                    found.append(key)
                # Recursively check nested structures
                _check_keys(value, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _check_keys(item, f"{path}[{i}]")

    _check_keys(data)
    return len(found) > 0, found


class DeepSeekProvider(LLMProvider):
    """
    DeepSeek LLM Provider.

    IMPORTANT:
    - API key from DEEPSEEK_API_KEY environment variable ONLY
    - Model ID is config-driven (DEEPSEEK_MODEL env override)
    - Supports JSON mode via response_format
    - LLM output is validated and checked for forbidden trading fields
    - LLM CANNOT directly trigger trading execution
    """

    def __init__(self, config: Optional[DeepSeekConfig] = None):
        """
        Initialize DeepSeek provider.

        Args:
            config: DeepSeek configuration (default: from defaults)
        """
        self.config = config or DeepSeekConfig()
        self._call_count = 0

    def get_provider_name(self) -> str:
        """Return provider name"""
        return "deepseek"

    def get_status(self) -> dict:
        """Return provider status"""
        return {
            "provider": "deepseek",
            "model": self.config.get_model(),
            "configured": self.config.is_configured(),
            "call_count": self._call_count,
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
            "supports_json_mode": self.config.supports_json_mode,
        }

    async def analyze(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> LLMResponse:
        """
        Analyze prompt using DeepSeek API.

        Args:
            prompt: Input prompt
            response_schema: Pydantic model for response validation
            timeout_seconds: Request timeout (default: from config)
            max_retries: Maximum retry attempts (default: from config)

        Returns:
            LLMResponse with parsed output and metadata
        """
        # Check if configured
        if not self.config.is_configured():
            raise LLMProviderNotConfigured(
                message="DeepSeek API key not configured. Set DEEPSEEK_API_KEY environment variable.",
                provider="deepseek",
            )

        self._call_count += 1
        start_time = time.time()

        timeout = timeout_seconds or self.config.timeout_seconds
        retries = max_retries if max_retries is not None else self.config.max_retries

        last_error: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                result = await self._make_request(
                    prompt=prompt,
                    response_schema=response_schema,
                    timeout_seconds=timeout,
                )
                return result

            except LLMRateLimit as e:
                last_error = e
                if attempt < retries:
                    # Wait before retry
                    wait_time = e.retry_after or (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                # No more retries, raise the error
                raise

            except (LLMTimeout, LLMConnectionError) as e:
                last_error = e
                if attempt < retries:
                    # Wait before retry
                    await asyncio.sleep(2 ** attempt)
                    continue
                # No more retries, raise the error
                raise

            except (LLMAuthenticationError, LLMInvalidJSON, LLMSchemaError, LLMForbiddenFieldsError):
                # Don't retry these errors
                raise

        # All retries exhausted (should not reach here, but just in case)
        latency = time.time() - start_time
        return LLMResponse(
            success=False,
            error=str(last_error) if last_error else "Max retries exceeded",
            error_type="max_retries_exceeded",
            retry_count=retries,
            provider="deepseek",
            latency_seconds=latency,
        )

    async def _make_request(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float,
    ) -> LLMResponse:
        """Make HTTP request to DeepSeek API"""
        start_time = time.time()

        # Build request body
        request_body = {
            "model": self.config.get_model(),
            "messages": [
                {
                    "role": "system",
                    "content": self._build_system_prompt(response_schema),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        # Add JSON mode if supported
        if self.config.supports_json_mode:
            request_body["response_format"] = {"type": "json_object"}

        # Make HTTP request
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.config.get_api_key()}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )

                latency = time.time() - start_time

                # Handle HTTP errors
                if response.status_code == 401:
                    raise LLMAuthenticationError(
                        message="DeepSeek API authentication failed. Check DEEPSEEK_API_KEY.",
                        provider="deepseek",
                    )

                if response.status_code == 429:
                    # Try to get retry-after header
                    retry_after = response.headers.get("retry-after")
                    raise LLMRateLimit(
                        message="DeepSeek API rate limit exceeded",
                        provider="deepseek",
                        retry_after=float(retry_after) if retry_after else None,
                    )

                if response.status_code >= 500:
                    raise LLMConnectionError(
                        message=f"DeepSeek API server error: {response.status_code}",
                        provider="deepseek",
                    )

                if response.status_code >= 400:
                    raise LLMConnectionError(
                        message=f"DeepSeek API error: {response.status_code} - {response.text}",
                        provider="deepseek",
                    )

                # Parse response
                response_data = response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not content:
                    return LLMResponse(
                        success=False,
                        error="Empty response from DeepSeek",
                        error_type="empty_response",
                        provider="deepseek",
                        latency_seconds=latency,
                    )

                # Parse and validate JSON
                return self._parse_response(content, response_schema, latency)

        except httpx.TimeoutException:
            raise LLMTimeout(
                message=f"DeepSeek API request timed out after {timeout_seconds}s",
                provider="deepseek",
            )

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                message=f"Failed to connect to DeepSeek API: {e}",
                provider="deepseek",
            )

    def _build_system_prompt(self, response_schema: type[T]) -> str:
        """Build system prompt with schema requirements"""
        schema_json = response_schema.model_json_schema()

        # Build field descriptions
        field_descriptions = []
        for field_name, field_info in schema_json.get("properties", {}).items():
            desc = field_info.get("description", field_name)
            field_descriptions.append(f"- {field_name}: {desc}")

        return "\n".join([
            "You are a market analysis assistant.",
            "Analyze the given market and provide structured output.",
            "",
            "IMPORTANT OUTPUT REQUIREMENTS:",
            "1. Output MUST be valid JSON",
            "2. Output MUST match the following schema:",
            "\n".join(field_descriptions),
            "",
            "FORBIDDEN: Do NOT include these fields in your output:",
            "- side, size, order, position, buy, sell, action",
            "",
            "These fields are NOT allowed because LLM cannot make trading decisions.",
        ])

    def _parse_response(
        self,
        content: str,
        response_schema: type[T],
        latency: float,
    ) -> LLMResponse:
        """Parse and validate LLM response"""
        # Try to parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMInvalidJSON(
                message=f"Invalid JSON from DeepSeek: {e}",
                provider="deepseek",
                raw_output=content,
            )

        # Check for forbidden trading fields (JSON keys only)
        has_forbidden, forbidden_fields = check_forbidden_trading_fields_in_keys(data)
        if has_forbidden:
            raise LLMForbiddenFieldsError(
                message=f"DeepSeek output contains forbidden trading fields: {forbidden_fields}",
                provider="deepseek",
                forbidden_fields=forbidden_fields,
            )

        # Validate against schema
        try:
            parsed = response_schema.model_validate(data)
        except ValidationError as e:
            raise LLMSchemaError(
                message=f"Schema validation failed: {e}",
                provider="deepseek",
                raw_output=content,
            )

        # Get confidence from parsed output
        confidence = getattr(parsed, "confidence", 0.8)

        return LLMResponse(
            success=True,
            parsed_output=parsed,
            raw_output=content,
            confidence=confidence,
            provider="deepseek",
            latency_seconds=latency,
            has_forbidden_trading_fields=False,
            forbidden_fields=[],
        )
