"""
GLM/Z.AI LLM Provider - Implementation for GLM/Z.AI API

IMPORTANT: This provider calls external GLM/Z.AI API.
- API key from ZAI_API_KEY (preferred) or GLM_API_KEY environment variable
- Model ID is config-driven (ZAI_MODEL preferred, GLM_MODEL fallback)
- Default model is glm-5 (NOT glm-4-flash)
- GLM may not support response_format JSON mode, uses prompt constraint
- LLM output is validated and checked for forbidden trading fields
- LLM CANNOT directly trigger trading execution

Environment variables:
- ZAI_API_KEY: Z.AI API key (preferred)
- GLM_API_KEY: GLM API key (fallback)
- ZAI_MODEL: Model override (preferred)
- GLM_MODEL: Model override (fallback)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from polysignal.llm.base import LLMProvider
from polysignal.llm.llm_config import GLMConfig
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


class GLMProvider(LLMProvider):
    """
    GLM/Z.AI LLM Provider.

    IMPORTANT:
    - API key from ZAI_API_KEY (preferred) or GLM_API_KEY environment variable
    - Model ID is config-driven (ZAI_MODEL preferred, GLM_MODEL fallback)
    - Default model is glm-5 (NOT glm-4-flash)
    - May not support response_format JSON mode, uses prompt constraint
    - LLM output is validated and checked for forbidden trading fields
    - LLM CANNOT directly trigger trading execution
    """

    def __init__(self, config: Optional[GLMConfig] = None):
        """
        Initialize GLM/Z.AI provider.

        Args:
            config: GLM configuration (default: from defaults)
        """
        self.config = config or GLMConfig()
        self._call_count = 0

    def get_provider_name(self) -> str:
        """Return provider name"""
        return "glm"

    def get_status(self) -> dict:
        """Return provider status"""
        return {
            "provider": "glm",
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
        Analyze prompt using GLM/Z.AI API.

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
                message="GLM/Z.AI API key not configured. Set ZAI_API_KEY or GLM_API_KEY environment variable.",
                provider="glm",
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
            provider="glm",
            latency_seconds=latency,
        )

    async def _make_request(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float,
    ) -> LLMResponse:
        """Make HTTP request to GLM/Z.AI API"""
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

        # GLM may not support response_format, so we rely on prompt constraint
        # If supports_json_mode is True, we can try adding it
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
                        message="GLM/Z.AI API authentication failed. Check ZAI_API_KEY or GLM_API_KEY.",
                        provider="glm",
                    )

                if response.status_code == 429:
                    # Try to get retry-after header
                    retry_after = response.headers.get("retry-after")
                    raise LLMRateLimit(
                        message="GLM/Z.AI API rate limit exceeded",
                        provider="glm",
                        retry_after=float(retry_after) if retry_after else None,
                    )

                if response.status_code >= 500:
                    raise LLMConnectionError(
                        message=f"GLM/Z.AI API server error: {response.status_code}",
                        provider="glm",
                    )

                if response.status_code >= 400:
                    raise LLMConnectionError(
                        message=f"GLM/Z.AI API error: {response.status_code} - {response.text}",
                        provider="glm",
                    )

                # Parse response
                response_data = response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not content:
                    return LLMResponse(
                        success=False,
                        error="Empty response from GLM/Z.AI",
                        error_type="empty_response",
                        provider="glm",
                        latency_seconds=latency,
                    )

                # Parse and validate JSON
                return self._parse_response(content, response_schema, latency)

        except httpx.TimeoutException:
            raise LLMTimeout(
                message=f"GLM/Z.AI API request timed out after {timeout_seconds}s",
                provider="glm",
            )

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                message=f"Failed to connect to GLM/Z.AI API: {e}",
                provider="glm",
            )

    def _build_system_prompt(self, response_schema: type[T]) -> str:
        """
        Build system prompt with schema requirements.

        GLM may not support response_format JSON mode, so we use
        strong prompt constraint to ensure JSON output.
        """
        schema_json = response_schema.model_json_schema()

        # Build field descriptions
        field_descriptions = []
        for field_name, field_info in schema_json.get("properties", {}).items():
            desc = field_info.get("description", field_name)
            field_type = field_info.get("type", "unknown")
            field_descriptions.append(f"- {field_name} ({field_type}): {desc}")

        # Strong JSON constraint for GLM
        return "\n".join([
            "You are a market analysis assistant.",
            "Analyze the given market and provide structured output.",
            "",
            "CRITICAL OUTPUT REQUIREMENTS:",
            "1. Output MUST be valid JSON only (no markdown, no code blocks)",
            "2. Output MUST match the following schema exactly:",
            "\n".join(field_descriptions),
            "",
            "FORBIDDEN: Do NOT include these fields in your output:",
            "- side, size, order, position, buy, sell, action",
            "",
            "These fields are NOT allowed because LLM cannot make trading decisions.",
            "",
            "Your response must be pure JSON, starting with { and ending with }.",
        ])

    def _parse_response(
        self,
        content: str,
        response_schema: type[T],
        latency: float,
    ) -> LLMResponse:
        """Parse and validate LLM response"""
        # Clean potential markdown code blocks (GLM might wrap JSON)
        cleaned_content = content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        # Try to parse JSON
        try:
            data = json.loads(cleaned_content)
        except json.JSONDecodeError as e:
            raise LLMInvalidJSON(
                message=f"Invalid JSON from GLM/Z.AI: {e}",
                provider="glm",
                raw_output=content,
            )

        # Check for forbidden trading fields (JSON keys only)
        has_forbidden, forbidden_fields = check_forbidden_trading_fields_in_keys(data)
        if has_forbidden:
            raise LLMForbiddenFieldsError(
                message=f"GLM/Z.AI output contains forbidden trading fields: {forbidden_fields}",
                provider="glm",
                forbidden_fields=forbidden_fields,
            )

        # Validate against schema
        try:
            parsed = response_schema.model_validate(data)
        except ValidationError as e:
            raise LLMSchemaError(
                message=f"Schema validation failed: {e}",
                provider="glm",
                raw_output=content,
            )

        # Get confidence from parsed output
        confidence = getattr(parsed, "confidence", 0.8)

        return LLMResponse(
            success=True,
            parsed_output=parsed,
            raw_output=content,
            confidence=confidence,
            provider="glm",
            latency_seconds=latency,
            has_forbidden_trading_fields=False,
            forbidden_fields=[],
        )