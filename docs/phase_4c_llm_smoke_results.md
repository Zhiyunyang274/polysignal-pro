# Phase 4C — Real LLM Smoke Test Results

## 测试日期: 2026-05-08

---

## 测试环境

- Python: 3.9.6
- pytest: 8.4.2
- Platform: darwin (macOS)
- Test Mode: Real API calls (not mocked)

---

## Provider: SenseNova (OpenAI-compatible)

### Configuration

| Setting | Value |
|---------|-------|
| Model | sensenova-6.7-flash-lite |
| Endpoint | https://token.sensenova.cn/v1/chat/completions |
| Timeout | 60s (increased from 30s) |
| API Key Status | configured |

### Event Analysis

| Metric | Value |
|--------|-------|
| Result | ✅ **Passed** |
| Latency | 39.09s |
| Confidence | 0.7 |
| Event Score | 70.0 |
| Suggested Mode | alert_only |
| Forbidden Fields | [] (none detected) |

### Rule Analysis

| Metric | Value |
|--------|-------|
| Result | ❌ **Failed** |
| Error Type | timeout |
| Latency | 30s+ (timeout) |
| Reason | Request timed out after 30.0s |

### Recommendation

| Aspect | Recommendation |
|--------|----------------|
| Event Analysis | ✅ Can be used with increased timeout (60s) |
| Rule Analysis | ❌ NOT recommended due to timeout issues |
| Default Provider | ❌ NOT recommended as default rule provider |

---

## Provider: XFyun Anthropic (Anthropic-compatible)

### Configuration

| Setting | Value |
|---------|-------|
| Model | astron-code-latest |
| Endpoint | https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic |
| Timeout | 45s |
| API Key Status | configured |

### Event Analysis

| Metric | Value |
|--------|-------|
| Result | ✅ **Passed** |
| Latency | 26.18s |
| Confidence | 0.92 |
| Event Score | 82.0 |
| Suggested Mode | alert_only |
| Forbidden Fields | [] (none detected) |

### Rule Analysis

| Metric | Value |
|--------|-------|
| Result | ✅ **Passed** |
| Latency | 16.85s |
| Confidence | 0.88 |
| Rule Clarity | 85.0 |
| Has Ambiguity | true |

### Recommendation

| Aspect | Recommendation |
|--------|----------------|
| Event Analysis | ✅ **Recommended** - Good latency, high confidence |
| Rule Analysis | ✅ **Recommended** - Excellent performance |
| Default Provider | ✅ **Recommended as default for both event and rule analysis** |

---

## Summary Comparison

| Provider | Event Analysis | Rule Analysis | Avg Latency | Recommendation |
|----------|---------------|---------------|-------------|----------------|
| XFyun Anthropic | ✅ Passed (26s) | ✅ Passed (17s) | 21.5s | **Recommended** |
| SenseNova | ✅ Passed (39s) | ❌ Timeout | N/A | Not recommended for rule |

---

## Recommended Router Configuration

Based on smoke test results:

```yaml
router:
  default_event_provider: "xfyun_anthropic"
  default_rule_provider: "xfyun_anthropic"
  fallback_provider: "mock"
  allow_cross_provider_fallback: false

sensenova:
  timeout_seconds: 60  # Increased due to high latency
  # NOT recommended as default rule provider

xfyun_anthropic:
  timeout_seconds: 45  # Recommended for both event and rule
```

---

## pytest Results

```
================= 588 passed, 8 warnings in 262.41s ==================
```

All unit tests pass. Tests mock HTTP requests and do not call real APIs.

---

## Safety Checks

| Check | Status |
|-------|--------|
| live_trading_enabled | false (unchanged) |
| allow_auto_execution | false (unchanged) |
| Default provider | mock (unchanged) |
| API keys printed | No (only "configured"/"missing") |
| Forbidden trading fields detected | No (none in outputs) |

---

## Next Steps

1. **Phase 4C Audit**: Review all Phase 4C changes for security and correctness
2. **Phase 5 Planning**: Plan next phase based on validated LLM integration
3. **Production Readiness**: Consider XFyun Anthropic for production rule analysis