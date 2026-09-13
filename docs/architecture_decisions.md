# Architecture Decisions — PolySignal Pro 架构决策记录

本文件记录 PolySignal Pro 的关键架构决策。任何重大架构变更必须更新本文件。

格式参考 ADR：Architecture Decision Record。

---

## ADR-001：系统定位为 Research-first，而不是 Live-trading-first

### 状态

Accepted

### 背景

Polymarket 自动交易涉及资金风险、盘口滑点、规则歧义、市场流动性、API 稳定性和钱包私钥安全。如果一开始以实盘交易为核心，容易导致系统在尚未验证策略期望值前暴露资金风险。

### 决策

PolySignal Pro 默认定位为：

```text
Read-only monitoring + Paper trading + Alerting + Risk research
```

Live trading 不是 MVP 目标，必须通过显式 feature flag 与 Risk Governor。

### 影响

优点：

* 降低资金风险
* 提高可测试性
* 更适合作品集与长期研究
* 避免过早处理私钥和真实订单

代价：

* 初期不能直接产生实盘收益
* 需要更长 paper trading 验证周期

---

## ADR-002：采用四引擎 + Risk Governor 架构

### 状态

Accepted

### 背景

单一策略 bot 容易过拟合，且缺乏解释性。Polymarket 机会通常来自多个维度：盘口结构、钱包行为、外部事件、结算规则。

### 决策

系统采用四个智能引擎：

1. Market Microstructure Engine
2. Wallet Intelligence Engine
3. Event Intelligence Engine
4. Resolution & Lifecycle Engine

所有引擎输出进入 Risk Governor，由 Risk Governor 统一裁决。

### 影响

优点：

* 模块边界清晰
* 信号更可解释
* 风控集中
* 后续策略扩展更容易

代价：

* 初始架构复杂度较高
* 需要更严格接口设计

---

## ADR-003：采用快慢分层架构

### 状态

Accepted

### 背景

盘口错价机会可能在秒级消失。如果每次信号都等待 LLM、钱包画像和外部数据分析，机会会错过。

### 决策

系统采用四层路径：

```text
Ultra-fast path: 0.1–2 seconds
Fast path: 5–30 seconds
Slow path: 1–15 minutes
Research path: hourly/daily
```

Ultra-fast path 只处理轻量盘口信号，并读取其他引擎缓存。

### 影响

优点：

* 盘口机会响应更快
* LLM 不阻塞交易判断
* 系统更稳定

代价：

* 需要缓存设计
* 需要异步任务管理

---

## ADR-004：Risk Governor 为唯一执行裁决者

### 状态

Accepted

### 背景

如果策略、LLM 或钱包信号能直接触发交易，系统会变得不可控。

### 决策

所有 Signal 必须进入 Risk Governor。

Risk Governor 输出最终动作：

* ignore
* log only
* alert
* paper trade
* manual review
* limited live execution

任何模块不得绕过 Risk Governor。

### 影响

优点：

* 风控集中
* 行为可审计
* 防止策略越权

代价：

* 所有模块必须遵守统一接口

---

## ADR-005：MVP 使用 SQLite，而非 PostgreSQL

### 状态

Accepted

### 背景

MVP 需要快速可运行，数据规模初期有限。PostgreSQL 增加部署复杂度。

### 决策

MVP 使用 SQLite。

后续如果出现以下情况，可迁移 PostgreSQL：

* 高频 orderbook snapshot 写入过多
* 多进程写入冲突明显
* dashboard 查询性能不足
* 需要远程多人访问

### 影响

优点：

* 部署简单
* 适合个人 VPS
* 便于测试

代价：

* 并发能力有限
* 长期数据分析能力有限

---

## ADR-006：LLM 只做分析，不做执行

### 状态

Accepted

### 背景

LLM 可能幻觉、误读市场规则、输出无效 JSON 或受到外部文本影响。让 LLM 直接下单风险过高。

### 决策

LLM 只能用于：

* 事件摘要
* 市场规则解释
* 歧义风险判断
* 新闻初筛
* alert 文案
* 日报总结

LLM 不能：

* 下单
* 决定仓位
* 绕过风控
* 进入 ultra-fast path

### 影响

优点：

* 降低幻觉风险
* 系统更可控
* 输出可校验

代价：

* 部分复杂事件无法完全自动化

---

## ADR-007：默认禁止政治、战争、法律、主观类市场自动执行

### 状态

Accepted

### 背景

这些市场通常存在规则解释争议、信息不对称、结算不确定和舆论噪声。

### 决策

以下类别默认禁止自动实盘：

* Politics
* War / geopolitics
* Legal judgments
* Celebrity / pop culture
* Subjective markets
* Ambiguous resolution rules

