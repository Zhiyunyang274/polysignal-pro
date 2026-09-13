"""
Tests for LLM Configuration

IMPORTANT: Tests verify configuration loading and environment variable handling.
"""

import os
import tempfile
from unittest.mock import patch

from polysignal.llm.llm_config import (
    DeepSeekConfig,
    GLMConfig,
    LLMConfig,
    LLMProviderType,
    RouterConfig,
    ValidationConfig,
    load_llm_config,
)


class TestDeepSeekConfig:
    """Test DeepSeek Configuration"""

    def test_default_model(self):
        """Test default model"""
        config = DeepSeekConfig()
        assert config.model == "deepseek-chat"

    def test_model_override_from_env(self):
        """Test model override from environment"""
        with patch.dict("os.environ", {"DEEPSEEK_MODEL": "deepseek-v4-flash"}):
            config = DeepSeekConfig()
            assert config.get_model() == "deepseek-v4-flash"

    def test_model_default_without_env(self):
        """Test default model without env override"""
        with patch.dict("os.environ", {}, clear=True):
            config = DeepSeekConfig()
            assert config.get_model() == "deepseek-chat"

    def test_api_key_from_env(self):
        """Test API key from environment"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key-123"}):
            config = DeepSeekConfig()
            assert config.get_api_key() == "test-key-123"

    def test_api_key_none_without_env(self):
        """Test API key is None without env"""
        with patch.dict("os.environ", {}, clear=True):
            config = DeepSeekConfig()
            assert config.get_api_key() is None

    def test_is_configured_with_key(self):
        """Test is_configured returns True with key"""
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            config = DeepSeekConfig()
            assert config.is_configured() is True

    def test_is_configured_without_key(self):
        """Test is_configured returns False without key"""
        with patch.dict("os.environ", {}, clear=True):
            config = DeepSeekConfig()
            assert config.is_configured() is False

    def test_default_timeout(self):
        """Test default timeout"""
        config = DeepSeekConfig()
        assert config.timeout_seconds == 30.0

    def test_default_max_retries(self):
        """Test default max retries"""
        config = DeepSeekConfig()
        assert config.max_retries == 2

    def test_supports_json_mode(self):
        """Test supports_json_mode default"""
        config = DeepSeekConfig()
        assert config.supports_json_mode is True


class TestGLMConfig:
    """Test GLM/Z.AI Configuration"""

    def test_default_model_is_glm5(self):
        """Test default model is glm-5 (NOT glm-4-flash)"""
        config = GLMConfig()
        assert config.model == "glm-5"

    def test_api_key_zai_preferred(self):
        """Test ZAI_API_KEY takes precedence"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "zai-key", "GLM_API_KEY": "glm-key"}):
            config = GLMConfig()
            assert config.get_api_key() == "zai-key"

    def test_api_key_glm_fallback(self):
        """Test GLM_API_KEY as fallback"""
        with patch.dict("os.environ", {"GLM_API_KEY": "glm-key"}, clear=True):
            config = GLMConfig()
            assert config.get_api_key() == "glm-key"

    def test_model_zai_preferred(self):
        """Test ZAI_MODEL takes precedence"""
        with patch.dict("os.environ", {"ZAI_MODEL": "glm-5-flash", "GLM_MODEL": "glm-4"}):
            config = GLMConfig()
            assert config.get_model() == "glm-5-flash"

    def test_model_glm_fallback(self):
        """Test GLM_MODEL as fallback"""
        with patch.dict("os.environ", {"GLM_MODEL": "glm-4-flash"}, clear=True):
            config = GLMConfig()
            assert config.get_model() == "glm-4-flash"

    def test_model_default_without_env(self):
        """Test default model without env override"""
        with patch.dict("os.environ", {}, clear=True):
            config = GLMConfig()
            assert config.get_model() == "glm-5"

    def test_is_configured_with_zai_key(self):
        """Test is_configured with ZAI_API_KEY"""
        with patch.dict("os.environ", {"ZAI_API_KEY": "test-key"}):
            config = GLMConfig()
            assert config.is_configured() is True

    def test_is_configured_with_glm_key(self):
        """Test is_configured with GLM_API_KEY"""
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            config = GLMConfig()
            assert config.is_configured() is True

    def test_is_configured_without_key(self):
        """Test is_configured without key"""
        with patch.dict("os.environ", {}, clear=True):
            config = GLMConfig()
            assert config.is_configured() is False

    def test_supports_json_mode_false(self):
        """Test supports_json_mode default is False"""
        config = GLMConfig()
        assert config.supports_json_mode is False


class TestRouterConfig:
    """Test Router Configuration"""

    def test_default_event_provider(self):
        """Test default event provider"""
        config = RouterConfig()
        assert config.default_event_provider == "deepseek"

    def test_default_rule_provider(self):
        """Test default rule provider"""
        config = RouterConfig()
        assert config.default_rule_provider == "glm"

    def test_fallback_provider(self):
        """Test fallback provider"""
        config = RouterConfig()
        assert config.fallback_provider == "mock"

    def test_cross_provider_fallback_disabled(self):
        """Test cross-provider fallback disabled by default"""
        config = RouterConfig()
        assert config.allow_cross_provider_fallback is False


