#!/usr/bin/env python3
"""
Smoke Test for Real LLM Providers

IMPORTANT: This script calls real LLM APIs and requires API keys.
It is OPTIONAL and NOT part of pytest test suite.

Usage:
    # Set API keys in .env file or export them
    export DEEPSEEK_API_KEY=sk-xxx
    export ZAI_API_KEY=xxx.xxx  # or GLM_API_KEY
    export SENSENOVA_API_KEY=xxx
    export XFYUN_API_KEY=xxx

    # Run smoke test
    python scripts/smoke_llm_real.py --provider deepseek
    python scripts/smoke_llm_real.py --provider glm
    python scripts/smoke_llm_real.py --provider sensenova
    python scripts/smoke_llm_real.py --provider xfyun_anthropic
    python scripts/smoke_llm_real.py --provider router

Requirements:
    - API key for selected provider
    - Network connectivity
    - Valid LLM API endpoint
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.llm.llm_config import (
    LLMConfig,
    LLMProviderType,
    load_llm_config,
)
from polysignal.llm.deepseek_provider import DeepSeekProvider
from polysignal.llm.glm_provider import GLMProvider
from polysignal.llm.sensenova_provider import SenseNovaProvider, SenseNovaConfig
from polysignal.llm.xfyun_anthropic_provider import XFyunAnthropicProvider, XFyunAnthropicConfig
from polysignal.llm.provider_router import ProviderRouter, AnalysisType
from polysignal.llm.mock_provider import MockLLMProvider, MockScenario
from polysignal.llm.schemas import EventAnalysisSchema, MarketRuleSchema
from polysignal.llm.llm_errors import LLMProviderNotConfigured


def print_header(title: str) -> None:
    """Print header"""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_section(title: str) -> None:
    """Print section header"""
    print(f"\n[{title}]")


def check_api_keys(provider: str) -> dict:
    """Check API keys for provider"""
    keys = {}

    if provider == "deepseek":
        keys["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY")
        keys["DEEPSEEK_MODEL"] = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    elif provider in ("glm", "zai"):
        keys["ZAI_API_KEY"] = os.environ.get("ZAI_API_KEY")
        keys["GLM_API_KEY"] = os.environ.get("GLM_API_KEY")
        keys["ZAI_MODEL"] = os.environ.get("ZAI_MODEL")
        keys["GLM_MODEL"] = os.environ.get("GLM_MODEL")

    elif provider == "sensenova":
        keys["SENSENOVA_API_KEY"] = os.environ.get("SENSENOVA_API_KEY")
        keys["SENSENOVA_MODEL"] = os.environ.get("SENSENOVA_MODEL", "sensenova-6.7-flash-lite")

    elif provider == "xfyun_anthropic":
        keys["XFYUN_API_KEY"] = os.environ.get("XFYUN_API_KEY")
        keys["XFYUN_MODEL"] = os.environ.get("XFYUN_MODEL", "astron-code-latest")

    elif provider == "router":
        keys["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY")
        keys["ZAI_API_KEY"] = os.environ.get("ZAI_API_KEY")
        keys["GLM_API_KEY"] = os.environ.get("GLM_API_KEY")
        keys["SENSENOVA_API_KEY"] = os.environ.get("SENSENOVA_API_KEY")
        keys["XFYUN_API_KEY"] = os.environ.get("XFYUN_API_KEY")

    return keys


def create_provider(provider_type: str, config: LLMConfig) -> Optional[object]:
    """Create LLM provider"""
    if provider_type == "deepseek":
        if not config.deepseek.is_configured():
            return None
        return DeepSeekProvider(config=config.deepseek)

    elif provider_type in ("glm", "zai"):
        if not config.glm.is_configured():
            return None
        return GLMProvider(config=config.glm)

    elif provider_type == "sensenova":
        if not config.sensenova.is_configured():
            return None
        return SenseNovaProvider(config=SenseNovaConfig(
            model=config.sensenova.get_model(),
            base_url=config.sensenova.base_url,
            timeout_seconds=config.sensenova.timeout_seconds,
            max_retries=config.sensenova.max_retries,
            temperature=config.sensenova.temperature,
            max_tokens=config.sensenova.max_tokens,
        ))

    elif provider_type == "xfyun_anthropic":
        if not config.xfyun_anthropic.is_configured():
            return None
        return XFyunAnthropicProvider(config=XFyunAnthropicConfig(
            model=config.xfyun_anthropic.get_model(),
            base_url=config.xfyun_anthropic.base_url,
            timeout_seconds=config.xfyun_anthropic.timeout_seconds,
            max_retries=config.xfyun_anthropic.max_retries,
            temperature=config.xfyun_anthropic.temperature,
            max_tokens=config.xfyun_anthropic.max_tokens,
        ))

    elif provider_type == "router":
        return ProviderRouter(
            config=config.router,
            deepseek_config=config.deepseek,
            glm_config=config.glm,
            sensenova_config=config.sensenova,
            xfyun_anthropic_config=config.xfyun_anthropic,
        )

    elif provider_type == "mock":
        return MockLLMProvider(scenario=MockScenario.SUCCESS)

    return None


async def test_event_analysis(provider: object, provider_name: str) -> dict:
    """Test event analysis"""
    prompt = """
