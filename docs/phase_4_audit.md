# Phase 4 Audit — Real Read-only Data Layer Audit

## 概述

本文档记录 Phase 4 (Real Read-only Polymarket API) 的审计结果，包括 REST API 和 WebSocket 的真实协议验证。

---

## Phase 4A — REST API 验证摘要

### 验证日期
2026-05-07

### 验证方式
`scripts/smoke_real_readonly.py`

### 验证结果
✅ **通过**

### 关键发现

**Gamma API:**
- URL: `https://gamma-api.polymarket.com`
- 公开数据，无需认证
- `clobTokenIds` 和 `outcomes` 字段返回 JSON 字符串，需要 `json.loads()` 解析
- 每个市场有 YES token 和 NO token

**CLOB REST API:**
- URL: `https://clob.polymarket.com`
- Orderbook 按 token_id 获取
- 需要分别获取 YES 和 NO token 的 orderbook

### 测试数据
```
Markets Fetched:        100
Markets Usable:         5
Orderbooks Fetched:     3
Signals Generated:      0 (YES/NO mispricing conditions not met)
```

---

## Phase 4B — WebSocket 验证摘要

### 验证日期
2026-05-07

### 验证方式
`scripts/smoke_ws_readonly.py`

### 验证结果
✅ **通过**

### 关键发现

**WebSocket URL:**
```
wss://ws-subscriptions-clob.polymarket.com/ws/market
```

**订阅消息格式:**
```json
{
    "type": "subscribe",
    "channel": "market",
    "assets_ids": ["token_id_1", "token_id_2"]
}
```

**重要协议细节:**

1. **字段名**: `assets_ids`（复数），不是 `asset_ids`
2. **必须包含**: `channel: "market"`
3. **返回格式**: 消息是数组，不是单个对象
4. **消息类型**: 没有 `type` 字段，直接包含 orderbook 数据

**返回消息示例:**
```json
[
    {
        "market": "0x9c1a953fe92c8357f1b646ba25d983aa83e90c525992db14fb726fa895cb5763",
        "asset_id": "8501497159083948713316135768103773293754490207922884688769443031624417212426",
        "timestamp": "1778161557552",
        "hash": "558f5bf3469fdf02dac71a43cd50d3b3dcd6885d",
        "bids": [{"price": "0.01", "size": "2054325.28"}, ...],
        "asks": [{"price": "0.99", "size": "100"}, ...]
    }
]
```

### 测试数据
```
WebSocket Connected:    True
Messages Received:      4
Tokens Subscribed:     4
Orderbooks Cached:     4
```

---

## 真实 API 协议发现

### REST API

| 端点 | URL | 认证 | 说明 |
|------|-----|------|------|
| Gamma Markets | `GET https://gamma-api.polymarket.com/markets` | 无 | 市场列表 |
| Gamma Market | `GET https://gamma-api.polymarket.com/markets/{id}` | 无 | 单个市场 |
| CLOB Orderbook | `GET https://clob.polymarket.com/book?token_id={id}` | 无 | Orderbook |
| CLOB Price | `GET https://clob.polymarket.com/price?token_id={id}` | 无 | 价格 |
| CLOB Tickers | `GET https://clob.polymarket.com/tickers` | 无 | 所有 ticker |

### WebSocket

| Channel | URL | 认证 | 说明 |
|---------|-----|------|------|
| Market | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | 无 | 实时 orderbook |

### 订阅协议

```json
// 发送
{
    "type": "subscribe",
    "channel": "market",
    "assets_ids": ["token_id_1", "token_id_2"]
}

// 接收（数组格式）
[
    {
        "market": "condition_id",
        "asset_id": "token_id",
        "timestamp": "unix_timestamp_ms",
        "bids": [{"price": "0.50", "size": "100"}, ...],
        "asks": [{"price": "0.51", "size": "100"}, ...]
    }
]
```

---

## 当前数据流

```
┌─────────────────────────────────────────────────────────────┐
│                     Data Provider Manager                    │
│                    (mock / real_readonly / hybrid)           │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │   Mock      │     │  REST API   │     │  WebSocket  │
   │   Provider  │     │  (fallback) │     │  (primary)  │
   └─────────────┘     └─────────────┘     └─────────────┘
          │                   │                   │
          └───────────────────┼───────────────────┘
                              ▼
                    ┌─────────────────┐
                    │ OrderBook Cache │
                    │  (per token_id) │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ OrderBookSnapshot│
                    │  (YES + NO 合成) │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │     Engines     │
                    │  - Microstructure│
                    │  - Lifecycle    │
                    │  - Wallet       │
                    │  - Event        │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Risk Governor   │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Paper Trader   │
                    └─────────────────┘
```