可以记录、分析、paper trade，但不允许自动执行。

### 影响

优点：

* 降低争议结算风险
* 降低错误理解规则风险

代价：

* 放弃部分潜在机会

---

## ADR-008：Paper Trader 是 MVP 核心，而不是附属功能

### 状态

Accepted

### 背景

没有长期 paper trading 数据，就无法判断策略是否有正期望。直接实盘属于盲测。

### 决策

Paper Trader 必须作为核心模块实现。

它必须支持：

* limit order simulation
* partial fill simulation
* slippage assumptions
* mark-to-market
* PnL tracking
* trade journal
* strategy statistics

### 影响

优点：

* 策略可验证
* 风险可度量
* 方便复盘

代价：

* MVP 开发工作量增加

---

## ADR-009：Telegram 作为第一阶段交互层

### 状态

Accepted

### 背景

项目需要实时提醒和轻量人工确认。开发完整 App 或复杂 Web 前端成本较高。

### 决策

MVP 使用 Telegram alert 和按钮作为远程驾驶舱。

Dashboard 用于观察和复盘，Telegram 用于即时交互。

### 影响

优点：

* 开发快
* 手机实时提醒
* 适合人工确认

代价：

* 交互能力有限
* 依赖 Telegram 可用性

---

## ADR-010：Live Trader MVP 中实现为 Stub

### 状态

Accepted

### 背景

真实下单涉及私钥、安全、订单签名、资金和合规风险。MVP 阶段更需要验证数据和风控。

### 决策

MVP 中 live_trader 只实现接口和 stub，不执行真实订单。

后续实现必须满足：

* feature flag 显式开启
* 测试钱包
* 小额资金
* limit order only
* Risk Governor 二次确认
* 完整 audit log

### 影响

优点：

* 避免误下单
* 保持架构可扩展
* 降低初期风险

代价：

* 初期不能实盘验证执行层

---

## ADR-011：Side-specific Depth Checking for YES/NO Mispricing

### 状态

Accepted

### 背景

YES/NO mispricing strategy generates signals with side=BOTH, meaning it needs to buy both YES and NO tokens. A generic depth check that only examines total orderbook depth could incorrectly approve trades when one side has insufficient depth.

### 决策

Risk Governor checks depth based on signal side:

* For `SignalSide.BOTH`: Both YES ask side and NO ask side must have sufficient depth
* For `SignalSide.YES`: YES ask side must have sufficient depth
* For `SignalSide.NO`: NO ask side must have sufficient depth

Implementation in `risk_governor.py`:

```python
if signal.side == SignalSide.BOTH:
    yes_ask_depth = orderbook.yes_asks.total_depth_usd
    no_ask_depth = orderbook.no_asks.total_depth_usd
    if yes_ask_depth < self.min_depth_usd or no_ask_depth < self.min_depth_usd:
        reasons.append("depth_too_thin")
```

### 影响

优点：

* Prevents partial execution risk
* More accurate liquidity assessment
* Reduces slippage risk for combined positions

代价：

* Slightly more complex depth checking logic
* Requires signal side to be properly set

---

## ADR-012：Python 3.9+ Compatibility

### 状态

Superseded by ADR-026 (2026-09-11)

### 背景

Project initially specified Python 3.11+ but system Python on target environment is 3.9.6. Using newer syntax like `|` union types would break compatibility.

### 决策

Support Python 3.9+ by:

* Using `Optional[X]` instead of `X | None`
* Using `Union[X, Y]` instead of `X | Y`
* Using `from __future__ import annotations` for forward references
* Setting `python_requires = ">=3.9"` in pyproject.toml

### 影响

优点：

* Broader compatibility
* Works on default macOS Python

代价：

* Slightly more verbose type annotations
* Cannot use some 3.10+ features

---

## ADR-013：MVP Test Coverage Target

### 状态

Accepted

### 背景

MVP needs sufficient test coverage to validate core functionality before adding more complex engines.

### 决策

Milestone 1 MVP targets:

* 57 tests covering all core modules
* Config loading and validation
* Market Microstructure Engine
* YES/NO Mispricing Strategy
* Risk Governor (hard rejection, score calculation, thresholds)
* Paper Trader (execution, tracking, PnL)

All tests must pass before proceeding to Milestone 2.

### 影响

优点：

* Validates MVP functionality
* Provides regression protection
* Documents expected behavior

代价：

* Initial development time for tests

---

## ADR-014：Resolution & Lifecycle Engine 作为 Risk Governor 的前置风险评估层

### 状态

Accepted

### 背景

市场生命周期状态、规则歧义、结算风险等因素会影响交易安全性。如果 Risk Governor 只依赖信号本身的评分，可能无法及时拒绝存在生命周期风险的市场。

### 决策