class TestValidationConfig:
    """Test Validation Configuration"""

    def test_forbidden_fields(self):
        """Test forbidden fields"""
        config = ValidationConfig()
        assert "side" in config.forbidden_fields
        assert "size" in config.forbidden_fields
        assert "order" in config.forbidden_fields
        assert "position" in config.forbidden_fields
        assert "buy" in config.forbidden_fields
        assert "sell" in config.forbidden_fields
        assert "action" in config.forbidden_fields

    def test_min_confidence(self):
        """Test min confidence"""
        config = ValidationConfig()
        assert config.min_confidence == 0.5

    def test_require_json(self):
        """Test require_json"""
        config = ValidationConfig()
        assert config.require_json is True

    def test_require_confidence(self):
        """Test require_confidence"""
        config = ValidationConfig()
        assert config.require_confidence is True


class TestLLMConfig:
    """Test Top-level LLM Configuration"""

    def test_default_provider_is_mock(self):
        """Test default provider is mock"""
        config = LLMConfig()
        assert config.provider == LLMProviderType.MOCK

    def test_get_effective_provider_mock(self):
        """Test effective provider is mock by default"""
        with patch.dict("os.environ", {}, clear=True):
            config = LLMConfig()
            assert config.get_effective_provider() == LLMProviderType.MOCK

    def test_get_effective_provider_env_override(self):
        """Test environment variable override"""
        with patch.dict("os.environ", {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"}):
            config = LLMConfig()
            assert config.get_effective_provider() == LLMProviderType.DEEPSEEK

    def test_get_effective_provider_fallback_to_mock(self):
        """Test fallback to mock without API key"""
        config = LLMConfig(provider=LLMProviderType.DEEPSEEK)

        with patch.dict("os.environ", {}, clear=True):
            # Should fallback to mock because no API key
            assert config.get_effective_provider() == LLMProviderType.MOCK

    def test_get_effective_provider_router_with_keys(self):
        """Test router provider with API keys"""
        config = LLMConfig(provider=LLMProviderType.ROUTER)

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key", "ZAI_API_KEY": "test-key"}):
            assert config.get_effective_provider() == LLMProviderType.ROUTER

    def test_get_effective_provider_router_fallback(self):
        """Test router fallback to mock without keys"""
        config = LLMConfig(provider=LLMProviderType.ROUTER)

        with patch.dict("os.environ", {}, clear=True):
            # Should fallback to mock because no API keys
            assert config.get_effective_provider() == LLMProviderType.MOCK

    def test_is_mock_mode(self):
        """Test is_mock_mode"""
        config = LLMConfig()

        with patch.dict("os.environ", {}, clear=True):
            assert config.is_mock_mode() is True

    def test_is_not_mock_mode_with_key(self):
        """Test is_mock_mode returns False with key"""
        config = LLMConfig(provider=LLMProviderType.DEEPSEEK)

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            assert config.is_mock_mode() is False


class TestLoadLLMConfig:
    """Test load_llm_config function"""

    def test_load_default_config(self):
        """Test loading default config when file not found"""
        with patch.dict("os.environ", {}, clear=True):
            config = load_llm_config("/nonexistent/path.yaml")
            assert config.provider == LLMProviderType.MOCK

    def test_load_config_from_yaml(self):
        """Test loading config from YAML file"""
        yaml_content = """
provider: "mock"
deepseek:
  model: "deepseek-chat"
  timeout_seconds: 30.0
glm:
  model: "glm-5"
  timeout_seconds: 30.0
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                config = load_llm_config(f.name)
                assert config.provider == LLMProviderType.MOCK
                assert config.deepseek.model == "deepseek-chat"
                assert config.glm.model == "glm-5"
            finally:
                os.unlink(f.name)

    def test_load_config_with_router(self):
        """Test loading config with router settings"""
        yaml_content = """
provider: "router"
router:
  default_event_provider: "deepseek"
  default_rule_provider: "glm"
  allow_cross_provider_fallback: true
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                config = load_llm_config(f.name)
                assert config.provider == LLMProviderType.ROUTER
                assert config.router.default_event_provider == "deepseek"
                assert config.router.default_rule_provider == "glm"
                assert config.router.allow_cross_provider_fallback is True
            finally:
                os.unlink(f.name)


class TestLLMProviderType:
    """Test LLM Provider Type Enum"""

    def test_provider_types(self):
        """Test all provider types exist"""
        assert LLMProviderType.MOCK.value == "mock"
        assert LLMProviderType.DEEPSEEK.value == "deepseek"
        assert LLMProviderType.GLM.value == "glm"
        assert LLMProviderType.ZAI.value == "zai"
        assert LLMProviderType.ROUTER.value == "router"

    def test_provider_type_from_string(self):
        """Test creating provider type from string"""
        assert LLMProviderType("mock") == LLMProviderType.MOCK
        assert LLMProviderType("deepseek") == LLMProviderType.DEEPSEEK
        assert LLMProviderType("glm") == LLMProviderType.GLM
        assert LLMProviderType("zai") == LLMProviderType.ZAI
        assert LLMProviderType("router") == LLMProviderType.ROUTER