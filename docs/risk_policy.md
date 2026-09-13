# Risk Policy — PolySignal Pro 风控政策

本文件定义 PolySignal Pro 的资金风险、策略风险、模型风险、系统风险、私钥风险和执行风险控制规则。

Risk Governor 和所有交易相关模块必须遵守本文件。

---

## 1. 风控理念

PolySignal Pro 的风控目标不是提高收益，而是防止系统在错误条件下交易。

核心原则：

```text
First survive, then measure, then improve.
```

即：

1. 先保证系统不会乱交易。
2. 再长期收集 paper trading 数据。
3. 最后再考虑是否小额实盘。

---

## 2. 默认风险模式

默认模式：

```yaml
paper_trading_enabled: true
live_trading_enabled: false
allow_auto_execution: false
```

任何 live execution 必须满足：

1. live_trading_enabled = true
2. allow_auto_execution = true 或人工确认
3. Risk Governor 通过
4. 无 hard rejection
5. 使用测试钱包
6. 仓位小于限制
7. 市场不是 forbidden category

---

## 3. 账户级风控

默认账户参数：

```yaml
max_account_capital_usd: 100
max_position_pct: 0.01
max_market_exposure_pct: 0.03
max_strategy_exposure_pct: 0.08
daily_max_loss_pct: 0.03
weekly_max_loss_pct: 0.08
max_consecutive_losses: 3
```

### 3.1 Wired Guards（2026-09-11 起，Iteration 006）

两个守卫模块已从 stub 接入 Risk Governor 的硬拒绝链，不再是名义防线：

* `polysignal/risk/exposure_guard.py` — **ExposureGuard（硬拒绝）**
  * `market_exposure_limit`：评估时该市场已有敞口 ≥ `max_account_capital_usd × max_market_exposure_pct` → 拒绝
  * `strategy_exposure_limit`：该策略已有敞口 ≥ `max_account_capital_usd × max_strategy_exposure_pct` → 拒绝
  * 语义为 pre-trade 检查：约束的是"已有"敞口；单笔请求规模由执行层
    （PaperTrader/SimBroker）与 AccountState 现金守卫约束，`max_position_pct`
    是执行层 sizing 参数，不是 Governor 的 pre-trade 拒绝条件。
* `polysignal/risk/liquidity_guard.py` — **LiquidityGuard（单一事实来源）**
  * 承接原 Risk Governor 内嵌的 spread/depth 检查（`spread_too_wide`、
    side-aware `depth_too_thin`），行为逐字保留；`orderbook_stale` 与
    `volume_too_low` 仍属 Governor（非盘口深度问题）。

_runner 义务：必须把真实账户状态传入 RiskContext（AccountState.risk_context_fields），
否则敞口限制形同虚设。_

含义：

* 单笔最大仓位：账户资金 1%
* 单市场最大暴露：账户资金 3%
* 单策略最大暴露：账户资金 8%
* 单日最大亏损：账户资金 3%
* 单周最大亏损：账户资金 8%
* 连续亏损 3 笔后暂停

如果账户资金为 100 USD：

```text
单笔最多 1 USD
单市场最多 3 USD
单日最多亏 3 USD
单周最多亏 8 USD
```

---

## 4. 市场级风控

默认市场过滤条件：

```yaml
min_total_volume_usd: 100000
min_24h_volume_usd: 50000
max_spread_pct: 0.05
min_depth_usd: 20
max_price_drift_pct: 0.02
```

禁止交易市场：

* 规则描述不清晰
* 结果来源不明确
* 主观判断市场
* 政治市场自动执行
* 战争 / 地缘冲突市场自动执行
* 法律判决市场自动执行
* 名人八卦市场自动执行
* 低流动性市场
* spread 过宽市场
* depth 过薄市场（按信号方向检查）
* stale price 市场
* 高争议风险市场

### 4.1 Depth 检查逻辑

Risk Governor 按信号方向检查盘口深度：

* **SignalSide.BOTH**：YES ask 侧和 NO ask 侧都必须有足够深度
* **SignalSide.YES**：YES ask 侧必须有足够深度
* **SignalSide.NO**：NO ask 侧必须有足够深度

这确保 YES/NO mispricing 策略（需要同时买入 YES 和 NO）不会因为单侧深度不足而无法执行。

实现代码：