Resolution & Lifecycle Engine 作为独立引擎，在信号进入 Risk Governor 前评估市场生命周期风险：

**输出：**
- `lifecycle_score` (0-100)：基于市场阶段和风险因素的综合评分
- `is_tradable`：市场是否可交易
- `hard_reject_reasons`：必须拒绝的原因列表
- `risk_flags`：风险标志列表

**评估维度：**
1. 市场状态 (OPEN/CLOSED/RESOLVED)
2. 时间阶段 (EARLY/MID/LATE/CLOSING)
3. 规则歧义风险 (ambiguity_risk)
4. 结算风险 (resolution_risk)
5. 禁止类别 (forbidden_category)

**lifecycle_score 计算公式：**
```text
lifecycle_score = base_score(phase)
                  - ambiguity_risk * 40
                  - resolution_risk * 25
                  - close_time_risk * 20
```

### 影响

优点：

* 提前识别生命周期风险
* lifecycle_score 作为 Risk Governor 评分的一部分
* 可独立测试和验证

代价：

* 增加一个评估层
* 需要维护评估逻辑

---

## ADR-015：Risk Governor 对关键条件做直接兜底检查

### 状态

Accepted

### 背景

如果 Risk Governor 只依赖 signal.risk_flags 来判断是否拒绝，存在以下风险：
1. 上游引擎可能遗漏设置 risk_flags
2. 数据传递过程中 risk_flags 可能丢失
3. 单一依赖链路不够健壮

### 决策

Risk Governor 对关键安全条件做**直接检查**，不依赖 signal.risk_flags：

**直接检查项：**
1. `market.status != MarketStatus.OPEN` → hard reject "market_not_open"
2. `market.is_ambiguous` → hard reject "market_ambiguous"
3. `not market.is_auto_allowed()` → hard reject "forbidden_category"

**双重兜底：**
- 直接检查作为主要安全来源
- signal.risk_flags 作为补充检查（防止遗漏）

**实现原则：**
```python
# 直接检查（主要）
if market.status != MarketStatus.OPEN:
    reasons.append("market_not_open")

# 信号标志检查（补充）
if "market_not_open" in signal.risk_flags:
    reasons.append("market_not_open")
```

### 影响

优点：

* 双重保障，更健壮
* 不依赖上游正确设置 risk_flags
* 符合防御性编程原则

代价：

* 略有重复检查
* Risk Governor 需要访问 Market 对象

---

## ADR-016：Wallet Intelligence Engine 作为钱包行为分析层

### 状态

Accepted

### 背景

钱包行为是 Polymarket 的重要信号来源。某些钱包可能有更好的预测能力、更高的胜率或更专业的领域知识。但纯 copy trading 存在风险：跟随者可能被利用、钱包可能改变行为、或信号可能是噪声。

### 决策

Wallet Intelligence Engine 作为独立引擎，评估钱包行为：

**输出：**
- `wallet_score` (0-100)：基于钱包画像的综合评分
- `active_wallets`：活跃钱包列表
- `consensus_direction`：钱包共识方向
- `risk_flags`：风险标志列表

**评估维度：**
1. 钱包可靠性 (reliability_score)
2. 钱包表现 (performance_score)
3. 钱包专业化 (specialization_score)
4. 钱包纪律性 (discipline_score)
5. Copy 风险 (copy_risk_score)
6. Chase 风险 (chase_risk)
7. Timing 风险 (timing_risk)

**wallet_score 计算公式：**
```text
wallet_score =
  0.30 * reliability_score
  + 0.35 * performance_score
  + 0.20 * specialization_score
  + 0.15 * discipline_score
  - copy_risk_penalty (copy_risk_score * 0.30, max 30)
```

**wallet_signal_only 硬性拒绝：**
```text
wallet_score >= 80
AND microstructure_score < 60
AND event_score < 60
AND liquidity_score < 60
→ hard reject
```

### 影响

优点：

* 钱包信号可量化
* 防止纯 copy trading
* wallet_score 作为 Risk Governor 评分的一部分

代价：

* 需要维护钱包画像数据
* 钱包行为可能变化

---

## ADR-017：Event Intelligence Engine 作为事件分析层

### 状态

Accepted

### 背景

外部事件（新闻、公告、数据发布）可能影响预测市场价格。但事件分析涉及 LLM，存在幻觉、误读、格式错误等风险。

### 决策

Event Intelligence Engine 作为独立引擎，使用 LLM 分析事件：

**输出：**
- `event_score` (0-100)：基于事件分析的综合评分
- `suggested_mode`：建议处理模式 (ignore/research/alert_only/manual_review/avoid)
- `risk_flags`：风险标志列表

