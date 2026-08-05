"""
XFyun Anthropic LLM Provider - Anthropic-compatible API

IMPORTANT: This provider calls external XFyun/MaaS API.
- API key from XFYUN_API_KEY environment variable ONLY
- Model ID is config-driven (XFYUN_MODEL env override)
- Compatible with Anthropic Messages API format
- LLM output is validated and checked for forbidden trading fields
- LLM CANNOT directly trigger trading execution

Endpoint: https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic
Model: astron-code-latest (default)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from polysignal.llm.base import LLMProvider
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
    """
    found = []

    def _check_keys(obj: dict | list, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in FORBIDDEN_TRADING_FIELDS:
                    found.append(key)
                _check_keys(value, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _check_keys(item, f"{path}[{i}]")

    _check_keys(data)
    return len(found) > 0, found


class XFyunAnthropicConfig:
    """XFyun Anthropic provider configuration"""

    def __init__(
        self,
        model: str = "astron-code-latest",
        base_url: str = "https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ):
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens

    def get_api_key(self) -> Optional[str]:
        """Get API key from environment variable"""
        import os
        return os.environ.get("XFYUN_API_KEY")

    def get_model(self) -> str:
        """Get model ID (env override takes precedence)"""
        import os
        env_model = os.environ.get("XFYUN_MODEL")
        return env_model if env_model else self.model

    def is_configured(self) -> bool:
        """Check if provider is configured (has API key)"""
        return self.get_api_key() is not None


class XFyunAnthropicProvider(LLMProvider):
    """
    XFyun Anthropic LLM Provider.

    IMPORTANT:
    - API key from XFYUN_API_KEY environment variable ONLY
    - Model ID is config-driven (XFYUN_MODEL env override)
    - Anthropic Messages API compatible
    - LLM output is validated and checked for forbidden trading fields
    - LLM CANNOT directly trigger trading execution
    """

    def __init__(self, config: Optional[XFyunAnthropicConfig] = None):
        """Initialize XFyun Anthropic provider."""
        self.config = config or XFyunAnthropicConfig()
        self._call_count = 0

    def get_provider_name(self) -> str:
        """Return provider name"""
        return "xfyun_anthropic"

    def get_status(self) -> dict:
        """Return provider status"""
        return {
            "provider": "xfyun_anthropic",
            "model": self.config.get_model(),
            "configured": self.config.is_configured(),
            "call_count": self._call_count,
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
        }

    async def analyze(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> LLMResponse:
        """Analyze prompt using XFyun Anthropic API."""
        if not self.config.is_configured():
            raise LLMProviderNotConfigured(
                message="XFyun API key not configured. Set XFYUN_API_KEY environment variable.",
                provider="xfyun_anthropic",
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
                    wait_time = e.retry_after or (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                raise

            except (LLMTimeout, LLMConnectionError) as e:
                last_error = e
                if attempt < retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

            except (LLMAuthenticationError, LLMInvalidJSON, LLMSchemaError, LLMForbiddenFieldsError):
                raise

        latency = time.time() - start_time
        return LLMResponse(
            success=False,
            error=str(last_error) if last_error else "Max retries exceeded",
            error_type="max_retries_exceeded",
            retry_count=retries,
            provider="xfyun_anthropic",
            latency_seconds=latency,
        )

    async def _make_request(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float,
    ) -> LLMResponse:
        """Make HTTP request to XFyun Anthropic API"""
        start_time = time.time()

        # Build request body (Anthropic Messages API format)
        request_body = {
            "model": self.config.get_model(),
            "max_tokens": self.config.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": self._build_user_prompt(prompt, response_schema),
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.config.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.config.get_api_key(),
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json=request_body,
                )

                latency = time.time() - start_time

                if response.status_code == 401:
                    raise LLMAuthenticationError(
                        message="XFyun API authentication failed. Check XFYUN_API_KEY.",
                        provider="xfyun_anthropic",
                    )

                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    raise LLMRateLimit(
                        message="XFyun API rate limit exceeded",
                        provider="xfyun_anthropic",
                        retry_after=float(retry_after) if retry_after else None,
                    )

                if response.status_code >= 500:
                    raise LLMConnectionError(
                        message=f"XFyun API server error: {response.status_code}",
                        provider="xfyun_anthropic",
                    )

                if response.status_code >= 400:
                    raise LLMConnectionError(
                        message=f"XFyun API error: {response.status_code} - {response.text}",
                        provider="xfyun_anthropic",
                    )

                response_data = response.json()

                # Anthropic response format
                content_blocks = response_data.get("content", [])
                content = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        content += block.get("text", "")

                if not content:
                    return LLMResponse(
                        success=False,
                        error="Empty response from XFyun",
                        error_type="empty_response",
                        provider="xfyun_anthropic",
                        latency_seconds=latency,
                    )

                return self._parse_response(content, response_schema, latency)

        except httpx.TimeoutException:
            raise LLMTimeout(
                message=f"XFyun API request timed out after {timeout_seconds}s",
                provider="xfyun_anthropic",
            )

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                message=f"Failed to connect to XFyun API: {e}",
                provider="xfyun_anthropic",
            )

    def _build_user_prompt(self, prompt: str, response_schema: type[T]) -> str:
        """Build user prompt with schema requirements"""
        schema_json = response_schema.model_json_schema()

        field_descriptions = []
        for field_name, field_info in schema_json.get("properties", {}).items():
            desc = field_info.get("description", field_name)
            # Add enum values if present
            if "enum" in field_info:
                enum_values = ", ".join(repr(v) for v in field_info["enum"])
                field_descriptions.append(f"- {field_name}: {desc} (MUST be one of: {enum_values})")
            else:
                field_descriptions.append(f"- {field_name}: {desc}")

        return "\n".join([
            "You are a market analysis assistant.",
            "Analyze the given market and provide structured output.",
            "",
            "IMPORTANT OUTPUT REQUIREMENTS:",
            "1. Output MUST be valid JSON only (no markdown, no code blocks)",
            "2. Output MUST match the following schema:",
            "\n".join(field_descriptions),
            "",
            "CRITICAL ENUM VALUES - You MUST use EXACTLY these values:",
            "- suggested_mode: 'ignore', 'research', 'alert_only', 'manual_review', or 'avoid'",
            "- resolution_source_type: 'oracle', 'uma', 'manual', 'committee', or 'unknown'",
            "Do NOT invent new values. Use only the exact values listed above.",
            "",
            "FORBIDDEN: Do NOT include these fields in your output:",
            "- side, size, order, position, buy, sell, action",
            "",
            "These fields are NOT allowed because LLM cannot make trading decisions.",
            "",
            "Your response must be pure JSON, starting with { and ending with }.",
            "",
            "---",
            "",
            prompt,
        ])

    def _parse_response(
        self,
        content: str,
        response_schema: type[T],
        latency: float,
    ) -> LLMResponse:
        """Parse and validate LLM response"""
        # Clean potential markdown code blocks
        cleaned_content = content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        try:
            data = json.loads(cleaned_content)
        except json.JSONDecodeError as e:
            raise LLMInvalidJSON(
                message=f"Invalid JSON from XFyun: {e}",
                provider="xfyun_anthropic",
                raw_output=content,
            )

        has_forbidden, forbidden_fields = check_forbidden_trading_fields_in_keys(data)
        if has_forbidden:
            raise LLMForbiddenFieldsError(
                message=f"XFyun output contains forbidden trading fields: {forbidden_fields}",
                provider="xfyun_anthropic",
                forbidden_fields=forbidden_fields,
            )

        try:
            parsed = response_schema.model_validate(data)
        except ValidationError as e:
            raise LLMSchemaError(
                message=f"Schema validation failed: {e}",
                provider="xfyun_anthropic",
                raw_output=content,
            )

        confidence = getattr(parsed, "confidence", 0.8)

        return LLMResponse(
            success=True,
            parsed_output=parsed,
            raw_output=content,
            confidence=confidence,
            provider="xfyun_anthropic",
            latency_seconds=latency,
            has_forbidden_trading_fields=False,
            forbidden_fields=[],
        )