```python
if signal.side == SignalSide.BOTH:
    yes_ask_depth = orderbook.yes_asks.total_depth_usd
    no_ask_depth = orderbook.no_asks.total_depth_usd
    if yes_ask_depth < self.min_depth_usd or no_ask_depth < self.min_depth_usd:
        reasons.append("depth_too_thin")
elif signal.side == SignalSide.YES:
    yes_ask_depth = orderbook.yes_asks.total_depth_usd
    if yes_ask_depth < self.min_depth_usd:
        reasons.append("depth_too_thin")
elif signal.side == SignalSide.NO:
    no_ask_depth = orderbook.no_asks.total_depth_usd
    if no_ask_depth < self.min_depth_usd:
        reasons.append("depth_too_thin")
```

---

## 5. 策略级风控

### 5.1 YES/NO 合成错价策略

允许：

* paper trading
* alert
* research

实盘默认禁止。

必须满足：

* combined_ask <= 0.985
* 两边盘口都有足够深度
* 市场规则清晰
* 非 forbidden category
* 无 stale price
* 无高 resolution risk

风险：

* 两边无法同时成交
* 部分成交风险
* 盘口撤单风险
* 交易成本和滑点
* 结算争议

### 5.2 Orderbook Imbalance 策略

只能作为弱信号。

禁止单独触发交易。

### 5.3 Settlement Edge 策略

必须人工确认或 paper only。

风险：

* 结果源误读
* 市场规则歧义
* 结算延迟
* 争议处理

### 5.4 Wallet Consensus 策略

钱包信号只能加分。

禁止：

* 纯 copy trading 自动执行
* 因单个钱包入场而交易
* 跟随已经明显涨价后的钱包动作

### 5.5 Event Lag 策略

LLM 输出不能直接交易。

事件信号必须经过：

* 证据强度检查
* 市场相关性检查
* 歧义风险检查
* Risk Governor

---

## 6. LLM 风险控制

LLM 风险包括：

* 幻觉
* 错读规则
* 输出格式错误
* 被社交媒体噪声误导
* 被恶意文本注入影响

控制规则：

1. LLM 输出必须是 JSON。
2. JSON 必须通过 Pydantic 校验。
3. 无效输出默认 no trade。
4. LLM 不能进入 ultra-fast path。
5. LLM 不能处理私钥。
6. LLM 不能决定仓位。
7. LLM 不能绕过 Risk Governor。
8. LLM 只能输出建议和解释。

---

## 6.1 生命周期风险控制 (Milestone 2A)

### lifecycle_score 权重

lifecycle_score 在 Risk Governor 评分公式中权重为 **15%**：

```text
trade_score =
  0.30 * microstructure_score
  + 0.20 * liquidity_score
  + 0.20 * event_score
  + 0.15 * wallet_score
  + 0.15 * lifecycle_score
  - ambiguity_penalty
  - slippage_penalty
  - concentration_penalty
```

### 生命周期硬性拒绝条件

以下条件触发 hard reject：

| 条件 | 说明 |
|------|------|
| market_not_open | market.status != OPEN |
| market_ambiguous | market.is_ambiguous == True |
| forbidden_category | market.category 在禁止列表中 |

### 生命周期风险评分

Resolution & Lifecycle Engine 计算以下风险评分：

**close_time_risk (0-1)：**
- 0：市场刚开启或中期
- 0.5：市场进入后期（< 20% 时间剩余）
- 0.9：市场即将关闭（< 5% 时间剩余）
- 1.0：市场已关闭

**ambiguity_risk (0-1)：**
- 0：规则清晰
- 0.2：描述简短或存在弱歧义关键词
- 0.5：resolution_source 不明确或存在歧义关键词
- 0.8：无 resolution_source
- 1.0：显式标记为 ambiguous

**resolution_risk (0-1)：**
- 0：结算源清晰可靠（如 polymarket, uma, oracle）
- 0.3：结算源为手动或委员会
- 0.5：结算源未知
- 0.7：市场类别为 POLITICS/LEGAL/WAR_GEOPOLITICS 等

### lifecycle_score 计算

```text
lifecycle_score = base_score(phase)
                  - ambiguity_risk * 40
                  - resolution_risk * 25
                  - close_time_risk * 20
```

**Phase 基础分：**
- EARLY: 80
- MID: 90
- LATE: 70
- CLOSING: 50
- CLOSED/RESOLVED: 0 (hard reject)

---

## 6.2 钱包风险控制 (Milestone 2B)

### wallet_score 权重

wallet_score 在 Risk Governor 评分公式中权重为 **15%**：

```text
trade_score =
  0.30 * microstructure_score
  + 0.20 * liquidity_score
  + 0.20 * event_score
  + 0.15 * wallet_score
  + 0.15 * lifecycle_score
  - copy_risk_penalty
  - chase_risk_penalty
  - timing_risk_penalty
```

