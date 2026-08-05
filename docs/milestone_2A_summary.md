# Milestone 2A Summary — Resolution & Lifecycle Engine

**Date:** 2026-05-07
**Milestone:** 2A — Resolution & Lifecycle Engine
**Status:** ✅ Completed

---

## 1. 修改文件清单

### 新增文件

| 文件 | 描述 |
|------|------|
| `polysignal/models/lifecycle.py` | Lifecycle 数据模型 (LifecyclePhase, AmbiguityLevel, ResolutionRiskLevel, LifecycleAssessment) |
| `polysignal/engines/resolution_lifecycle.py` | Resolution & Lifecycle Engine 实现 |
| `tests/fixtures/lifecycle.py` | Lifecycle 测试 fixtures |
| `tests/test_resolution_lifecycle.py` | Lifecycle Engine 单元测试 (38 tests) |
| `tests/test_risk_governor_lifecycle.py` | Risk Governor + Lifecycle 集成测试 (14 tests) |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `polysignal/engines/__init__.py` | 导出 ResolutionLifecycleEngine |
| `polysignal/risk/risk_governor.py` | 集成 lifecycle hard rejection，双重兜底检查 |
| `config/risk.yaml` | 添加 lifecycle 配置和 ambiguity_keywords |

---

## 2. 新增测试清单

### tests/test_resolution_lifecycle.py (38 tests)

**Phase Detection Tests:**
- test_default_settings
- test_assess_early_phase
- test_assess_mid_phase
- test_assess_late_phase
- test_assess_closing_phase
- test_assess_closed_market
- test_assess_resolved_market
- test_assess_no_close_time
- test_assess_no_created_at

**Ambiguity Detection Tests:**
- test_ambiguity_explicit
- test_ambiguity_no_resolution_source
- test_ambiguity_keyword_in_title
- test_ambiguity_keyword_in_source
- test_ambiguity_insufficient_criteria

**Resolution Risk Tests:**
- test_resolution_risk_crypto_category
- test_resolution_risk_sports_category
- test_resolution_risk_politics_category
- test_resolution_risk_legal_category

**Forbidden Category Tests:**
- test_forbidden_category_politics
- test_forbidden_category_crypto
- test_forbidden_category_war
- test_forbidden_category_celebrity
- test_forbidden_category_subjective

**Lifecycle Score Tests:**
- test_lifecycle_score_mid_phase
- test_lifecycle_score_early_phase
- test_lifecycle_score_with_ambiguity_penalty
- test_lifecycle_score_with_resolution_penalty
- test_lifecycle_score_closed_market
- test_lifecycle_score_resolved_market

**Tradable Status Tests:**
- test_tradable_true_for_open_market
- test_tradable_false_when_closed
- test_tradable_false_when_ambiguous

**Risk Flags Tests:**
- test_risk_flags_propagated
- test_hard_reject_reasons_for_closed
- test_hard_reject_reasons_for_ambiguous

**Custom Keywords Tests:**
- test_custom_ambiguity_keywords
- test_default_keywords_present

**Summary Tests:**
- test_get_summary

### tests/test_risk_governor_lifecycle.py (14 tests)

**Hard Rejection Tests:**
- test_hard_reject_closed_market
- test_hard_reject_resolved_market
- test_hard_reject_ambiguous_market
- test_hard_reject_ambiguous_from_signal_flags
- test_hard_reject_forbidden_category_direct
- test_hard_reject_forbidden_category_from_signal_flags
- test_hard_reject_forbidden_category_dual_safeguard

**Lifecycle Score Integration Tests:**
- test_lifecycle_score_in_trade_score
- test_lifecycle_score_penalty_reduces_trade_score
- test_lifecycle_score_zero_for_closed_market

**Integration Flow Tests:**
- test_full_integration_flow
- test_integration_with_orderbook

**Safety Verification Tests:**
- test_live_trading_still_disabled
- test_no_live_execution_even_with_high_lifecycle_score

---

## 3. 测试结果

```
pytest tests/ -v
109 passed, 1 warning in 0.15s
```

**测试分布：**
- 原有测试：57 tests
- 新增测试：52 tests
- 总计：109 tests

---

## 4. Lifecycle Engine 功能摘要

### 输入

- Market 对象（包含 status, close_time, created_at, category, is_ambiguous, resolution_source 等）

### 输出

| 字段 | 类型 | 说明 |
|------|------|------|
| lifecycle_score | float (0-100) | 生命周期综合评分 |
| phase | LifecyclePhase | EARLY/MID/LATE/CLOSING/CLOSED/RESOLVED |
| is_tradable | bool | 市场是否可交易 |
| is_auto_allowed | bool | 是否允许自动执行 |
| ambiguity_risk | float (0-1) | 规则歧义风险 |
| resolution_risk | float (0-1) | 结算风险 |
| close_time_risk | float (0-1) | 时间风险 |
| hard_reject_reasons | list[str] | 必须拒绝的原因 |
| risk_flags | list[str] | 风险标志 |

### 评分公式

```text
lifecycle_score = base_score(phase)
                  - ambiguity_risk * 40
                  - resolution_risk * 25
                  - close_time_risk * 20
```

### Phase 基础分

| Phase | 基础分 | 时间条件 |
|-------|--------|----------|
| EARLY | 80 | > 90% 时间剩余 |
| MID | 90 | 20-90% 时间剩余 |
| LATE | 70 | 5-20% 时间剩余 |
| CLOSING | 50 | < 5% 时间剩余 |
| CLOSED/RESOLVED | 0 | 已关闭/已结算 |

---

## 5. Risk Governor 集成摘要

### 双重兜底机制

Risk Governor 对关键安全条件做**直接检查**和**信号标志检查**双重保障：

**直接检查（主要）：**
```python
if market.status != MarketStatus.OPEN:
    reasons.append("market_not_open")

if market.is_ambiguous:
    reasons.append("market_ambiguous")

if not market.is_auto_allowed():
    reasons.append("forbidden_category")
```

**信号标志检查（补充）：**
```python
if "market_not_open" in signal.risk_flags:
    reasons.append("market_not_open")

if "market_ambiguous" in signal.risk_flags:
    reasons.append("market_ambiguous")

if "forbidden_category" in signal.risk_flags:
    reasons.append("forbidden_category")
```

### lifecycle_score 集成

lifecycle_score 通过 `signal.component_scores.lifecycle_score` 传入，在 trade_score 计算中权重为 15%。

---

## 6. 当前安全状态

```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
```

**确认：Live trading 仍然禁用。**

---

## 7. 已知限制

1. **无真实 API：** 当前使用 mock 数据，未接入真实 Polymarket API
2. **无钱包画像：** Wallet Intelligence Engine 尚未实现
3. **无事件分析：** Event Intelligence Engine 尚未实现
4. **无 Telegram：** Telegram 交互尚未实现
5. **无 LLM：** LLM provider 为 mock

---

## 8. 下一步建议

**Milestone 2B — Wallet Intelligence Engine**

目标：
- wallet watchlist 管理
- wallet profile 生成
- wallet_score 计算
- anti-copy filters
- wallet_consensus strategy

约束：
- wallet signal 不能单独触发交易
- wallet_score 权重为 15%
- 需要新增测试

---

**Signed off by:** Claude Code
**Date:** 2026-05-07