**评估维度：**
1. 证据强度 (evidence_strength)
2. 市场相关性 (market_relevance)
3. 歧义风险 (ambiguity_risk)
4. LLM 置信度 (confidence)

**event_score 计算公式：**
```text
event_score =
  0.40 * evidence_strength
  + 0.30 * market_relevance
  + 0.20 * (100 - ambiguity_risk)
  + 0.10 * confidence * 100
```

**LLM 失败降级规则：**
```text
invalid JSON / schema error / low confidence / timeout / error:
- event_score = 50 (neutral)
- confidence = 0
- suggested_mode = "research" 或 "avoid"
- 添加对应 risk_flag
- 不触发 paper_trade、manual_review 或任何执行动作
```

**event_signal_only 硬性拒绝：**
```text
event_score >= 80
AND microstructure_score < 60
AND wallet_score < 60
AND liquidity_score < 60
→ hard reject
```

**LLM 输出禁止字段：**
```text
side, size, order, position, buy, sell, action
```

如果检测到禁止字段，标记 `llm_forbidden_trading_instruction`。

### 影响

优点：

* 事件信号可量化
* LLM 失败有安全降级
* event_score 作为 Risk Governor 评分的一部分

代价：

* LLM 可能幻觉
* 需要维护 LLM provider

---

## ADR-018：Signal-Only 双重保障机制

### 状态

Accepted

### 背景

如果某个引擎（如 Wallet 或 Event）产生高评分信号，但其他引擎评分都很低，可能表示信号来源单一，存在误判风险。例如，钱包信号可能被操纵，事件信号可能是 LLM 幻觉。

### 决策

Risk Governor 对 signal-only 情况做硬性拒绝：

**wallet_signal_only 检测：**
```text
wallet_score >= 80
AND microstructure_score < 60
AND event_score < 60
AND liquidity_score < 60
→ hard reject "wallet_signal_only_reason"
```

**event_signal_only 检测：**
```text
event_score >= 80
AND microstructure_score < 60
AND wallet_score < 60
AND liquidity_score < 60
→ hard reject "event_signal_only_reason"
```

**双重保障实现：**
1. 检查 signal.risk_flags 中的 "wallet_signal_only" / "event_signal_only"
2. 直接检查 component_scores（主要保障）

### 影响

优点：

* 防止单一信号源误判
* 双重保障更健壮
* 符合防御性编程原则

代价：

* 可能拒绝部分有效信号
* 需要维护检测逻辑

---

## ADR-019：Crypto Threshold Validation 使用 Run-scoped Provenance

### 状态

Accepted

### 背景

历史 shadow runner 使用固定输出目录，并可能丢弃候选的原始时间或复用同一市场的
observation。对于 threshold ladders，这会把旧 ask 当成新 entry，或把相关行误当作
独立样本，导致不可复盘的 PnL。

### 决策

Crypto threshold validation 使用独立 run 目录，且 discovery、entry、observation 和
validation artifact 通过稳定 trade ID 与 SHA-256 provenance 关联。Prepared input 与
最终 shadow trade output 使用独立哈希字段，避免把覆写前哈希误认为最终文件哈希。

稳定 identity 包含 market、side、entry timestamp、threshold、contract kind、barrier
direction、parser version 和 model version。不同语义或模型版本不得复用旧 entry。

Validator 本身不访问网络；公开行情刷新由现有 read-only poller 负责。Poller 在最小
240 分钟 horizon 前必须使用 `--no-update_positions`，generic exit path 不参与 corrected
PnL。旧 `runs/shadow` 目录及其子目录受保护，Step 12 不得覆盖历史证据。

Entry timestamp 只能在 spot 与 YES/NO orderbook 均取得后生成，并保存 client-observed
quote timestamp。默认 entry freshness 与中央 stale policy 对齐为 60 秒。Forward
observation 仅信任 `clob_rest_readonly`，且必须显式携带 `stale=false`、空 error 和未交叉
的同侧 bid/ask。独立 cohort 按 asset、expiry、contract kind 聚合；重复扫描不产生新
cohort。

### 影响

优点：

* entry 和 forward observation 可复盘
* parser/model 变更不会污染旧样本
* stale、cross-run 和 side mismatch 会 fail closed
* 缺失 provenance、freshness 或完整同侧 quote 会 fail closed
* 多轮研究产物不会相互覆盖

代价：

* 需要显式管理 run ID 和 observation cadence
* 在 horizon 成熟前不会产生 PnL

---

## ADR-020：Shadow Execution Cost 使用确定性 L2 Sweep

### 状态

Accepted

### 背景

best bid/ask 只能说明第一档价格存在，无法证明给定 dollar notional 或 shares 能完整成交。
使用第一档价格线性放大 shadow PnL 会忽略多档冲击，并允许大 aggregate liquidity 掩盖
tiny best-level size。