### 钱包硬性拒绝条件

以下条件触发 hard reject：

| 条件 | 说明 |
|------|------|
| wallet_signal_only | wallet_score >= 80 且其他分数 < 60 |

### 钱包风险评分

Wallet Intelligence Engine 计算以下风险评分：

**copy_risk (0-1)：**
- 0：无跟随行为
- 0.3：低跟随行为
- 0.7：高跟随行为
- 1.0：纯 copy trading

**chase_risk (0-1)：**
- 0：无追涨行为
- 0.5：轻微追涨
- 1.0：明显追涨

**timing_risk (0-1)：**
- 0：无异常时间模式
- 0.5：轻微时间集中
- 1.0：高度时间集中

### wallet_score 计算

```text
wallet_score =
  0.30 * reliability_score
  + 0.35 * performance_score
  + 0.20 * specialization_score
  + 0.15 * discipline_score
  - copy_risk_penalty (copy_risk_score * 0.30, max 30)
```

### 钱包信号双重保障

Risk Governor 对 wallet_signal_only 做双重检查：

1. 检查 signal.risk_flags 中的 "wallet_signal_only"
2. 直接检查 component_scores（主要保障）

---

## 6.3 事件风险控制 (Milestone 2C)

### event_score 权重

event_score 在 Risk Governor 评分公式中权重为 **20%**：

```text
trade_score =
  0.30 * microstructure_score
  + 0.20 * liquidity_score
  + 0.20 * event_score
  + 0.15 * wallet_score
  + 0.15 * lifecycle_score
  - event_ambiguity_penalty
  - event_weak_evidence_penalty
  - llm_failure_penalty
```

### 事件硬性拒绝条件

以下条件触发 hard reject：

| 条件 | 说明 |
|------|------|
| event_signal_only | event_score >= 80 且其他分数 < 60 |
| event_forbidden_category | 事件涉及禁止类别 |

### 事件风险评分

Event Intelligence Engine 计算以下风险评分：

**evidence_strength (0-100)：**
- 0-30：弱证据（单来源、未确认）
- 30-60：中等证据（多来源、部分确认）
- 60-100：强证据（官方来源、已确认）

**market_relevance (0-100)：**
- 0-30：低相关性
- 30-60：中等相关性
- 60-100：高相关性

**ambiguity_risk (0-100)：**
- 0-30：低歧义
- 30-60：中等歧义
- 60-100：高歧义

### event_score 计算

```text
event_score =
  0.40 * evidence_strength
  + 0.30 * market_relevance
  + 0.20 * (100 - ambiguity_risk)
  + 0.10 * confidence * 100
```

### LLM 失败降级规则

LLM 失败时（invalid JSON / schema error / low confidence / timeout / error）：

- event_score = 50 (neutral)
- confidence = 0
- suggested_mode = "research" 或 "avoid"
- 添加对应 risk_flag
- 不触发 paper_trade、manual_review 或任何执行动作

### 事件信号双重保障

Risk Governor 对 event_signal_only 做双重检查：

1. 检查 signal.risk_flags 中的 "event_signal_only"
2. 直接检查 component_scores（主要保障）

### LLM 输出禁止字段

LLM 输出禁止包含以下字段：

```text
side, size, order, position, buy, sell, action
```

如果检测到禁止字段，标记 `llm_forbidden_trading_instruction`。

---

## 7. 执行风险控制

MVP 中 live_trader 必须是 stub。

如果后续实现实盘：

* 只允许 limit order
* 禁止 market-order-style sweep
* 订单超时自动撤销
* 部分成交后重新评估
* 不允许无限重试
* 不允许追价超过 max_price_drift_pct
* 每次下单必须有 audit log

默认参数：

```yaml
order_timeout_seconds: 20
max_price_drift_pct: 0.02
```

---

## 8. 系统风险控制

以下情况触发 circuit breaker：

* WebSocket 断连超过阈值
* API 连续失败
* 数据明显 stale
* SQLite 写入失败
* Risk Governor 异常
* Telegram alert 发送失败且系统处于 live mode
* 日亏损触发
* 周亏损触发
* 连续亏损触发

Circuit breaker 触发后：

* 禁止 live execution
* 继续允许 read-only logging
* 发送 alert
* 记录原因
* 等待人工恢复

---

## 9. 私钥与 Secret 风险控制

禁止：

* 在代码中硬编码私钥
* 在配置文件中写私钥
* 在日志中输出私钥
* 在 Telegram 中发送私钥
* 使用主钱包
* 在 VPS 上存放高价值钱包

