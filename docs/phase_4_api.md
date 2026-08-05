# Phase 4 — Real Read-only Polymarket API Integration

## 概述

Phase 4 实现了 Polymarket 真实只读 API 接入，包括 REST API 和 WebSocket 实时数据。

**重要**: Phase 4 是只读阶段，不涉及：
- 真实下单
- 私钥处理
- 认证操作
- Authenticated endpoints

---

## 验证状态

| Phase | 描述 | 状态 |
|-------|------|------|
| Phase 4A | Gamma REST + CLOB REST | ✅ Verified |
| Phase 4A.5 | REST Smoke Test | ✅ Passed |
| Phase 4B | CLOB WebSocket | ✅ Verified |
| Phase 4B.5 | WebSocket Smoke Test | ✅ Passed |

**测试结果**: 430/430 passed, 8 warnings

---

## 数据模式

系统支持三种数据模式：

| 模式 | 说明 |
|------|------|
| `mock` | 仅使用模拟数据（默认） |
| `real_readonly` | 仅使用真实 API |
| `hybrid` | 优先真实 API，失败降级到 mock |

### 配置方式

**方式 1: 环境变量**
```bash
DATA_MODE=mock  # 或 real_readonly 或 hybrid
```

**方式 2: 配置文件**
```yaml
# config/app.yaml
data_mode: "mock"
```

---

## API 架构

```
Polymarket API
├── Gamma API (https://gamma-api.polymarket.com)
│   ├── GET /markets - 获取市场列表
│   └── GET /markets/{id} - 获取单个市场
│
├── CLOB REST API (https://clob.polymarket.com)
│   ├── GET /book?token_id={id} - 获取 orderbook
│   ├── GET /price?token_id={id} - 获取价格
│   └── GET /tickers - 获取所有 ticker
│
└── CLOB WebSocket (wss://ws-subscriptions-clob.polymarket.com/ws/market)
    └── Market Channel - 实时 orderbook 更新
```

**关键点**:
- 公开数据不需要 API key
- Orderbook 按 token_id 获取（非 market_id）
- 每个市场有 YES token 和 NO token
- WebSocket 使用 Market Channel，订阅 asset_ids

---

## 模块结构

```
polysignal/ingestion/
├── api_types.py        # API 响应类型定义
├── api_errors.py       # API 错误类型
├── gamma_client.py     # Gamma API 客户端
├── clob_client.py      # CLOB REST 客户端（只读）
├── data_converter.py   # API 数据转换器
└── data_provider_manager.py  # 统一数据管理器
```

---

## GammaAPIClient

用于市场发现：

```python
from polysignal.ingestion.gamma_client import GammaAPIClient

client = GammaAPIClient()

# 获取市场列表
markets = await client.get_markets(limit=100)

# 获取单个市场
market = await client.get_market("market_id")

# 按 slug 获取
market = await client.get_market_by_slug("market-slug")
```

---

## CLOBReadOnlyClient

用于 orderbook 数据：

```python
from polysignal.ingestion.clob_client import CLOBReadOnlyClient

client = CLOBReadOnlyClient()

# 获取单个 token 的 orderbook
orderbook = await client.get_orderbook("token_id")

# 获取市场完整 orderbook（YES + NO）
yes_book, no_book = await client.get_market_orderbook(
    yes_token_id="yes_token",
    no_token_id="no_token",
)

# 获取价格
price = await client.get_price("token_id")

# 获取所有 ticker
tickers = await client.get_tickers()
```

---

## DataConverter

将 API 数据转换为内部模型：

```python
from polysignal.ingestion.data_converter import DataConverter

# Gamma market → Market
market = DataConverter.gamma_to_market(gamma_market)

# CLOB orderbooks → OrderBookSnapshot
snapshot = DataConverter.clob_orderbooks_to_snapshot(
    yes_orderbook=yes_book,
    no_orderbook=no_book,
    market_id="market_id",
)
```

### 防御性解析

DataConverter 处理以下情况：
- 缺失字段 → 默认值
- 未知分类 → `MarketCategory.OTHER`
- 无效 token IDs → 跳过 orderbook
- 无效日期 → `None`
- 字符串数字解析失败 → `0.0`