### 决策

新增纯计算的 shadow execution-cost 模块。BUY 固定 notional 时从低到高逐档消耗 asks；
SELL 固定 shares 时从高到低逐档消耗 bids。默认采用 full-fill/fail-closed：可见深度不足、
限价内无足够数量或任一 round-trip leg 不可完整成交时，不生成 PnL。

输出使用明确模型保存 requested/available/filled notional 与 shares、VWAP、best/worst fill、
adverse impact、fee、completion ratio 和逐档 ledger。Round trip 必须用 entry 实际获得的同一
shares 验证 exit。模块无网络、I/O、认证、密钥或下单能力，也不绕过 Risk Governor。

当前 fee 使用显式 flat-notional bps 研究假设，不代表特定 Polymarket 市场的真实动态 fee
schedule。未来接入市场 fee metadata 时必须保留 fee source、timestamp 和公式版本。

### 影响

优点：

* shadow 可成交性不再等同于 best-price 可见性
* 多档价格冲击、限价和深度短缺可确定性复盘
* entry 与 exit 的 quantity conservation 明确
* 可作为 markout、microprice 和 pair-leg risk 的共同成本接口

代价：

* 静态 L2 snapshot 仍不能模拟 queue-ahead、latency、隐藏流动性或 L3/FIFO priority
* maker strategy 仍需要历史 book delta 与 trade tick replay 才能评估 fill probability

---

## ADR-021：Crypto Threshold Validator v4 证据契约

### 状态

Superseded by ADR-022

### 背景

v3 的 shadow artifacts 能保存客户端观察时间和价格，但不能证明 entry 时的 resolution
来源、服务端盘口新鲜度或 best-level 可成交数量。继续 poll 旧 run 会把事后补充的信息
错误地当成 entry-time evidence。

### 决策

从 `crypto_threshold_shadow_pnl_v4` 起，每个候选必须保存并校验：

* resolution source、完整 rules、rules SHA-256 和 `resolution_status=verified`
* YES/NO 四个 best bid/ask price、size，以及两个原始服务端 orderbook timestamp
* client/server freshness，entry 最大年龄 60 秒，未来 clock skew 硬上限 5 秒
* `entry_shares = notional / selected_entry_ask`，entry ask 与 exit bid 都必须覆盖同一份额

Discovery 对未验证 resolution 直接输出 `watch_only`；离线 validator 再次独立拒绝。旧
schema 或缺少 entry-time evidence 的 run 只能审计，禁止 poll、补字段、迁移或参与 PnL。
新 run 必须使用隔离目录、独立输入/输出 SHA-256，并保持 `tiny_live_recommendation=NO`。

### 影响

优点：

* PnL 证据同时具备语义、时间和数量完整性
* 事后数据不能伪造历史成交容量或 resolution provenance
* 数据覆盖不足时系统稳定地产生零 entry，而不是乐观估算

代价：

* 当前 Gamma 批次若缺少结构化 resolutionSource 会全部 watch-only
* 需要后续 versioned source adapter 才能安全识别规则正文中的明确来源 URL

---

## ADR-022：Versioned Resolution-Source Adapter 与 Validator v5

### 状态

Accepted

该决策仍作为 v5 provenance 的历史记录保留；validator/expiry/lifecycle 约束已由 ADR-024
取代，v5 artifacts 只能 audit-only。

### 背景

Gamma 的结构化 `resolutionSource` 在 fresh v4 批次中覆盖 0/44，但规则正文包含明确的
Binance resolution URL。直接信任任意描述 URL 会把宣传链接、多来源冲突或不可信域名
伪装成结算 provenance；继续使用 v4 又无法记录提取逻辑版本。

### 决策

新增共享纯计算 adapter `resolution_source_adapter_v1`，discovery 与 offline validator
使用同一套解析和完整性检查。Adapter 不跟随 URL、不访问网络、不认证；优先使用结构化
Gamma source，否则只接受明确 resolution-source section 中唯一的 HTTPS URL。

Host 必须精确匹配 `docs/risk_policy.md` 的逐项 allowlist，不允许 suffix trust。Binance
进一步限定 `/en/trade/{BTC|ETH|SOL}_USDT`，并验证 candidate asset、规则 pair、1m candle、
up/High/equal-or-greater 或 down/Low/equal-or-lower 语义。Non-string、HTTP、多个 URL、
untrusted host、结构化/规则 source 冲突或语义不一致全部 fail closed。

Schema 升级为 `crypto_threshold_shadow_pnl_v5`。每个 candidate/position 保存 source、origin、
locator、adapter version、rules、rules SHA-256、provenance SHA-256 和 verified status；stable
trade ID 绑定 adapter version、rules hash 与 provenance digest。旧 v4 artifact 只可审计，
不得 migrate、补字段、继续 poll 或参与 PnL。

