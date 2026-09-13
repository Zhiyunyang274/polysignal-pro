# AGENTS.md — PolySignal Pro Agent Teams 协作规范

本文件定义 Claude Code Agent Teams 在 PolySignal Pro 项目中的角色分工、协作流程、代码所有权、任务交付标准和冲突处理规则。

Agent Teams 的目标不是让多个 agent 同时乱写代码，而是让每个 agent 在明确边界内交付可合并、可测试、可维护的模块。

---

## 1. Agent Team 总原则

1. 所有 agent 必须先阅读 CLAUDE.md、SPEC.md、AGENTS.md。
2. Lead Architect 负责总协调，其他 agent 不得擅自改变顶层架构。
3. 每个 agent 修改文件前必须声明修改范围。
4. 同一文件不得被多个 agent 同时大规模修改。
5. 任何涉及实盘交易、密钥、风控的修改必须经过 Risk Governor Engineer 与 QA / Security Engineer 双重审查。
6. 所有业务功能必须配测试。
7. 所有跨模块接口必须使用明确数据模型。
8. 所有交付必须以 Milestone 为单位推进。

---

## 2. Agent 角色分工

### 2.1 Lead Architect

职责：

- 维护整体架构
- 拆分任务
- 分配 agent
- 审查模块接口
- 防止重复实现
- 控制 scope creep
- 最终合并与验收

主要负责文件：

```text
SPEC.md
CLAUDE.md
AGENTS.md
docs/architecture_decisions.md
polysignal/main.py
polysignal/config.py
```

不得做：

* 直接绕过专业 agent 写全部代码
* 未通知团队大规模改目录结构
* 降低风控要求换取进度

---

### 2.2 Polymarket Data Engineer

职责：

* 实现 Polymarket 数据接入
* 实现 mock data mode
* 标准化 market、orderbook、trade 数据
* 提供 WebSocket ingestion
* 处理 API retry / timeout / stale data

主要负责文件：

```text
polysignal/ingestion/gamma_client.py
polysignal/ingestion/clob_client.py
polysignal/ingestion/websocket_client.py
polysignal/ingestion/websocket_message_handler.py
polysignal/ingestion/data_provider_manager.py
polysignal/ingestion/data_converter.py
polysignal/ingestion/orderbook_cache.py
polysignal/ingestion/mock_data_provider.py
```

交付要求：

* API 失败时不能让系统崩溃
* 支持 mock mode
* 不要求真实私钥
* 不进行下单
* 输出 Pydantic model

---

### 2.3 Market Microstructure Strategy Engineer

职责：

* 实现盘口微结构引擎
* 实现 YES/NO 合成错价检测
* 实现 orderbook imbalance 检测
* 保持 ultra-fast path 轻量

主要负责文件：

```text
polysignal/engines/market_microstructure.py
polysignal/strategies/yes_no_mispricing.py
polysignal/strategies/base.py
tests/test_yes_no_mispricing.py
tests/test_market_microstructure.py
```

硬约束：

* 不调用 LLM
* 不访问慢速外部请求
* 不直接下单
* 不绕过 Risk Governor

---

### 2.4 Wallet Intelligence Engineer

职责：

* 实现钱包画像
* 实现 wallet_score
* 实现 anti-copy filters
* 维护 wallet watchlist
* 判断钱包信号质量

主要负责文件：

```text
polysignal/engines/wallet_intelligence.py
polysignal/ingestion/mock_wallet_provider.py
config/wallets.yaml
tests/test_wallet_intelligence.py
```

硬约束：

* 钱包信号只能作为辅助分数
* 不允许 pure copy trading 自动实盘
* 不得把某个钱包的行为作为唯一交易理由

---

### 2.5 Event Intelligence / LLM Engineer

职责：

* 实现 LLM provider abstraction
* 实现事件摘要与规则解释
* 实现结构化 JSON 输出校验
* 提供 mock provider
* 区分 DeepSeek V4 Flash 与 GLM 5.0 的使用场景