---

## DataProviderManager

统一数据接口：

```python
from polysignal.ingestion.data_provider_manager import (
    DataProviderManager,
    DataMode,
)

# 创建管理器
manager = DataProviderManager(
    mode=DataMode.HYBRID,  # 或 MOCK / REAL_READONLY
)

# 获取市场
markets = await manager.get_markets()

# 获取 orderbook
orderbook = await manager.get_orderbook("market_id")

# 关闭连接
await manager.close()
```

### Fallback 行为

**HYBRID 模式**:
1. 尝试真实 API
2. API 失败 → 自动降级到 mock
3. 记录警告日志

**REAL_READONLY 模式**:
1. 使用真实 API
2. API 失败 → 抛出 `APIError`

---

## 错误处理

```python
from polysignal.ingestion.api_errors import (
    APIError,
    APITimeout,
    APIConnectionError,
    APIRateLimit,
    APINotFound,
    APIServerError,
    GammaAPIError,
    CLOBError,
)
```

### 重试策略

- 最大重试次数: 3（可配置）
- 指数退避: 1s, 2s, 3s
- 超时: 10s（可配置）

---

## 测试

所有测试使用 mock HTTP 响应：

```bash
pytest tests/test_gamma_client.py -v
pytest tests/test_clob_client.py -v
pytest tests/test_data_converter.py -v
pytest tests/test_data_provider_manager.py -v
```

测试不依赖真实 Polymarket API。

---

## 安全保证

### Phase 4A 不包含

| 功能 | 原因 |
|------|------|
| 真实下单 | 只读阶段 |
| 私钥处理 | 只读不需要 |
| 认证客户端 | 只读不需要 |
| POST /order | 只读阶段 |
| DELETE /order | 只读阶段 |
| approve/allowance | 只读阶段 |
| WebSocket | Phase 4B |

### 保持不变

```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
```

---

## 使用示例

### Mock 模式（默认）

```python
from polysignal.ingestion.data_provider_manager import DataProviderManager, DataMode

manager = DataProviderManager(mode=DataMode.MOCK)
markets = await manager.get_markets()
# 返回模拟数据
```

### Real Readonly 模式

```python
manager = DataProviderManager(mode=DataMode.REAL_READONLY)
markets = await manager.get_markets()
# 返回真实 API 数据，失败抛出异常
```

### Hybrid 模式

```python
manager = DataProviderManager(mode=DataMode.HYBRID)
markets = await manager.get_markets()
# 优先真实 API，失败降级到 mock
```

---

## Smoke Test

### 运行方式

```bash
python scripts/smoke_real_readonly.py
```

### 功能

Smoke test 执行以下操作：

1. 使用 `DataMode.REAL_READONLY` 模式
2. 从 Gamma API 拉取最多 5 个活跃市场
3. 过滤出具有 YES/NO token ID 的市场
4. 对 1-3 个市场获取 CLOB REST orderbook
5. 将真实数据转换为 Pydantic models
6. 运行完整 pipeline：
   - Market Microstructure Engine
   - Resolution & Lifecycle Engine
   - Wallet Intelligence Engine
   - Event Intelligence Engine
   - Risk Governor
   - Paper Trader (如果允许)
7. 输出 CLI summary

### 输出示例

```
============================================================
PolySignal Pro - Real Read-only API Smoke Test
============================================================
Started: 2024-01-15T12:00:00Z
Mode: REAL_READONLY
============================================================

[Step 1] Fetching markets from Gamma API...
  Fetched 100 markets

[Step 2] Filtering markets with valid token IDs...
  Found 5 usable markets

[Step 3] Fetching orderbooks (max 3)...
  Fetching orderbook for: Will BTC reach $100k?...
    ✓ Orderbook fetched (combined_ask: 1.001)

============================================================
Smoke Test Summary
============================================================
Markets Fetched:        100
Markets Usable:         5
Orderbooks Fetched:     3
Signals Generated:      1
Risk Decisions:         1
Paper Trades Simulated: 1
Fallback Count:         0
============================================================

SAFETY CHECK: Live Trading Status
============================================================
live_trading_enabled: False
allow_auto_execution: False
paper_trading_enabled: True

✅ Safe: live_trading is DISABLED
============================================================
```