### 影响

`step12_v5_20260804_073542` 扫描 1,958 markets，解析 44 个 threshold candidates，44/44
通过 rules-URL provenance；discovery 为 16 shadow-entry / 28 watch-only。Strict gate 为
14，revalidation 保留 10 positions / 3 clusters。首次 public CLOB poll 写入 10 observations，
0 error、0 stale、`updated_positions=false`；全部早于 240 分钟，因此 closed=0、PnL=null、
`tiny_live_recommendation=NO`。

该结果建立 forward cohort，但不证明 edge、expectancy 或 profitability。更严格的 provenance
提高了可审计性，也减少了可用 source；allowlist 或语义模板变化必须显式升级 adapter 版本。

---

## ADR-023：Expiry Timezone Provenance 是 Expectancy 前置门槛

### 状态

Accepted; implemented in v6 and superseded as a pending item by ADR-024

### 背景

v5 cohort 的 title parser 输出 naive `2026-12-31T23:59:00`，validator 将 naive timestamp
解释为 UTC；同一市场的 Gamma 规则明确指定 23:59 ET。12 月 ET 转换为 UTC 后约晚五小时。
临近 expiry 时，该偏差会错误截断 forward observation 或改变 lifecycle 判断。

### 决策

Title-derived expiry、Gamma lifecycle timestamp 和 resolution rules timezone 必须分别保存
provenance 并完成一致性校验。Naive title time 不得默认按 UTC 进入 validator cutoff；若时区
缺失、冲突或无法映射，candidate 必须 watch-only/validator reject。

### 影响

当前 v5 run 只能保留为 audit-only；即使 timezone gate 已在 v6 完成，也不得把 v5 用于正
期望、收益或 tiny-live 结论。v6 已使用新的 run-scoped cohort，避免事后改写 entry-time
lifecycle evidence。

## ADR-024：Validator v6 与历史 Barrier 证据门

### 状态

Accepted; implemented and verified 2026-08-04

### 背景

v5 审计发现五个研究完整性问题：ET/UTC expiry 偏差、touch 合约缺少历史 barrier 覆盖、
forward 只验证选择侧、persisted entry 未绑定完整身份，以及 prepared input 被覆盖后无法
复核。继续 poll v5 会把不可复核输入误当作 forward evidence。

### 决策

Discovery 升级为 `crypto_threshold_edge_discovery_v4` / `crypto_threshold_parser_v4`，
接入 `gamma_expiry_adapter_v1`，将 title-local cutoff 按规则 timezone 转成 canonical UTC，
并在 120 秒内与带时区 Gamma `endDate` corroborate。Touch 合约必须有
`verified_full_coverage` 的规则起点到 entry 1m candle artifact，否则只能 watch-only。

Validator 升级为 `crypto_threshold_shadow_pnl_v6`，只接受 discovery/parser v4。它要求完整
resolution/expiry provenance、YES/NO 双边非交叉四档价格和 size、双 server timestamp、
selected-side capacity，以及不少于 240 分钟的 forward horizon。稳定 trade ID 绑定所有
entry evidence、tokens、notional/shares 和 gate fields；覆盖 `shadow_trades.csv` 前保存
内容寻址 immutable snapshot。任何旧 v5 或更早 artifact 均 fail closed。

### 影响

最终只读 run `step12_v6_20260804_083736` 扫描 1,958 markets、解析 44 candidates，44/44
source/expiry verified，但 44/44 缺历史 barrier coverage，因此 `0 shadow_entry / 44
watch_only`、strict gate=0、positions=0、PnL=null，validation status=
`historical_barrier_evidence_required`。Gamma 末页 422 被记录，扫描不宣称 exhaustive。
该结果是完整性门通过的证据，不是 edge 或收益证明；`tiny_live_recommendation` 固定为
`NO`。在当时的决策点，下一步是实现 versioned historical 1m candle coverage adapter；该
工作已由 ADR-025 完成，v6 artifact 仍只保留为 audit-only。

---

## ADR-025：Exact-minute Batch Entry、共享历史证据与 Validator v7

### 状态

Accepted; implemented and verified 2026-08-04

### 背景

ADR-024 建立了 expiry、resolution 和 historical barrier 的前置门，但 v6 仍因缺少规则起点
到 entry 的完整 1m candle coverage 而产生 0 positions。若每个 threshold ladder 行分别
下载和解析同一资产的 candles，会重复外部请求、放大 entry 后处理延迟，并让相关候选看似
拥有独立历史样本。若先收集 quote、再决定 entry 时间，则 entry evidence 也无法证明是在
同一预先承诺的时点观察到的。

### 决策

