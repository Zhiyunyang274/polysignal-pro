"""
Ingestion Package - Data ingestion modules
"""

from polysignal.ingestion.mock_data_provider import MockDataProvider, create_mock_provider

__all__ = [
    "MockDataProvider",
    "create_mock_provider",
]