### 限制

| 限制 | 说明 |
|------|------|
| 不下单 | 仅使用 GET endpoints |
| 不需要私钥 | 公开数据无需认证 |
| 不调用 live_trader | 仅 paper trading |
| 不影响 pytest | 独立脚本，非测试依赖 |
| 失败时优雅退出 | 退出码 0，打印错误 |

### 错误处理

如果真实 API 失败：
- 打印错误信息
- 优雅退出（退出码 0）
- 不影响项目测试

常见错误：
- 网络超时：检查网络连接
- Rate limit：等待后重试
- 无可用市场：可能 API 返回格式变化

---

## Phase 4B — CLOB WebSocket Read-only

Phase 4B 实现了 Polymarket CLOB WebSocket 实时 orderbook 订阅。

**重要**: Phase 4B 是只读阶段，不涉及：
- 真实下单
- 私钥处理
- 认证操作
- User channel

---

### WebSocket 架构

```
Polymarket CLOB WebSocket
└── Market Channel (wss://ws-subscriptions-clob.polymarket.com/ws/market)
    ├── 订阅: assets_ids (token IDs) - 注意是 assets_ids 不是 asset_ids
    ├── 消息: 返回数组，每个元素直接包含 orderbook 数据
    └── 无需认证
```

---

### 真实协议发现（Smoke Test 验证）

**WebSocket URL:**
```
wss://ws-subscriptions-clob.polymarket.com/ws/market
```

**订阅消息格式（已验证）:**
```json
{
    "type": "subscribe",
    "channel": "market",
    "assets_ids": ["token_id_1", "token_id_2"]
}
```

**重要**: 字段名是 `assets_ids`（复数），不是 `asset_ids`。

**返回消息格式（已验证）:**

Polymarket 返回消息是**数组**，每个元素直接包含 orderbook 数据，**没有 `type` 字段**：

```json
[
    {
        "market": "0x9c1a953fe92c8357f1b646ba25d983aa83e90c525992db14fb726fa895cb5763",
        "asset_id": "8501497159083948713316135768103773293754490207922884688769443031624417212426",
        "timestamp": "1778161557552",
        "hash": "558f5bf3469fdf02dac71a43cd50d3b3dcd6885d",
        "bids": [
            {"price": "0.01", "size": "2054325.28"},
            {"price": "0.02", "size": "122.65"},
            ...
        ],
        "asks": [
            {"price": "0.99", "size": "100"},
            ...
        ]
    }
]
```

**字段说明:**
- `market`: condition_id（市场标识）
- `asset_id`: token_id（YES 或 NO token）
- `timestamp`: Unix 时间戳（毫秒）
- `bids`: 买单列表，价格降序
- `asks`: 卖单列表，价格升序
- 价格和大小都是字符串格式

---

### 模块结构

```
polysignal/ingestion/
├── websocket_client.py        # WebSocket 客户端
├── websocket_message_handler.py  # 消息解析器
├── orderbook_cache.py         # OrderBook 缓存管理
├── subscription_manager.py    # 订阅管理
└── reconnection_strategy.py   # 重连策略

config/
└── websocket.yaml             # WebSocket 配置
```

---

### 配置

**config/websocket.yaml:**

```yaml
websocket:
  enabled: true
  url: "wss://ws-subscriptions-clob.polymarket.com/ws/market"

  # 心跳 (官方推荐 10 秒)
  ping_interval_seconds: 10
  pong_timeout_seconds: 10

  # 重连
  max_reconnect_attempts: 5
  reconnect_delay_seconds: 1
  reconnect_backoff_multiplier: 2.0

  # 订阅限制
  max_subscriptions: 20  # token 数，不是 market 数
  subscribe_batch_size: 5
  subscribe_delay_ms: 100

  # Stale 检测
  stale_threshold_seconds: 60
```

---

### 订阅格式

