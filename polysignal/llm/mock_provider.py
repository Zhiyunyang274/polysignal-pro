"""
Mock LLM Provider - Deterministic mock for testing

IMPORTANT: This provider does NOT call any external API.
It produces deterministic output based on input and scenario.

Scenarios (deterministic, not random):
- success: Return valid output
- invalid_json: Return invalid JSON
- low_confidence: Return valid output with low confidence
- timeout: Simulate timeout
- schema_error: Return JSON that doesn't match schema
- missing_fields: Return JSON with missing required fields

Same input + same scenario = same output (deterministic)
"""

import hashlib
import json
import time
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from polysignal.llm.base import LLMProvider
from polysignal.models.event import (
    LLMResponse,
    check_forbidden_trading_fields,
)

T = TypeVar("T", bound=BaseModel)


class MockScenario(str, Enum):
    """
    Deterministic scenarios for Mock LLM Provider.

    These are NOT random - they must be explicitly specified.
    Same input + same scenario = same output.
    """
    SUCCESS = "success"
    INVALID_JSON = "invalid_json"
    LOW_CONFIDENCE = "low_confidence"
    TIMEOUT = "timeout"
    SCHEMA_ERROR = "schema_error"
    MISSING_FIELDS = "missing_fields"


class MockLLMProvider(LLMProvider):
    """
    Mock LLM Provider for testing.

    IMPORTANT:
    - Does NOT call any external API
    - Produces deterministic output based on input hash
    - Scenario must be explicitly specified (no random behavior)

    Same input + same scenario = same output.
    """

    def __init__(
        self,
        default_latency: float = 0.1,
        scenario: MockScenario = MockScenario.SUCCESS,
    ):
        """
        Initialize Mock LLM Provider.

        Args:
            default_latency: Simulated latency in seconds
            scenario: Deterministic scenario to use
        """
        self.default_latency = default_latency
        self.scenario = scenario
        self._call_count = 0

    def get_provider_name(self) -> str:
        """Return provider name"""
        return "mock"

    def get_status(self) -> dict:
        """Return provider status"""
        return {
            "provider": "mock",
            "scenario": self.scenario.value,
            "call_count": self._call_count,
            "default_latency": self.default_latency,
        }

    async def analyze(
        self,
        prompt: str,
        response_schema: type[T],
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> LLMResponse:
        """
        Analyze prompt and return mock response.

        This does NOT call any external API.
        Output is deterministic based on prompt hash and scenario.

        Args:
            prompt: Input prompt
            response_schema: Pydantic model for response validation
            timeout_seconds: Request timeout (simulated)
            max_retries: Maximum retry attempts (simulated)

        Returns:
            LLMResponse with mock output
        """
        self._call_count += 1
        start_time = time.time()

        # Handle timeout scenario
        if self.scenario == MockScenario.TIMEOUT:
            return LLMResponse(
                success=False,
                error="Timeout: simulated timeout",
                error_type="timeout",
                retry_count=max_retries,
                provider="mock",
                latency_seconds=timeout_seconds,
            )

        # Simulate latency
        time.sleep(self.default_latency)
        latency = time.time() - start_time

        # Generate deterministic output based on prompt hash
        prompt_hash = self._hash_prompt(prompt)

        # Handle different scenarios
        if self.scenario == MockScenario.INVALID_JSON:
            return self._handle_invalid_json(prompt_hash, latency)

        if self.scenario == MockScenario.SCHEMA_ERROR:
            return self._handle_schema_error(prompt_hash, latency)

        if self.scenario == MockScenario.MISSING_FIELDS:
            return self._handle_missing_fields(prompt_hash, latency)

        if self.scenario == MockScenario.LOW_CONFIDENCE:
            return self._handle_low_confidence(prompt, response_schema, prompt_hash, latency)

        # Default: SUCCESS scenario
        return self._handle_success(prompt, response_schema, prompt_hash, latency)

    def _hash_prompt(self, prompt: str) -> int:
        """Generate deterministic hash from prompt"""
        return int(hashlib.md5(prompt.encode()).hexdigest(), 16)

    def _handle_success(
        self,
        prompt: str,
        response_schema: type[T],
        prompt_hash: int,
        latency: float,
    ) -> LLMResponse:
        """Handle SUCCESS scenario"""
        # Generate mock output based on schema
        mock_data = self._generate_mock_data(prompt, response_schema, prompt_hash)

        # Check for forbidden trading fields
        has_forbidden, forbidden_fields = check_forbidden_trading_fields(mock_data)

        try:
            parsed = response_schema.model_validate(mock_data)
            return LLMResponse(
                success=True,
                parsed_output=parsed,
                raw_output=json.dumps(mock_data),
                confidence=mock_data.get("confidence", 0.8),
                provider="mock",
                latency_seconds=latency,
                has_forbidden_trading_fields=has_forbidden,
                forbidden_fields=forbidden_fields,
            )
        except ValidationError as e:
            return LLMResponse(
                success=False,
                raw_output=json.dumps(mock_data),
                error=f"Schema validation failed: {str(e)}",
                error_type="schema_error",
                provider="mock",
                latency_seconds=latency,
            )

    def _handle_invalid_json(self, prompt_hash: int, latency: float) -> LLMResponse:
        """Handle INVALID_JSON scenario"""
        invalid_output = f"{{invalid json {prompt_hash}}}"
        return LLMResponse(
            success=False,
            raw_output=invalid_output,
            error="Invalid JSON: cannot parse",
            error_type="invalid_json",
            provider="mock",
            latency_seconds=latency,
        )

    def _handle_schema_error(self, prompt_hash: int, latency: float) -> LLMResponse:
        """Handle SCHEMA_ERROR scenario"""
        # Return JSON with wrong types
        invalid_data = {
            "event_score": "not_a_number",  # Should be float
            "evidence_strength": "not_a_number",
            "market_relevance": "not_a_number",
            "ambiguity_risk": "not_a_number",
            "suggested_mode": 123,  # Should be string
            "confidence": "not_a_number",
        }
        return LLMResponse(
            success=False,
            raw_output=json.dumps(invalid_data),
            error="Schema validation failed: wrong types",
            error_type="schema_error",
            provider="mock",
            latency_seconds=latency,
        )

    def _handle_missing_fields(self, prompt_hash: int, latency: float) -> LLMResponse:
        """Handle MISSING_FIELDS scenario"""
        # Return JSON missing required fields
        incomplete_data = {
            "suggested_mode": "research",
            # Missing: event_score, evidence_strength, market_relevance, ambiguity_risk, confidence
        }
        return LLMResponse(
            success=False,
            raw_output=json.dumps(incomplete_data),
            error="Schema validation failed: missing required fields",
            error_type="schema_error",
            provider="mock",
            latency_seconds=latency,
        )

    def _handle_low_confidence(
        self,
        prompt: str,
        response_schema: type[T],
        prompt_hash: int,
        latency: float,
    ) -> LLMResponse:
        """Handle LOW_CONFIDENCE scenario"""
        mock_data = self._generate_mock_data(prompt, response_schema, prompt_hash)
        mock_data["confidence"] = 0.3  # Low confidence (< 0.5)

        try:
            parsed = response_schema.model_validate(mock_data)
            return LLMResponse(
                success=True,
                parsed_output=parsed,
                raw_output=json.dumps(mock_data),
                confidence=0.3,
                provider="mock",
                latency_seconds=latency,
            )
        except ValidationError as e:
            return LLMResponse(
                success=False,
                raw_output=json.dumps(mock_data),
                error=f"Schema validation failed: {str(e)}",
                error_type="schema_error",
                provider="mock",
                latency_seconds=latency,
            )

    def _generate_mock_data(
        self,
        prompt: str,
        response_schema: type[T],
        prompt_hash: int,
    ) -> dict:
        """
        Generate deterministic mock data based on prompt and schema.

        The output is deterministic: same prompt = same output.
        """
        # Use prompt hash to generate deterministic values
        base_score = 50 + (prompt_hash % 40)  # 50-89 range

        # Detect keywords in prompt for more realistic mock output
        prompt_lower = prompt.lower()

        # Default mock data
        mock_data: dict[str, Any] = {
            "event_score": float(base_score),
            "evidence_strength": float(base_score - 5),
            "market_relevance": float(base_score + 5),
            "ambiguity_risk": float(30 if "clear" in prompt_lower else 50),
            "suggested_mode": "research",
            "risk_flags": [],
            "explanation": f"Mock analysis for prompt hash {prompt_hash}",
            "confidence": 0.8,
        }

        # Adjust based on keywords
        if "ambiguous" in prompt_lower or "unclear" in prompt_lower:
            mock_data["ambiguity_risk"] = 70.0
            mock_data["suggested_mode"] = "manual_review"
            mock_data["risk_flags"].append("event_high_ambiguity")

        if "forbidden" in prompt_lower or "politics" in prompt_lower:
            mock_data["is_forbidden_category"] = True
            mock_data["suggested_mode"] = "avoid"
            mock_data["risk_flags"].append("event_forbidden_category")

        if "weak" in prompt_lower or "uncertain" in prompt_lower:
            mock_data["evidence_strength"] = 30.0
            mock_data["risk_flags"].append("event_weak_evidence")

        # For MarketRuleSchema, add additional fields
        if hasattr(response_schema, "model_fields"):
            if "rule_clarity" in response_schema.model_fields:
                mock_data["rule_clarity"] = float(base_score)
                mock_data["resolution_source_type"] = "oracle"
                mock_data["resolution_source_reliability"] = 85.0
                mock_data["has_ambiguity"] = mock_data["ambiguity_risk"] > 60
                mock_data["ambiguity_keywords"] = ["unclear"] if mock_data["has_ambiguity"] else []
                mock_data["ambiguity_explanation"] = "Detected potential ambiguity" if mock_data["has_ambiguity"] else ""
                mock_data["suggested_category"] = "crypto"
                mock_data["is_forbidden_category"] = False

        return mock_data