必须：

* 使用 `.env.example` 示例
* `.env` 加入 `.gitignore`
* 使用小额测试钱包
* 最小权限原则
* 定期轮换 API key

---

## 10. 黑名单机制

系统必须支持 blacklist。

可被拉黑对象：

* market_id
* market category
* wallet address
* strategy
* event source

触发条件：

* 市场规则歧义
* 多次错误信号
* 钱包行为异常
* 事件源不可靠
* 高争议风险

被 blacklist 后，Risk Governor 必须 hard reject。

---

## 11. 人工确认策略

以下情况必须人工确认：

* score >= 90 且 < 95
* settlement edge
* high time sensitivity
* wallet consensus strong but event weak
* event strong but liquidity weak
* 任意接近实盘的动作

Telegram 按钮只能产生 request，不得绕过 Risk Governor。

---

## 12. Paper Trading 验证门槛

进入任何小额实盘前，必须满足：

* paper trades >= 100
* 连续运行 >= 14 天
* 最大回撤 < 5%
* 模拟成交率 > 60%
* 策略收益不是由 1–2 笔极端交易贡献
* 无严重系统错误
* Risk Governor 工作正常
* 日志完整

未满足前，不得开启 live trading。

---

## 13. 风控审计日志

每次 Risk Governor 决策必须记录：

* timestamp
* market_id
* strategy
* trade_score
* component_scores
* hard_reject_reasons
* final_decision
* allowed_actions
* explanation

每次 paper / live order 必须记录：

* signal_id
* order_id
* side
* price
* size
* status
* reason
* risk_decision_id

---

## 14. 禁止宣传

项目文档、README、推文、公众号内容中禁止使用：

* 稳赚
* 保证收益
* 99% 胜率
* 复制暴富
* 无风险套利
* 自动印钞

允许表达：

* research-first
* paper trading
* risk-controlled
* signal analysis
* market microstructure research
* prediction market intelligence

---

## 15. 最终风控原则

任何时候，如果系统无法确定是否安全，应默认：

```text
No trade.
Log only.
Alert if necessary.
Wait for human review.
```

---

## 16. Crypto Threshold / Barrier 风险政策

Crypto threshold 候选仅允许 read-only discovery 和 shadow validation。

必须 fail closed 的条件：

* 标题没有明确资产、价格阈值、方向或到期时间
* contract kind 或 barrier direction 不可验证或互相冲突
* touch contract 的 barrier 在 entry snapshot 时已经越过
* touch contract 缺少从规则起点到 entry 的完整 1m candle barrier coverage；只有
  `historical_barrier_evidence_status=verified_full_coverage` 才能进入 validator
* description 中的示例价格被误识别为标题阈值
* resolution source / origin / locator / adapter / rules / digests / verified status
  缺失、冲突或存在歧义
* spot、entry quote、服务端 orderbook timestamp 或 forward quote stale
* spot 或 quote evidence 晚于 entry，entry evidence 超过 60 秒，或未来时钟偏差超过 5 秒
* YES/NO token pair 缺失、相同或与 observation 不一致
* side-specific bid/ask 缺失或 bid 高于 ask
* entry 或 forward 缺少任一 YES/NO best-level price、size 或服务端 timestamp
* selected entry ask size 无法覆盖 `notional / entry_ask` shares
* selected exit bid size 无法覆盖 entry 获得的完全相同 shares
* forward source 非 public read-only CLOB，或缺少显式 stale/error metadata

Discovery 不能只把 resolution failure 写进诊断后继续生成 entry。任何
`resolution_status != verified` 的候选必须立即降级为 `watch_only`，并由离线 validator
再次独立 fail closed。

`resolution_source_adapter_v1` 风控契约：

* 优先使用结构化 Gamma source；否则只接受明确 resolution-source section 中的唯一 URL
* URL 必须为 HTTPS，且 hostname 必须精确等于以下之一；不接受任意子域或 suffix match：
  `binance.com`、`www.binance.com`、`coinbase.com`、`www.coinbase.com`、
  `exchange.coinbase.com`、`kraken.com`、`www.kraken.com`、`coingecko.com`、
  `www.coingecko.com`、`coinmarketcap.com`、`www.coinmarketcap.com`、`okx.com`、
  `www.okx.com`、`bybit.com`、`www.bybit.com`
* Binance source 只接受 `/en/trade/{BTC|ETH|SOL}_USDT`，并要求 URL asset、规则中的
  `ASSET/USDT`、one-minute/`1m`、up 的 `High`/`equal to or greater` 或 down 的
  `Low`/`equal to or lower` 全部一致