Market channel 使用 assets_ids (token IDs) 订阅：

```python
# 订阅消息格式（已验证）
{
    "type": "subscribe",
    "channel": "market",
    "assets_ids": ["yes_token_id", "no_token_id"]
}
```

**重要**:
- 字段名是 `assets_ids`（复数），不是 `asset_ids`
- 必须包含 `channel: "market"`
- 每个市场有 2 个 token: YES 和 NO
- `max_subscriptions` 是 token 数，不是 market 数

---

### OrderBook Cache

Cache 按 token_id 维护，完整 market orderbook 由 YES + NO cache 合成：

```python
from polysignal.ingestion.websocket_client import CLOBWebSocketClient

client = CLOBWebSocketClient()

# 连接
await client.connect()

# 订阅
await client.subscribe(["yes_token_id", "no_token_id"])

# 获取 orderbook (自动合并 YES + NO)
snapshot = await client.get_orderbook(
    market_id="market_1",
    yes_token_id="yes_token_id",
    no_token_id="no_token_id",
)
```

---

### Stale Data 检测

如果超过 `stale_threshold_seconds` 未收到更新，`OrderBookSnapshot.is_stale` 会被设置为 `True`。

Risk Governor 会自动 hard reject stale 数据：

```python
if orderbook.is_stale:
    decision.add_hard_reject("price_stale")
```

---

### REST Fallback

WebSocket 失败时自动 fallback 到 REST：

1. WebSocket 未启用 → REST
2. WebSocket 连接失败 → REST
3. Cache miss → REST
4. Stale data → REST

---

### 测试

所有测试使用 mock WebSocket：

```bash
pytest tests/test_websocket_client.py -v
pytest tests/test_websocket_message_handler.py -v
pytest tests/test_orderbook_cache.py -v
pytest tests/test_subscription_manager.py -v
pytest tests/test_reconnection_strategy.py -v
```

测试不依赖真实 WebSocket 连接。

---

### 可选 Smoke Test

手动运行真实 WebSocket smoke test：

```bash
python scripts/smoke_ws_readonly.py
```

**注意**: 这是可选的，不纳入 pytest 必须项。

---

### 安全保证

| 功能 | 原因 |
|------|------|
| 真实下单 | 只读阶段 |
| 私钥处理 | 只读不需要 |
| 认证 WebSocket | 只读不需要 |
| User channel | 只读不需要 |
| POST /order | 只读阶段 |

### 保持不变

```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
```

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `polysignal/ingestion/api_types.py` | API 响应类型 |
| `polysignal/ingestion/api_errors.py` | API 错误类型 |
| `polysignal/ingestion/gamma_client.py` | Gamma API 客户端 |
| `polysignal/ingestion/clob_client.py` | CLOB REST 客户端 |
| `polysignal/ingestion/data_converter.py` | 数据转换器 |
| `polysignal/ingestion/data_provider_manager.py` | 数据管理器 |
| `polysignal/ingestion/websocket_client.py` | WebSocket 客户端 |
| `polysignal/ingestion/websocket_message_handler.py` | 消息解析器 |
| `polysignal/ingestion/orderbook_cache.py` | OrderBook 缓存 |
| `polysignal/ingestion/subscription_manager.py` | 订阅管理 |
| `polysignal/ingestion/reconnection_strategy.py` | 重连策略 |
| `config/websocket.yaml` | WebSocket 配置 |
| `tests/fixtures/api_responses.py` | 测试 fixtures |
| `tests/test_gamma_client.py` | Gamma 客户端测试 |
| `tests/test_clob_client.py` | CLOB 客户端测试 |
| `tests/test_data_converter.py` | 转换器测试 |
| `tests/test_data_provider_manager.py` | 管理器测试 |
| `tests/test_websocket_client.py` | WebSocket 客户端测试 |
| `tests/test_websocket_message_handler.py` | 消息解析测试 |
| `tests/test_orderbook_cache.py` | 缓存测试 |
| `tests/test_subscription_manager.py` | 订阅管理测试 |
| `tests/test_reconnection_strategy.py` | 重连策略测试 |