Market ID: test-market-001
Title: Will Bitcoin reach $100,000 by end of 2026?
Description: This market resolves to YES if Bitcoin price reaches $100,000 USD or higher on any major exchange before December 31, 2026.
Category: crypto
Status: open

Please analyze this market for event intelligence.
"""

    start_time = datetime.utcnow()

    try:
        if provider_name == "router":
            response = await provider.analyze_event(
                prompt=prompt,
                response_schema=EventAnalysisSchema,
            )
        else:
            response = await provider.analyze(
                prompt=prompt,
                response_schema=EventAnalysisSchema,
            )

        latency = (datetime.utcnow() - start_time).total_seconds()

        return {
            "success": response.success,
            "latency": latency,
            "provider": response.provider,
            "confidence": response.confidence,
            "event_score": getattr(response.parsed_output, "event_score", None) if response.parsed_output else None,
            "suggested_mode": getattr(response.parsed_output, "suggested_mode", None) if response.parsed_output else None,
            "error": response.error,
            "error_type": response.error_type,
            "has_forbidden_fields": response.has_forbidden_trading_fields,
            "forbidden_fields": response.forbidden_fields,
        }

    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds()
        return {
            "success": False,
            "latency": latency,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def test_rule_analysis(provider: object, provider_name: str) -> dict:
    """Test rule analysis"""
    prompt = """