* source/rules 非字符串、HTTP、多个 URL、未知 host、结构化与规则 source 冲突、
  ambiguous rules、locator/rules SHA-256/provenance digest 不一致均 hard fail closed；
  非 Binance source 还必须在 URL 与去除 URL 的规则正文中唯一匹配 provider 和 asset
* origin、locator、adapter version、rules SHA-256 和 provenance SHA-256 必须持久化；
  adapter version、rules hash 与 provenance digest 必须进入 stable trade ID；当前 identity
  contract 还绑定 expiry、spot、全部 client/server timestamps、四价四 size、tokens、
  notional/shares 和 gate fields，并在覆盖前保存 immutable prepared-input snapshot

集中度政策：同一 asset、expiry 和 contract kind 的 threshold ladder 按一个相关 cohort
处理；重复 entry minute 或重复扫描不得创建新 cohort。报告必须披露最大 cohort、
asset、expiry、side、contract 和 barrier share；行数不得冒充独立样本数。

PnL 政策：entry 只用 selected-side ask，exit 只用同 side bid，并显式扣除一次成本。
份额固定为 `notional / entry_ask`，entry/exit 都必须有足量可见盘口，禁止只按 best price
线性外推。
不足 240 分钟、跨 run、pre-entry、future、stale 或 error observation 一律不计算 PnL。
缺数据必须为 null，不得用零填充。

`step12_20260804_114000`、`step12_20260804_122700`、
`step12_v4_20260804_064741`、`step12_v5_20260804_073542` 和
`step12_v6_20260804_083736` 均为旧 cohort 审计材料，禁止继续 poll、补写 entry-time
字段、迁移到当前 discovery/validator schema 或计算 PnL。所有新 cohort 必须从
`crypto_threshold_edge_discovery_v5` 的 run-scoped discovery 开始，并由
`crypto_threshold_shadow_pnl_v7` 离线 validator 严格验收，才可累计 forward
observations。

v5 运行 `step12_v5_20260804_073542` 的 10 个 positions 仅覆盖 3 个 cluster，现已
audit-only；不得继续 poll、迁移、补写或表述为正期望、盈利或 live-ready。v6 及更早
运行同样只保留用于审计。

Historical barrier integration 已完成。正式 v7 cohort 位于
`runs/crypto_threshold_shadow/step12_v7_20260804_140305`：discovery 扫描 1,958 个
markets、识别 56 个 crypto markets、解析 44 个 threshold candidates；通过 3 次 preload、
3 次 entry tail 和 3 个共享 candle snapshots 生成 43 个 threshold-specific manifests。
其中 43/44 historical barriers 为 `verified_full_coverage`；缺少 rules-defined start 的 1 个
候选未发起猜测性历史请求并 fail closed。88 个预期 public CLOB reads 中有 3 个不完整读取
继续 fail closed。Gamma 分页末页记录了可恢复错误，因此本次扫描不宣称 exhaustive。

Discovery 生成 12 个 shadow entries；validator 创建 11 个 fresh paper positions，按资产为
BTC 3、ETH 5、SOL 3，并聚合为 3 个独立 cluster。当前 closed=0，11/11 均为
`insufficient_forward_data`，forward coverage=0.0，PnL=null，win rate=null，整体 status=
`insufficient_forward_data`。历史证据不再是阻塞项；当前阻塞项是满足 entry 后至少 240 分钟
的合格 forward observations，并达到至少 5 个独立 cluster，而本 cohort 目前只有 3 个。
正式 cohort 在达到 240 分钟 horizon 前不得提前 poll；达到时间门槛后也只能采集满足完整
forward-book、timestamp、identity 和 size gates 的只读观察。缺少 5 个独立 cluster 时，
仍不得作 expectancy、profitability 或可实盘结论。

Expiry timezone gate 已由 `gamma_expiry_adapter_v1` 实现：title-local time、rules timezone、
Gamma `endDate` 与 canonical UTC 必须一致，冲突或 naive Gamma time fail closed。

双腿风险政策：当前 PaperTrader 只能表达一个 order 和一个 outcome position，因此
`SignalSide.BOTH` 必须拒绝。YES/NO 双腿只有在 typed result、独立 ledger、逐腿容量及
非原子 leg-risk/flatten 规则完整后，才可进入 paper execution；仍不得进入 live。

无论样本结果如何，当前阶段固定：

```text
supports_tiny_live: false
tiny_live_recommendation: NO
```
