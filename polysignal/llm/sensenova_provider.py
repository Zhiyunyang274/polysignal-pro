"""
SenseNova LLM Provider - OpenAI-compatible API

IMPORTANT: This provider calls external SenseNova API.
- API key from SENSENOVA_API_KEY environment variable ONLY
- Model ID is config-driven (SENSENOVA_MODEL env override)
- Compatible with OpenAI chat/completions format
- LLM output is validated and checked for forbidden trading fields
- LLM CANNOT directly trigger trading execution

Endpoint: https://token.sensenova.cn/v1/chat/completions
Model: sensenova-6.7-flash-lite (default)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from polysignal.llm.base import LLMProvider
from polysignal.llm.llm_config import SenseNovaConfig  # single source of truth
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


class SenseNovaProvider(LLMProvider):
    """
    SenseNova LLM Provider (OpenAI-compatible).

    IMPORTANT:
    - API key from SENSENOVA_API_KEY environment variable ONLY
    - Model ID is config-driven (SENSENOVA_MODEL env override)
    - OpenAI chat/completions compatible
    - LLM output is validated and checked for forbidden trading fields
    - LLM CANNOT directly trigger trading execution
    """

    def __init__(self, config: SenseNovaConfig | None = None):
        """Initialize SenseNova provider."""
        self.config = config or SenseNovaConfig()
        self._call_count = 0

    def get_provider_name(self) -> str:
        """Return provider name"""
        return "sensenova"

    def get_status(self) -> dict:
        """Return provider status"""
        return {
            "provider": "sensenova",
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
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Analyze prompt using SenseNova API."""
        if not self.config.is_configured():
            raise LLMProviderNotConfigured(
                message="SenseNova API key not configured. Set SENSENOVA_API_KEY environment variable.",
                provider="sensenova",
            )

        self._call_count += 1
        start_time = time.time()

        timeout = timeout_seconds or self.config.timeout_seconds
        retries = max_retries if max_retries is not None else self.config.max_retries

        last_error: Exception | None = None

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
            provider="sensenova",
            latency_seconds=latency,
        )

    async def _make_request(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float,
    ) -> LLMResponse:
        """Make HTTP request to SenseNova API (OpenAI-compatible)"""
        start_time = time.time()

        # Build request body (OpenAI format)
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

                if response.status_code == 401:
                    raise LLMAuthenticationError(
                        message="SenseNova API authentication failed. Check SENSENOVA_API_KEY.",
                        provider="sensenova",
                    )

                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    raise LLMRateLimit(
                        message="SenseNova API rate limit exceeded",
                        provider="sensenova",
                        retry_after=float(retry_after) if retry_after else None,
                    )

                if response.status_code >= 500:
                    raise LLMConnectionError(
                        message=f"SenseNova API server error: {response.status_code}",
                        provider="sensenova",
                    )

                if response.status_code >= 400:
                    raise LLMConnectionError(
                        message=f"SenseNova API error: {response.status_code} - {response.text}",
                        provider="sensenova",
                    )

                response_data = response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not content:
                    return LLMResponse(
                        success=False,
                        error="Empty response from SenseNova",
                        error_type="empty_response",
                        provider="sensenova",
                        latency_seconds=latency,
                    )

                return self._parse_response(content, response_schema, latency)

        except httpx.TimeoutException as e:
            raise LLMTimeout(
                message=f"SenseNova API request timed out after {timeout_seconds}s",
                provider="sensenova",
            ) from e

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                message=f"Failed to connect to SenseNova API: {e}",
                provider="sensenova",
            ) from e

    def _build_system_prompt(self, response_schema: type[T]) -> str:
        """Build system prompt with schema requirements"""
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
            "CRITICAL: For 'suggested_mode', you MUST use EXACTLY one of these values:",
            "  'ignore', 'research', 'alert_only', 'manual_review', or 'avoid'",
            "Do NOT invent new values like 'monitor', 'observe', 'watch', etc.",
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
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMInvalidJSON(
                message=f"Invalid JSON from SenseNova: {e}",
                provider="sensenova",
                raw_output=content,
            ) from e

        has_forbidden, forbidden_fields = check_forbidden_trading_fields_in_keys(data)
        if has_forbidden:
            raise LLMForbiddenFieldsError(
                message=f"SenseNova output contains forbidden trading fields: {forbidden_fields}",
                provider="sensenova",
                forbidden_fields=forbidden_fields,
            )

        try:
            parsed = response_schema.model_validate(data)
        except ValidationError as e:
            raise LLMSchemaError(
                message=f"Schema validation failed: {e}",
                provider="sensenova",
                raw_output=content,
            ) from e

        confidence = getattr(parsed, "confidence", 0.8)

        return LLMResponse(
            success=True,
            parsed_output=parsed,
            raw_output=content,
            confidence=confidence,
            provider="sensenova",
            latency_seconds=latency,
            has_forbidden_trading_fields=False,
            forbidden_fields=[],
        )