---

## 安全状态

### 当前配置
```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
```

### 安全保证

| 检查项 | 状态 |
|-------|------|
| 无私钥处理 | ✅ |
| 无认证操作 | ✅ |
| 无订单提交 | ✅ |
| 无账户操作 | ✅ |
| WebSocket 只读 | ✅ |
| Risk Governor 拦截 | ✅ |

---

## 已知限制

### REST API
- `clobTokenIds` 和 `outcomes` 返回 JSON 字符串，需要解析
- Orderbook 需要分别获取 YES 和 NO token
- 有速率限制，需要合理控制请求频率

### WebSocket
- 订阅字段名是 `assets_ids`（复数），容易拼写错误
- 返回消息是数组，需要遍历处理
- 消息没有 `type` 字段，需要根据内容判断
- 价格和大小是字符串格式，需要转换为数值
- 需要维护 token_id 到 market_id 的映射

### 数据层
- Mock 数据与真实数据格式可能不完全一致
- Hybrid 模式下，REST fallback 可能导致数据延迟
- Stale 检测阈值需要根据实际情况调整

---

## 测试覆盖

### 测试结果
```
pytest tests/ -v
430/430 passed, 8 warnings
```

### 测试分布

| 模块 | 测试文件 | 测试数量 |
|------|---------|---------|
| REST API | test_gamma_client.py | ~20 |
| REST API | test_clob_client.py | ~20 |
| REST API | test_data_converter.py | ~20 |
| REST API | test_data_provider_manager.py | ~15 |
| WebSocket | test_websocket_client.py | 21 |
| WebSocket | test_websocket_message_handler.py | 18 |
| WebSocket | test_orderbook_cache.py | 17 |
| WebSocket | test_subscription_manager.py | 14 |
| WebSocket | test_reconnection_strategy.py | 10 |
| 其他 | ... | ~275 |

### Mock 策略
- 所有测试使用 mock HTTP/WebSocket
- 不依赖真实 Polymarket API
- Smoke tests 是可选的手动验证

---

## 下一阶段建议

### Phase 4C — Real LLM Providers Integration

**目标**: 接入真实 LLM 提供商，替换 Mock LLM

**候选提供商**:
- DeepSeek V4 Flash
- GLM 5.0

**注意事项**:
- LLM 仅用于 Event Intelligence Engine
- LLM 输出禁止包含交易执行字段
- 需要处理 LLM 失败降级
- 需要验证 LLM 输出格式

### 不建议的下一步

- ❌ 直接进入实盘交易
- ❌ 绕过 Risk Governor
- ❌ 修改 live_trading_enabled
- ❌ 处理真实私钥

---

## 文件清单

### 核心模块
```
polysignal/ingestion/
├── gamma_client.py           # Gamma REST API
├── clob_client.py            # CLOB REST API
├── websocket_client.py       # CLOB WebSocket
├── websocket_message_handler.py  # 消息解析
├── orderbook_cache.py        # 缓存管理
├── subscription_manager.py   # 订阅管理
├── reconnection_strategy.py  # 重连策略
├── data_converter.py         # 数据转换
├── data_provider_manager.py  # 统一接口
├── api_types.py              # API 类型定义
└── api_errors.py             # 错误类型
```

### 配置文件
```
config/
├── app.yaml          # 应用配置
├── websocket.yaml    # WebSocket 配置
└── ...
```

### Smoke Tests
```
scripts/
├── smoke_real_readonly.py   # REST API smoke test
└── smoke_ws_readonly.py     # WebSocket smoke test
```

### 文档
```
docs/
├── phase_4_api.md      # API 文档
└── phase_4_audit.md    # 本文档
```

---

## 审计结论

Phase 4 (Real Read-only Data Layer) 已完成验证：

1. ✅ REST API 真实数据获取正常
2. ✅ WebSocket 真实数据获取正常
3. ✅ 协议细节已记录并验证
4. ✅ 安全状态保持 read-only
5. ✅ 测试覆盖完整 (430/430)
6. ✅ 文档已更新

**建议**: 可以进入 Phase 4C Planning — Real LLM Providers Integration