Discovery 升级为 `crypto_threshold_edge_discovery_v5`。每批运行必须在采集 quote 前承诺一个
未来的 exact UTC minute；spot、client-observed quote 和 YES/NO CLOB server timestamps
必须不晚于该 batch entry，且在 entry 时不超过 60 秒。时间证据缺失、过期、来自未来或
互相冲突时一律 fail closed。

Historical barrier evidence 按资产共享：每个资产只做一次 preload、一次 entry tail，并生成
一个 content-addressed shared candle snapshot。每个 threshold candidate 仍生成独立 manifest，
绑定 rules-defined start、threshold、direction、snapshot reference、coverage 与 provenance
digests；共享 candles 不得把同一 ladder 的多行解释为独立 cohort。Gamma `startDate` 只保存
为 lifecycle metadata，不得替代或重定义规则正文中的 barrier start。缺少 rules-defined
start 时不得发起历史请求来猜测起点，candidate 必须 `watch_only`；manifest、snapshot、
locator、digest 或 coverage 任一缺失/不一致时，discovery 和 validator 都必须拒绝 entry。

Validator 升级为 `crypto_threshold_shadow_pnl_v7`，只接受 discovery v5，并继续要求完整
resolution/expiry/history/entry identity、YES/NO 双边盘口、同份额容量守恒和可信 public
read-only CLOB observation。Forward observation 必须严格晚于 entry、达到至少 240 分钟且
不晚于 expiry；不满足时 exit、return 和 PnL 保持 null。任何 expectancy 或推进评估还必须
覆盖至少 5 个独立 asset/expiry/contract-kind clusters。v6 及更早 artifacts 只能 audit-only，
不得补字段、迁移、复用或继续 poll；正式 v7 cohort 只有在达到 240 分钟 horizon 后才可做
一次新的只读观察采集，且仍必须通过全部 forward gates。

### 影响

正式 cohort `step12_v7_20260804_140305` 扫描 1,958 markets，识别 56 个 crypto markets 和
44 个 threshold candidates。Discovery 以 3 preloads + 3 entry tails 生成 3 个 shared candle
snapshots 和 43 个 threshold-specific manifests；43/44 historical barriers verified，缺少
rules-defined start 的 1 个 candidate 保持 fail closed。Public CLOB 加载 85/88 orderbooks，
其余 3 个不完整读取保持 fail closed；最终产生 12 `shadow_entry` / 32 `watch_only`。Gamma
pagination 最后一页记录了 recoverable error，因此不宣称扫描 exhaustive。

Validator v7 创建 11 个 fresh paper positions（BTC 3 / ETH 5 / SOL 3），仅分布在 3 个相关
clusters；closed=0、11 个 `insufficient_forward_data`、forward coverage=0.0、PnL=null、win
rate=null，status=`insufficient_forward_data`。因此 historical barrier integration 虽已完成，
当前 blocker 仍是成熟的 >=240-minute forward observations 与至少 5 个独立 clusters。
该 cohort 不证明 edge、expectancy 或 profitability；`supports_tiny_live=false`，
`tiny_live_recommendation=NO`。本决策不增加认证、签名、密钥访问或执行能力，live trading
继续默认关闭。

---

## ADR-026：运行时下限提升为 Python 3.11（取代 ADR-012）

### 状态

Accepted (2026-09-11)

### 背景

ADR-012 决定支持 Python 3.9+，前提是全库使用 `Optional[X]` 而非 `X | None`。该前提已在
代码演进中失效：`polysignal/execution/paper_trader.py`、`polysignal/shadow/*` 等模块在类体
中直接使用 `X | None`（PEP 604），该表达式在类定义时急切求值。2026-09-11 实测：在
Python 3.9.6 下 `python3 -m pytest` 收集即失败（`TypeError: unsupported operand type(s)
for |: 'ModelMetaclass' and 'NoneType'`），3.9 兼容事实上已不存在。项目实际运行环境为
uv 管理的 Python 3.11.15 venv（CONTEXT.md 历史基线均基于此）。

### 决策

* `pyproject.toml` 的 `requires-python` 从 `>=3.9` 修正为 `>=3.11`
* classifiers 移除 3.9/3.10；black target-version 改为 `py311`；mypy `python_version` 改为 `3.11`
* 文档与 CI 指引统一声明：本项目只能通过 `uv run`（或等价的 3.11+ 解释器）执行

### 影响

优点：

* 工具链声明与代码现实一致，消除 3.9/3.10 用户的必然报错
* 类体中的 PEP 604 注解、`Self` 类型等 3.11 特性可正常使用

代价：

* 理论上放弃 3.9/3.10 兼容；该兼容在实测中早已不可用，因此无实际损失

---