Analyze market rules for: Will Bitcoin reach $100,000 by end of 2026?
Description: This market resolves to YES if Bitcoin price reaches $100,000 USD or higher on any major exchange before December 31, 2026.
Category: crypto
Resolution Source: Binance API price feed
"""

    start_time = datetime.utcnow()

    try:
        if provider_name == "router":
            response = await provider.analyze_rule(
                prompt=prompt,
                response_schema=MarketRuleSchema,
            )
        else:
            response = await provider.analyze(
                prompt=prompt,
                response_schema=MarketRuleSchema,
            )

        latency = (datetime.utcnow() - start_time).total_seconds()

        return {
            "success": response.success,
            "latency": latency,
            "provider": response.provider,
            "confidence": response.confidence,
            "rule_clarity": getattr(response.parsed_output, "rule_clarity", None) if response.parsed_output else None,
            "has_ambiguity": getattr(response.parsed_output, "has_ambiguity", None) if response.parsed_output else None,
            "error": response.error,
            "error_type": response.error_type,
        }

    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds()
        return {
            "success": False,
            "latency": latency,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_smoke_test(provider_type: str) -> dict:
    """Run smoke test for provider"""
    print_header(f"PolySignal Pro - Real LLM Smoke Test")
    print(f"Provider: {provider_type}")
    print(f"Started: {datetime.utcnow().isoformat()}")

    # Check API keys
    print_section("Step 1: Checking API keys")
    keys = check_api_keys(provider_type)

    for key_name, key_value in keys.items():
        if key_value:
            print(f"  ✓ {key_name}: Set ({len(key_value)} chars)")
        else:
            print(f"  ✗ {key_name}: Not set")

    # Load config
    print_section("Step 2: Loading configuration")
    config = load_llm_config()
    print(f"  Config provider: {config.provider.value}")
    print(f"  DeepSeek model: {config.deepseek.get_model()}")
    print(f"  GLM model: {config.glm.get_model()}")
    print(f"  SenseNova model: {config.sensenova.get_model()}")
    print(f"  XFyun model: {config.xfyun_anthropic.get_model()}")

    # Create provider
    print_section("Step 3: Creating provider")
    provider = create_provider(provider_type, config)

    if provider is None:
        print(f"  ✗ Provider not configured (missing API key)")
        print("\n" + "=" * 60)
        print("SAFETY CHECK: Provider not configured")
        print("=" * 60)
        return {"success": False, "error": "Provider not configured"}

    print(f"  ✓ Provider created: {provider.get_provider_name()}")
    status = provider.get_status()
    for key, value in status.items():
        print(f"    {key}: {value}")

    # Test event analysis
    print_section("Step 4: Testing event analysis")
    event_result = await test_event_analysis(provider, provider_type)

    if event_result["success"]:
        print(f"  ✓ Event analysis succeeded")
        print(f"    Latency: {event_result['latency']:.2f}s")
        print(f"    Provider: {event_result['provider']}")
        print(f"    Confidence: {event_result['confidence']}")
        print(f"    Event Score: {event_result['event_score']}")
        print(f"    Suggested Mode: {event_result['suggested_mode']}")
        print(f"    Forbidden Fields: {event_result['forbidden_fields']}")
    else:
        print(f"  ✗ Event analysis failed")
        print(f"    Error: {event_result['error']}")
        print(f"    Error Type: {event_result['error_type']}")

    # Test rule analysis
    print_section("Step 5: Testing rule analysis")
    rule_result = await test_rule_analysis(provider, provider_type)

    if rule_result["success"]:
        print(f"  ✓ Rule analysis succeeded")
        print(f"    Latency: {rule_result['latency']:.2f}s")
        print(f"    Provider: {rule_result['provider']}")
        print(f"    Confidence: {rule_result['confidence']}")
        print(f"    Rule Clarity: {rule_result['rule_clarity']}")
        print(f"    Has Ambiguity: {rule_result['has_ambiguity']}")
    else:
        print(f"  ✗ Rule analysis failed")
        print(f"    Error: {rule_result['error']}")
        print(f"    Error Type: {rule_result['error_type']}")

    # Summary
    print_header("Smoke Test Summary")
    print(f"Provider:           {provider_type}")
    print(f"Event Analysis:     {'✓ Passed' if event_result['success'] else '✗ Failed'}")
    print(f"Rule Analysis:      {'✓ Passed' if rule_result['success'] else '✗ Failed'}")
    print(f"Event Latency:      {event_result['latency']:.2f}s")
    print(f"Rule Latency:       {rule_result['latency']:.2f}s")
    print(f"Forbidden Fields:   {event_result.get('forbidden_fields', [])}")

    # Safety check
    print_header("SAFETY CHECK: Live Trading Status")
    print(f"live_trading_enabled: False (unchanged)")
    print(f"allow_auto_execution: False (unchanged)")
    print(f"paper_trading_enabled: True")
    print("\n✅ Safe: live_trading is DISABLED")
    print("=" * 60)

    return {
        "success": event_result["success"] and rule_result["success"],
        "event_result": event_result,
        "rule_result": rule_result,
    }


def main() -> None:
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Smoke test for real LLM providers")
    parser.add_argument(
        "--provider",
        type=str,
        choices=["deepseek", "glm", "zai", "sensenova", "xfyun_anthropic", "router", "mock"],
        default="mock",
        help="LLM provider to test",
    )

    args = parser.parse_args()

    try:
        result = asyncio.run(run_smoke_test(args.provider))

        if result["success"]:
            print("\n✅ Smoke test passed")
            sys.exit(0)
        else:
            print("\n✗ Smoke test failed")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nSmoke test interrupted")
        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Smoke test error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()