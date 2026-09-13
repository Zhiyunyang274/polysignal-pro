"""
Tests for SenseNova LLM Provider

IMPORTANT: These tests mock HTTP requests, NOT real API calls.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polysignal.llm.llm_errors import (
    LLMAuthenticationError,
    LLMForbiddenFieldsError,
    LLMInvalidJSON,
    LLMProviderNotConfigured,
    LLMRateLimit,
    LLMSchemaError,
)
from polysignal.llm.schemas import EventAnalysisSchema
from polysignal.llm.sensenova_provider import (
    SenseNovaConfig,
    SenseNovaProvider,
    check_forbidden_trading_fields_in_keys,
)


class TestSenseNovaConfig:
    """Tests for SenseNovaConfig"""

    def test_default_config(self):
        """Test default configuration values"""
        config = SenseNovaConfig()

        assert config.model == "sensenova-6.7-flash-lite"
        assert config.base_url == "https://token.sensenova.cn/v1"
        assert config.timeout_seconds == 30.0
        assert config.max_retries == 2
        assert config.temperature == 0.1
        assert config.max_tokens == 2000

    def test_custom_config(self):
        """Test custom configuration values"""
        config = SenseNovaConfig(
            model="custom-model",
            base_url="https://custom.url",
            timeout_seconds=60.0,
            max_retries=5,
            temperature=0.5,
            max_tokens=4000,
        )

        assert config.model == "custom-model"
        assert config.base_url == "https://custom.url"
        assert config.timeout_seconds == 60.0
        assert config.max_retries == 5
        assert config.temperature == 0.5
        assert config.max_tokens == 4000

    def test_get_api_key_from_env(self, monkeypatch):
        """Test API key from environment variable"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-api-key-123")

        config = SenseNovaConfig()
        assert config.get_api_key() == "test-api-key-123"

    def test_get_api_key_missing(self, monkeypatch):
        """Test missing API key"""
        monkeypatch.delenv("SENSENOVA_API_KEY", raising=False)

        config = SenseNovaConfig()
        assert config.get_api_key() is None

    def test_get_model_from_env(self, monkeypatch):
        """Test model override from environment"""
        monkeypatch.setenv("SENSENOVA_MODEL", "custom-model")

        config = SenseNovaConfig()
        assert config.get_model() == "custom-model"

    def test_is_configured_true(self, monkeypatch):
        """Test is_configured returns True when API key is set"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        config = SenseNovaConfig()
        assert config.is_configured() is True

    def test_is_configured_false(self, monkeypatch):
        """Test is_configured returns False when API key is missing"""
        monkeypatch.delenv("SENSENOVA_API_KEY", raising=False)

        config = SenseNovaConfig()
        assert config.is_configured() is False


class TestForbiddenFieldsCheck:
    """Tests for forbidden trading fields check"""

    def test_no_forbidden_fields(self):
        """Test data without forbidden fields"""
        data = {"event_score": 0.8, "suggested_mode": "paper"}
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)

        assert has_forbidden is False
        assert fields == []

    def test_forbidden_field_side(self):
        """Test detection of 'side' field"""
        data = {"event_score": 0.8, "side": "buy"}
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)

        assert has_forbidden is True
        assert "side" in fields

    def test_forbidden_field_position(self):
        """Test detection of 'position' field"""
        data = {"analysis": {"position": 100}}
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)

        assert has_forbidden is True
        assert "position" in fields

    def test_forbidden_field_in_nested_list(self):
        """Test detection in nested list"""
        data = {"items": [{"order": "limit"}]}
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)

        assert has_forbidden is True
        assert "order" in fields

    def test_forbidden_field_case_insensitive(self):
        """Test case insensitive detection"""
        data = {"SIDE": "buy", "Order": "limit"}
        has_forbidden, fields = check_forbidden_trading_fields_in_keys(data)

        assert has_forbidden is True
        assert "SIDE" in fields
        assert "Order" in fields


class TestSenseNovaProvider:
    """Tests for SenseNovaProvider"""

    def test_provider_name(self, monkeypatch):
        """Test provider name"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        provider = SenseNovaProvider()
        assert provider.get_provider_name() == "sensenova"

    def test_provider_status(self, monkeypatch):
        """Test provider status"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        provider = SenseNovaProvider()
        status = provider.get_status()

        assert status["provider"] == "sensenova"
        assert status["configured"] is True
        assert status["call_count"] == 0

    def test_provider_not_configured(self, monkeypatch):
        """Test error when provider not configured"""
        monkeypatch.delenv("SENSENOVA_API_KEY", raising=False)

        provider = SenseNovaProvider()

        with pytest.raises(LLMProviderNotConfigured):
            asyncio.run(provider.analyze("test", EventAnalysisSchema))

    @pytest.mark.asyncio
    async def test_successful_analysis(self, monkeypatch):
        """Test successful analysis"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "event_score": 85.0,
                            "evidence_strength": 80.0,
                            "market_relevance": 90.0,
                            "ambiguity_risk": 20.0,
                            "suggested_mode": "research",
                            "confidence": 0.9,
                            "explanation": "Test reasoning",
                        })
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            provider = SenseNovaProvider()
            response = await provider.analyze("Test prompt", EventAnalysisSchema)

            assert response.success is True
            assert response.provider == "sensenova"
            assert response.parsed_output.event_score == 85.0

    @pytest.mark.asyncio
    async def test_authentication_error(self, monkeypatch):
        """Test authentication error"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            provider = SenseNovaProvider()

            with pytest.raises(LLMAuthenticationError):
                await provider.analyze("Test prompt", EventAnalysisSchema)

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, monkeypatch):
        """Test rate limit error"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"retry-after": "60"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            provider = SenseNovaProvider()

            with pytest.raises(LLMRateLimit):
                await provider.analyze("Test prompt", EventAnalysisSchema)

    @pytest.mark.asyncio
    async def test_invalid_json_error(self, monkeypatch):
        """Test invalid JSON error"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "not valid json"}}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            provider = SenseNovaProvider()

            with pytest.raises(LLMInvalidJSON):
                await provider.analyze("Test prompt", EventAnalysisSchema)

    @pytest.mark.asyncio
    async def test_forbidden_fields_error(self, monkeypatch):
        """Test forbidden trading fields error"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "event_score": 85.0,
                            "evidence_strength": 80.0,
                            "market_relevance": 90.0,
                            "ambiguity_risk": 20.0,
                            "suggested_mode": "research",
                            "confidence": 0.9,
                            "side": "buy",  # Forbidden field
                        })
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            provider = SenseNovaProvider()

            with pytest.raises(LLMForbiddenFieldsError):
                await provider.analyze("Test prompt", EventAnalysisSchema)

    @pytest.mark.asyncio
    async def test_schema_validation_error(self, monkeypatch):
        """Test schema validation error"""
        monkeypatch.setenv("SENSENOVA_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "invalid_field": "value",  # Missing required fields
                        })
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            provider = SenseNovaProvider()

            with pytest.raises(LLMSchemaError):
                await provider.analyze("Test prompt", EventAnalysisSchema)