## ADR-027：历史 Barrier K 线证据多源化（Binance 主源 + Coinbase 回退）

### 状态

Accepted (2026-09-12，用户批准的 SPEC 级数据源扩展)

### 背景

v8 discovery（2026-09-12）的 46 个候选中 45 个因 Binance 返回 HTTP 451（地域封锁）
无法取得历史 barrier K 线证据（v7 时期同环境为 43/44 verified），导致 0 仓位创建、
cohort 扩张停滞（3 clusters < 5 的 expectancy 前置无法推进）。v7 契约要求 barrier
证据使用 1 分钟 OHLC 且来源为 allowlist 主机；Binance 是唯一的 K 线源，构成单点依赖。

### 决策

1. `CoinbaseHistoricalCandleClient`：Coinbase Exchange 公共 candles API
   （`api.exchange.coinbase.com/products/{pair}/candles`，granularity=60），
   与 Binance 客户端同一 `fetch_klines` 契约与全部验证规则（分钟对齐、连续性、
   单调性、行内范围）；symbol 映射 BTC→BTC-USD / ETH→ETH-USD / SOL→SOL-USD。
2. `MultiSourceHistoricalKlineClient`：Binance 主源，仅当失败为源级
   （HTTP 4xx/5xx、超时、无效响应）时回退 Coinbase；范围级结果
   （partial/contiguity）不触发回退（数据属性在两源等价，保留主源结果可审计）。
3. 验证链 source-aware 化：`VERIFIED_HISTORICAL_BARRIER_SOURCES` 注册表 +
   按源 locator/symbol 校验（BTC-USD 等 pair 形式）；证据材料记录实际服务的
   source/locator；merged preload/tail 校验要求同一非空 verified source。
4. **字段差异披露**：Coinbase 不提供 quote volume / trade counts，这些列持久化为
   "0"（快照保持 Binance 行格式统一；barrier 验证只消费 open/high/low/close）。
5. **基差披露**：Coinbase 为 USD 计价，Binance 为 USDT——阈值触碰验证引入
   USD/USDT 基差近似（BTC/ETH/SOL 现货基差通常 <0.1%），source 字段已记录
   供审计者复核边界案例。

### 影响

优点：消除单点地域依赖，cohort 扩张可继续；证据 provenance 记录真实来源。
代价：跨源基差近似（已披露）；Coinbase 300 candle/页的额外分页。
维持不变：fail-closed 全部门禁、240 分钟水平线、exact-minute batch entry、
`supports_tiny_live` 判定逻辑。

---

## ADR-028：Crypto Threshold 资产宇宙扩展（+XRP/DOGE/BNB/LINK）

### 状态

Accepted (2026-09-12，用户批准；达成 ≥5 独立 cluster expectancy 前置的必要路径)

### 背景

Cluster 契约键为 (asset, expiry, contract_kind)。当前市场池 46 个候选全部是
2026-12-31 到期的 touch 市场，cluster 上限恒为 3（BTC/ETH/SOL），expectancy 评估
所需的 ≥5 独立 cluster 在现有资产宇宙内**数学上不可达**。对 v10 Gamma 快照
（2100 unique markets）的离线全量扫描发现：XRP×14、DOGE×12、BNB×11、LINK×8 个
阈值市场，且抽样核验其 resolutionSource 全部为
`https://www.binance.com/en/trade/{XRP|DOGE|BNB|LINK}_USDT` ——已在 allowlist
host 上、且与现有 `_BINANCE_PATH_RE` 模式完全同构，仅资产组缺失。

### 决策

资产表驱动扩展（4 处，全为纯数据表）：

1. discovery：`ASSET_ALIASES` / `BINANCE_SYMBOLS` / `ANNUAL_VOL_PROXY` 增加四资产
   （vol proxy 值为文档化的量级估计：XRP 0.90 / DOGE 1.10 / BNB 0.70 / LINK 0.95）
2. resolution adapter：`_BINANCE_PATH_RE` 资产组扩展；`_ASSET_SOURCE_ALIASES` 同步
3. barrier 模块：`BINANCE_SYMBOLS` / `COINBASE_SYMBOLS` 同步（Coinbase 四资产
   pair 均实际存在：XRP-USD/DOGE-USD/BNB-USD/LINK-USD）

### 影响

优点：cluster 上限从 3 → 7（BTC/ETH/SOL/XRP/DOGE/BNB/LINK × 同一到期 × touch），
expectancy 前置在数学上可达。
代价：新资产的 vol proxy 是量级估计（已文档化，非精确校准）；DOGE 基准价数量级
小（$0.2），阈值解析需处理小数精度（parser v4 已支持任意精度阈值）。
维持不变：全部 fail-closed 门、resolution/expiry/barrier 验证语义、cluster 契约键。
