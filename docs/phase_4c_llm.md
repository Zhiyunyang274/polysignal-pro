# Phase 4C — Real LLM Providers Integration

## 概述

Phase 4C 实现了真实 LLM 提供商接入，用于 Event Intelligence Engine。

**重要**: Phase 4C 不涉及：
- 真实下单
- 私钥处理
- 修改 `live_trading_enabled`
- LLM 进入 ultra-fast path
- LLM 直接触发交易

---

## 验证状态

| 组件 | 状态 |
|------|------|
| DeepSeek Provider | ✅ Implemented |
| GLM/Z.AI Provider | ✅ Implemented |
| SenseNova Provider | ✅ Implemented |
| XFyun Anthropic Provider | ✅ Implemented |
| Provider Router | ✅ Implemented |
| Configuration | ✅ Implemented |
| Tests | ✅ All 588 tests pass |
| Real LLM Smoke Test | ✅ Completed |

---

## Real LLM Smoke Test Results (2026-05-08)

### SenseNova (OpenAI-compatible)

| Analysis Type | Result | Latency | Confidence | Score | Notes |
|---------------|--------|---------|------------|-------|-------|
| Event Analysis | ✅ Passed | 39.09s | 0.7 | 70.0 | High latency |
| Rule Analysis | ❌ Timeout | 30s+ | N/A | N/A | Timeout after 30s |

**Recommendation**: Not recommended for rule analysis due to timeout issues. Can be used for event analysis with increased timeout (60s).

### XFyun Anthropic (Anthropic-compatible)

| Analysis Type | Result | Latency | Confidence | Score | Notes |
|---------------|--------|---------|------------|-------|-------|
| Event Analysis | ✅ Passed | 26.18s | 0.92 | 82.0 | Good performance |
| Rule Analysis | ✅ Passed | 16.85s | 0.88 | 85.0 (clarity) | Excellent performance |

**Recommendation**: Recommended for both event and rule analysis based on smoke test results.

---

## 提供商分工 (Updated based on smoke test)

| Provider | 用途 | 原因 |
|----------|------|------|
| XFyun Anthropic | Event Analysis, Rule Analysis | Smoke test passed, good latency, high confidence |
| SenseNova | Event Analysis (optional) | Passed event analysis but high latency (39s) |
| DeepSeek V4 Flash | 批量分析、快速筛选 | 成本低、速度快 (未测试) |
| GLM 5.0 | 复杂规则解读 | 中文理解强 (未测试) |

**Recommended Router Configuration**:
```yaml
router:
  default_event_provider: "xfyun_anthropic"
  default_rule_provider: "xfyun_anthropic"
  fallback_provider: "mock"
  allow_cross_provider_fallback: false
```

---

## 模块结构

```
polysignal/llm/
├── __init__.py              # Package exports
├── base.py                  # Abstract LLM Provider interface
├── mock_provider.py         # Mock provider for testing
├── deepseek_provider.py     # DeepSeek API provider
├── glm_provider.py          # GLM/Z.AI API provider
├── sensenova_provider.py    # SenseNova API provider (OpenAI-compatible)
├── xfyun_anthropic_provider.py  # XFyun Anthropic API provider
├── provider_router.py       # Intelligent routing
├── llm_config.py            # Configuration models
├── llm_errors.py            # Error types
└── schemas.py               # Output schemas
```

---

## 配置

### config/llm.yaml

```yaml
# Provider selection (mock by default)
provider: "mock"

# XFyun Anthropic settings (RECOMMENDED based on smoke test)
xfyun_anthropic:
  model: "astron-code-latest"
  base_url: "https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic"
  timeout_seconds: 45
  max_retries: 2
  temperature: 0.1
  max_tokens: 2000

# SenseNova settings (NOT recommended for rule analysis)
sensenova:
  model: "sensenova-6.7-flash-lite"
  base_url: "https://token.sensenova.cn/v1"
  timeout_seconds: 60  # Increased due to high latency
  max_retries: 2
  temperature: 0.1
  max_tokens: 2000

# Router settings
router:
  default_event_provider: "xfyun_anthropic"
  default_rule_provider: "xfyun_anthropic"
  fallback_provider: "mock"
  allow_cross_provider_fallback: false
```

### 环境变量

```bash
# Provider selection
LLM_PROVIDER=mock  # mock, deepseek, glm, sensenova, xfyun_anthropic, router

# XFyun Anthropic (RECOMMENDED)
XFYUN_API_KEY=your-api-key
XFYUN_MODEL=astron-code-latest

# SenseNova
SENSENOVA_API_KEY=your-api-key
SENSENOVA_MODEL=sensenova-6.7-flash-lite

# DeepSeek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-chat

# GLM/Z.AI (ZAI_API_KEY preferred)
ZAI_API_KEY=xxx.xxx
GLM_API_KEY=xxx.xxx
```