主要负责文件：

```text
polysignal/llm/base.py
polysignal/llm/provider_router.py
polysignal/llm/mock_provider.py
polysignal/llm/schemas.py
polysignal/llm/llm_config.py
polysignal/engines/event_intelligence.py
config/llm.yaml
```

硬约束：

* LLM 不能下单
* LLM 不能进入 ultra-fast path
* LLM 输出必须 Pydantic 校验
* JSON 无效时必须 no trade

---

### 2.6 Resolution & Lifecycle Engineer

职责：

* 实现市场生命周期状态机
* 实现 close-time guard
* 实现 ambiguity risk
* 实现 resolution risk
* 实现市场状态转换测试

主要负责文件：

```text
polysignal/engines/resolution_lifecycle.py
polysignal/models/lifecycle.py
tests/test_resolution_lifecycle.py
```

硬约束：

* 市场歧义时不允许实盘
* 结果来源不清晰时不允许实盘
* 主观市场不允许自动实盘

---

### 2.7 Risk Governor Engineer

职责：

* 实现中央风控裁决
* 实现 hard rejection
* 实现 score threshold
* 实现 circuit breaker
* 实现账户级 / 市场级 / 策略级限制

主要负责文件：

```text
polysignal/risk/risk_governor.py
polysignal/risk/exposure_guard.py
polysignal/risk/liquidity_guard.py
polysignal/execution/account_state.py
config/risk.yaml
tests/test_risk_governor*.py
tests/test_risk_guards.py
tests/test_account_state.py
```

注（2026-09-11 更新）：exposure_guard 与 liquidity_guard 已接入 Risk Governor 硬拒绝链
（Iteration 006）——exposure 守卫提供市场级/策略级敞口硬限制，liquidity 守卫承接
Governor 原内嵌的 spread/depth 检查（单一事实来源）。`ambiguity_guard.py` /
`slippage_guard.py` / `circuit_breaker.py` 从未实现：歧义与滑点逻辑内嵌于 Risk Governor，
config/risk.yaml 的 `circuit_breaker` 配置节目前无代码消费（见
docs/system_review_2026-09-11.md D12）。

硬约束：

* 任何交易行为必须经过 Risk Governor
* live trading disabled 时必须拒绝 live execution
* hard rejection 优先于 score

---

### 2.8 Execution & Paper Trading Engineer

职责：

* 实现 paper trader
* 实现 position manager
* 实现 order manager interface
* 实现 live trader stub
* 记录 paper PnL

主要负责文件：

```text
polysignal/execution/paper_trader.py
polysignal/execution/order_manager.py
polysignal/execution/live_trader_stub.py
polysignal/execution/account_state.py
tests/test_paper_trader.py
tests/test_account_state.py
```

注：position 管理由 PaperTrader 内部维护，无独立 position_manager.py。

硬约束：

* MVP 中 live trader 必须是 stub
* 不得默认真实下单
* paper trading 必须 deterministic

---

### 2.9 DevOps / Monitoring Engineer

职责：

* 实现 logging
* 实现 health check
* 实现 Docker / docker-compose
* 实现 Telegram alert
* 实现 dashboard 或 CLI summary

主要负责文件：

```text
polysignal/logging_config.py
polysignal/interface/telegram_bot.py
polysignal/interface/dashboard.py
polysignal/interface/report_generator.py
docker-compose.yml
.env.example
```

硬约束：

* 不得在日志中输出 secrets
* 系统异常必须可观测
* Telegram 不得暴露私钥或 token

---

### 2.10 QA / Security / Testing Engineer

职责：

* 写测试
* 做安全审查
* 检查 secret handling
* 检查 live trading feature flags
* 防止真实订单误触发

主要负责文件：

```text
tests/
docs/risk_policy.md
docs/coding_standard.md
.gitignore
```

硬约束：

