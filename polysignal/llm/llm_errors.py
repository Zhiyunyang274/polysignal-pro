"""
LLM Error Types - Custom exceptions for LLM providers

IMPORTANT: These errors are for LLM provider failures only.
They do NOT affect trading execution directly.
"""

from typing import Optional


class LLMError(Exception):
    """Base exception for LLM errors"""

    def __init__(
        self,
        message: str,
        error_type: str = "llm_error",
        provider: str = "unknown",
        retry_count: int = 0,
    ):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.provider = provider
        self.retry_count = retry_count


class LLMTimeout(LLMError):
    """LLM request timeout"""

    def __init__(
        self,
        message: str = "LLM request timed out",
        provider: str = "unknown",
        retry_count: int = 0,
    ):
        super().__init__(
            message=message,
            error_type="timeout",
            provider=provider,
            retry_count=retry_count,
        )


class LLMConnectionError(LLMError):
    """LLM connection error"""

    def __init__(
        self,
        message: str = "Failed to connect to LLM provider",
        provider: str = "unknown",
        retry_count: int = 0,
    ):
        super().__init__(
            message=message,
            error_type="connection_error",
            provider=provider,
            retry_count=retry_count,
        )


class LLMAuthenticationError(LLMError):
    """LLM authentication error (invalid API key)"""

    def __init__(
        self,
        message: str = "LLM authentication failed",
        provider: str = "unknown",
    ):
        super().__init__(
            message=message,
            error_type="auth_error",
            provider=provider,
        )


class LLMRateLimit(LLMError):
    """LLM rate limit exceeded"""

    def __init__(
        self,
        message: str = "LLM rate limit exceeded",
        provider: str = "unknown",
        retry_after: Optional[float] = None,
    ):
        super().__init__(
            message=message,
            error_type="rate_limit",
            provider=provider,
        )
        self.retry_after = retry_after


class LLMInvalidJSON(LLMError):
    """LLM returned invalid JSON"""

    def __init__(
        self,
        message: str = "LLM returned invalid JSON",
        provider: str = "unknown",
        raw_output: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_type="invalid_json",
            provider=provider,
        )
        self.raw_output = raw_output


class LLMSchemaError(LLMError):
    """LLM output doesn't match expected schema"""

    def __init__(
        self,
        message: str = "LLM output doesn't match expected schema",
        provider: str = "unknown",
        raw_output: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_type="schema_error",
            provider=provider,
        )
        self.raw_output = raw_output


class LLMForbiddenFieldsError(LLMError):
    """LLM output contains forbidden trading fields"""

    def __init__(
        self,
        message: str = "LLM output contains forbidden trading fields",
        provider: str = "unknown",
        forbidden_fields: Optional[list[str]] = None,
    ):
        super().__init__(
            message=message,
            error_type="forbidden_fields",
            provider=provider,
        )
        self.forbidden_fields = forbidden_fields or []


class LLMLowConfidence(LLMError):
    """LLM returned low confidence response"""

    def __init__(
        self,
        message: str = "LLM confidence below threshold",
        provider: str = "unknown",
        confidence: float = 0.0,
    ):
        super().__init__(
            message=message,
            error_type="low_confidence",
            provider=provider,
        )
        self.confidence = confidence


class LLMProviderNotConfigured(LLMError):
    """LLM provider not configured (missing API key)"""

    def __init__(
        self,
        message: str = "LLM provider not configured",
        provider: str = "unknown",
    ):
        super().__init__(
            message=message,
            error_type="not_configured",
            provider=provider,
        )