---

## 使用示例

### XFyun Anthropic Provider (Recommended)

```python
import os
os.environ["XFYUN_API_KEY"] = "your-api-key"

from polysignal.llm import XFyunAnthropicProvider, XFyunAnthropicConfig
from polysignal.llm.schemas import EventAnalysisSchema

config = XFyunAnthropicConfig(model="astron-code-latest")
provider = XFyunAnthropicProvider(config=config)
response = await provider.analyze(
    prompt="Analyze this market...",
    response_schema=EventAnalysisSchema,
)
```

### SenseNova Provider

```python
import os
os.environ["SENSENOVA_API_KEY"] = "your-api-key"

from polysignal.llm import SenseNovaProvider, SenseNovaConfig
from polysignal.llm.schemas import EventAnalysisSchema

config = SenseNovaConfig(
    model="sensenova-6.7-flash-lite",
    timeout_seconds=60,  # Recommended due to high latency
)
provider = SenseNovaProvider(config=config)
response = await provider.analyze(
    prompt="Analyze this market...",
    response_schema=EventAnalysisSchema,
)
```

### Provider Router

```python
import os
os.environ["XFYUN_API_KEY"] = "your-api-key"

from polysignal.llm import ProviderRouter, RouterConfig
from polysignal.llm.schemas import EventAnalysisSchema, MarketRuleSchema

config = RouterConfig(
    default_event_provider="xfyun_anthropic",
    default_rule_provider="xfyun_anthropic",
    allow_cross_provider_fallback=False,
)
router = ProviderRouter(config=config)

# Event analysis uses XFyun Anthropic
event_response = await router.analyze_event(
    prompt="Analyze event...",
    response_schema=EventAnalysisSchema,
)

# Rule analysis uses XFyun Anthropic
rule_response = await router.analyze_rule(
    prompt="Analyze rules...",
    response_schema=MarketRuleSchema,
)
```

---

## Fallback 策略

### 推荐配置 (allow_cross_provider_fallback=False)

```
Event Analysis: XFyun Anthropic -> Mock -> Neutral
Rule Analysis:  XFyun Anthropic -> Mock -> Neutral
```

---

## 安全约束

### LLM 输出禁止字段

以下字段不能作为 JSON key 出现在 LLM 输出中：

```python
FORBIDDEN_TRADING_FIELDS = {
    "side",
    "size",
    "order",
    "position",
    "buy",
    "sell",
    "action",
}
```

**重要**: 只检查 JSON key，不检查文本值。如果 "buy" 出现在 explanation 字符串中，不会被标记。

### Neutral EventAssessment

LLM 失败时的默认评估：

```python
EventAssessment(
    event_score=50.0,        # 中性分数
    evidence_strength=0.0,
    market_relevance=0.0,
    ambiguity_risk=50.0,     # 不是 100
    suggested_mode="research",
    risk_flags=["llm_fallback_neutral"],
    confidence=0.0,
)
```

---

## 测试

### 单元测试

```bash
pytest tests/test_sensenova_provider.py -v
pytest tests/test_xfyun_anthropic_provider.py -v
pytest tests/test_provider_router.py -v
pytest tests/test_llm_config.py -v
```

### Smoke Test (可选)

```bash
# 设置 API keys in .env
XFYUN_API_KEY=your-api-key
SENSENOVA_API_KEY=your-api-key

# 运行 smoke test
python3 scripts/smoke_llm_real.py --provider xfyun_anthropic
python3 scripts/smoke_llm_real.py --provider sensenova
```

---

## 文件清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `polysignal/llm/sensenova_provider.py` | SenseNova API provider (OpenAI-compatible) |
| `polysignal/llm/xfyun_anthropic_provider.py` | XFyun Anthropic API provider |
| `tests/test_sensenova_provider.py` | SenseNova tests (21 tests) |
| `tests/test_xfyun_anthropic_provider.py` | XFyun tests (23 tests) |

### 修改文件

| 文件 | 说明 |
|------|------|
| `polysignal/llm/provider_router.py` | Added SenseNova and XFyun routing |
| `polysignal/llm/llm_config.py` | Added SenseNova and XFyun configs |
| `config/llm.yaml` | Updated with new providers |
| `scripts/smoke_llm_real.py` | Added sensenova and xfyun_anthropic support |

---

## 安全保证

| 检查项 | 状态 |
|-------|------|
| `live_trading_enabled: false` | ✅ Unchanged |
| `allow_auto_execution: false` | ✅ Unchanged |
| 无私钥处理 | ✅ |
| LLM 不在 ultra-fast path | ✅ |
| LLM 不触发交易 | ✅ |
| LLM 不输出交易字段 | ✅ |
| API key 仅从环境变量读取 | ✅ |
| 测试不依赖真实 API | ✅ |
| 默认 provider: mock | ✅ |