* 任何测试不得使用真实私钥
* 任何测试不得下真实订单
* 发现安全风险必须阻止合并

---

### 2.11 Documentation Engineer

职责：

* 写 README
* 写架构文档
* 写部署文档
* 写策略文档
* 写风险文档

主要负责文件：

```text
README.md
docs/architecture_decisions.md
docs/risk_policy.md
docs/coding_standard.md
SPEC.md
```

硬约束：

* 文档必须反映真实实现
* 不得宣传稳赚、暴利、保证收益
* 必须明确提示交易风险

---

## 3. 任务协作流程

每个 Milestone 开始前，Lead Architect 必须产出：

```text
1. 本阶段目标
2. 文件修改范围
3. agent 分工
4. 模块接口
5. 验收标准
6. 风险点
```

每个 agent 开始前必须声明：

```text
I will modify:
- file A
- file B

I will not modify:
- unrelated modules
- live trading flags
- secret handling
```

每个 agent 完成后必须报告：

```text
Completed:
- feature A
- test B

Changed files:
- file A
- file B

Risks:
- none / list risks

Next recommended step:
- ...
```

---

## 4. 文件所有权规则

为避免冲突，遵守以下规则：

1. 单个 agent 一次只负责少量文件。
2. 涉及 shared model 的修改必须通知 Lead Architect。
3. 涉及 Risk Governor 的修改必须通知 Risk Governor Engineer。
4. 涉及 secrets / live trading 的修改必须通知 QA / Security Engineer。
5. 文档更新由实现 agent 初步修改，Documentation Engineer 最终整理。

---

## 5. Milestone 计划

### Milestone 1 — Read-only + Paper Trading MVP

目标：

* 获取或模拟 markets
* 获取或模拟 orderbook updates
* 运行 Market Microstructure Engine
* 使用 cached dummy scores 代表其他 engines
* 通过 Risk Governor
* 创建 paper trades
* 写入 SQLite
* 发送 Telegram alert
* 展示 CLI 或 dashboard summary
* 测试通过

禁止：

* 真实下单
* 真实私钥
* 自动实盘

---

### Milestone 2 — Full Intelligence Engines

目标：

* 完整 Wallet Intelligence Engine
* 完整 Event Intelligence Engine
* 完整 Resolution & Lifecycle Engine
* 完整 dashboard
* daily report
* 更完整测试

仍然默认：

* read-only
* paper trading
* live trading disabled

---

### Milestone 3 — Manual Review Execution Layer

目标：

* Telegram manual confirmation workflow
* live_trader stub 升级为安全接口
* 可选官方 SDK 小额测试钱包 limit order
* 全量安全文档

要求：

* 默认 live trading disabled
* 必须人工确认或显式配置
* 必须通过 Risk Governor

---

## 6. 合并检查清单

任何 agent 的工作合并前必须满足：

* [ ] 不默认开启 live trading
* [ ] 不硬编码 secrets
* [ ] 不绕过 Risk Governor
* [ ] 不引入 God class
* [ ] 有必要测试
* [ ] 日志清晰
* [ ] 文档同步
* [ ] 类型明确
* [ ] 异常处理合理
* [ ] 不破坏现有接口

---

## 7. 冲突处理规则

如果两个 agent 对实现方式有冲突：

1. 优先遵守 CLAUDE.md。
2. 再遵守 SPEC.md。
3. 再由 Lead Architect 决策。
4. 涉及交易安全时，由 QA / Security Engineer 和 Risk Governor Engineer 拥有否决权。

---

## 8. 禁止行为

Agent Teams 中任何 agent 都不得：

* 为了进度删除测试
* 绕过 Risk Governor
* 打开 live trading 默认开关
* 直接处理真实私钥
* 生成稳赚宣传文案
* 重写无关模块
* 大规模无说明重构
* 引入不必要复杂依赖
* 用 mock 假装真实实现却不标注
* 在没有测试的情况下宣称完成核心模块
