"""
API Errors - Polymarket API Error Types

This module defines error types for Polymarket API operations.
All errors are handled gracefully with fallback to mock mode.
"""

from __future__ import annotations

from typing import Optional


class APIError(Exception):
    """Base API error"""
    pass


class APITimeout(APIError):
    """Request timeout"""
    pass


class APIConnectionError(APIError):
    """Connection error (network, DNS, etc.)"""
    pass


class APIRateLimit(APIError):
    """Rate limit exceeded"""
    retry_after: Optional[int] = None

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class APIInvalidResponse(APIError):
    """Invalid response from API"""
    pass


class APINotFound(APIError):
    """Resource not found (404)"""
    pass


class APIServerError(APIError):
    """Server error (5xx)"""
    status_code: Optional[int] = None

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GammaAPIError(APIError):
    """Gamma API specific error"""
    pass


class CLOBError(APIError):
    """CLOB API specific error"""
    pass


class DataConversionError(APIError):
    """Error converting API data to internal models"""
    pass