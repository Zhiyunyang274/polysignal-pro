"""

Database Module - SQLite storage for PolySignal Pro

Tables:
- markets: Market information
- orderbook_snapshots: Orderbook snapshots
- signals: Trading signals
- paper_orders: Paper trading orders
- paper_positions: Paper trading positions
- risk_decisions: Risk Governor decisions
- system_health: System health records
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from polysignal.logging_config import get_logger
from polysignal.models.market import Market
from polysignal.models.paper_trade import PaperOrder, PaperPosition
from polysignal.models.risk import RiskDecision
from polysignal.models.signal import Signal

logger = get_logger("polysignal.storage.database")


class Database:
    """
    SQLite Database for PolySignal Pro.

    Uses aiosqlite for async operations.
    """

    def __init__(self, db_path: str = "data/polysignal.db"):
        """
        Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    def require_connection(self) -> aiosqlite.Connection:
        """Return the live connection or raise; callers inside an open run
        use this instead of touching the private _db attribute."""
        if self._db is None:
            raise RuntimeError("Database not connected")
        return self._db

    async def connect(self) -> None:
        """Connect to database and create tables"""
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        await self._create_tables()

    async def close(self) -> None:
        """Close database connection"""
        if self._db:
            await self._db.close()
            self._db = None

    async def _migrate_paper_runs_columns(self) -> None:
        """Add new columns to paper_runs table if they don't exist"""
        if not self._db:
            return

        # Get existing columns
        cursor = await self._db.execute("PRAGMA table_info(paper_runs)")
        rows = await cursor.fetchall()
        existing_columns = {row[1] for row in rows}

        # Add missing columns
        new_columns = [
            ("real_markets_fetched", "INTEGER DEFAULT 0"),
            ("orderbooks_fetched", "INTEGER DEFAULT 0"),
        ]

        for column_name, column_type in new_columns:
            if column_name not in existing_columns:
                try:
                    await self._db.execute(f"ALTER TABLE paper_runs ADD COLUMN {column_name} {column_type}")
                except Exception as e:
                    # Migration is best-effort (column may already exist from a
                    # concurrent start), but failures must be visible.
                    logger.warning(
                        "Column migration skipped",
                        column=column_name,
                        error=str(e),
                    )

        await self._db.commit()

    async def _create_tables(self) -> None:
        """Create database tables"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.executescript("""
            -- Markets table
            CREATE TABLE IF NOT EXISTS markets (
                market_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                total_volume_usd REAL DEFAULT 0,
                volume_24h_usd REAL DEFAULT 0,
                is_ambiguous INTEGER DEFAULT 0,
                is_forbidden_auto INTEGER DEFAULT 0,
                fetched_at TEXT NOT NULL,
                created_at TEXT
            );

            -- Orderbook snapshots table
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                yes_best_bid REAL,
                yes_best_ask REAL,
                no_best_bid REAL,
                no_best_ask REAL,
                combined_ask REAL,
                spread_pct_yes REAL,
                total_depth_usd REAL,
                is_stale INTEGER DEFAULT 0,
                source TEXT DEFAULT 'mock',
                FOREIGN KEY (market_id) REFERENCES markets(market_id)
            );

            -- Signals table
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_title TEXT,
                market_category TEXT,
                strategy_name TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                raw_score REAL DEFAULT 0,
                risk_flags TEXT,
                reason TEXT,
                path_type TEXT DEFAULT 'ultra_fast',
                data_source TEXT DEFAULT 'mock',
                FOREIGN KEY (market_id) REFERENCES markets(market_id)
            );

            -- Risk decisions table
            CREATE TABLE IF NOT EXISTS risk_decisions (
                decision_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                trade_score REAL DEFAULT 0,
                hard_reject_reasons TEXT,
                explanation TEXT,
                risk_flags TEXT,
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
            );

            -- Paper orders table
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                risk_decision_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_title TEXT,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                filled_size REAL DEFAULT 0,
                filled_price REAL,
                status TEXT NOT NULL,
                strategy_name TEXT,
                realized_pnl_usd REAL,
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id),
                FOREIGN KEY (risk_decision_id) REFERENCES risk_decisions(decision_id),
                FOREIGN KEY (market_id) REFERENCES markets(market_id)
            );

            -- Paper positions table
            CREATE TABLE IF NOT EXISTS paper_positions (
                position_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                market_title TEXT,
                side TEXT NOT NULL,
                size REAL DEFAULT 0,
                avg_entry_price REAL DEFAULT 0,
                current_price REAL DEFAULT 0,
                unrealized_pnl_usd REAL DEFAULT 0,
                realized_pnl_usd REAL DEFAULT 0,
                opened_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (market_id) REFERENCES markets(market_id)
            );

            -- System health table
            CREATE TABLE IF NOT EXISTS system_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                component TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                metadata TEXT
            );

            -- Telegram actions audit log
            CREATE TABLE IF NOT EXISTS telegram_actions (
                action_id TEXT PRIMARY KEY,
                signal_id TEXT,
                action TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                market_id TEXT,
                strategy_name TEXT,
                wallet_address TEXT,
                result TEXT NOT NULL,
                result_message TEXT,
                timestamp TEXT NOT NULL
            );

            -- Ignore rules (runtime)
            CREATE TABLE IF NOT EXISTS ignore_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT,
                strategy_name TEXT,
                added_by TEXT NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(market_id, strategy_name)
            );

            -- Blacklist (runtime)
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT,
                added_by TEXT NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(target_type, target_id)
            );

            -- Wallet watchlist runtime (not in YAML)
            CREATE TABLE IF NOT EXISTS wallet_watchlist_runtime (
                wallet_address TEXT PRIMARY KEY,
                added_by TEXT NOT NULL,
                added_at TEXT NOT NULL,
                notes TEXT
            );

            -- System state (pause states, etc.)
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL
            );

            -- Signal reviews
            CREATE TABLE IF NOT EXISTS signal_reviews (
                signal_id TEXT PRIMARY KEY,
                reviewed_by TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
            );

            -- Paper runs (Phase 5A)
            CREATE TABLE IF NOT EXISTS paper_runs (
                run_id TEXT PRIMARY KEY,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_minutes INTEGER,
                duration_hours REAL,
                status TEXT NOT NULL DEFAULT 'running',

                -- Configuration
                data_mode TEXT NOT NULL,
                llm_provider TEXT NOT NULL,
                websocket_enabled INTEGER NOT NULL,
                telegram_enabled INTEGER NOT NULL,
                max_markets INTEGER,
                scan_interval_seconds INTEGER,
                max_llm_calls_per_hour INTEGER,
                max_signals_per_hour INTEGER,
                max_telegram_messages_per_hour INTEGER,

                -- Statistics
                markets_checked INTEGER DEFAULT 0,
                real_markets_fetched INTEGER DEFAULT 0,
                orderbooks_fetched INTEGER DEFAULT 0,
                signals_generated INTEGER DEFAULT 0,
                signals_ignored INTEGER DEFAULT 0,
                signals_log_only INTEGER DEFAULT 0,
                signals_alert INTEGER DEFAULT 0,
                signals_paper_trade INTEGER DEFAULT 0,
                signals_hard_reject INTEGER DEFAULT 0,
                paper_trades_created INTEGER DEFAULT 0,
                paper_trades_filled INTEGER DEFAULT 0,

                -- LLM statistics
                llm_calls INTEGER DEFAULT 0,
                llm_successes INTEGER DEFAULT 0,
                llm_failures INTEGER DEFAULT 0,
                llm_avg_latency_seconds REAL,

                -- API/WebSocket statistics
                api_errors INTEGER DEFAULT 0,
                api_fallbacks INTEGER DEFAULT 0,
                websocket_messages INTEGER DEFAULT 0,
                websocket_reconnects INTEGER DEFAULT 0,
                websocket_errors INTEGER DEFAULT 0,

                -- Telegram statistics
                telegram_messages_sent INTEGER DEFAULT 0,
                telegram_errors INTEGER DEFAULT 0,

                -- Rate limit tracking
                llm_calls_this_hour INTEGER DEFAULT 0,
                signals_this_hour INTEGER DEFAULT 0,
                telegram_messages_this_hour INTEGER DEFAULT 0,

                -- Summary
                hard_reject_reasons TEXT,
                error_summary TEXT,
                simulated_pnl_usd REAL
            );

            -- Paper run scans (Phase 5A)
            CREATE TABLE IF NOT EXISTS paper_run_scans (
                scan_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                scan_time TEXT NOT NULL,
                markets_scanned INTEGER DEFAULT 0,
                signals_generated INTEGER DEFAULT 0,
                signals_by_action TEXT,
                errors INTEGER DEFAULT 0,
                latency_seconds REAL,
                data_source TEXT,
                FOREIGN KEY (run_id) REFERENCES paper_runs(run_id)
            );

            -- Paper run events (Phase 5A)
            CREATE TABLE IF NOT EXISTS paper_run_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_category TEXT NOT NULL,
                description TEXT,
                details TEXT,
                signal_id TEXT,
                market_id TEXT,
                FOREIGN KEY (run_id) REFERENCES paper_runs(run_id)
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
            CREATE INDEX IF NOT EXISTS idx_signals_market_id ON signals(market_id);
            CREATE INDEX IF NOT EXISTS idx_paper_orders_timestamp ON paper_orders(timestamp);
            CREATE INDEX IF NOT EXISTS idx_paper_positions_market_id ON paper_positions(market_id);
            CREATE INDEX IF NOT EXISTS idx_telegram_actions_timestamp ON telegram_actions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_blacklist_target ON blacklist(target_type, target_id);
            CREATE INDEX IF NOT EXISTS idx_paper_runs_start_time ON paper_runs(start_time);
            CREATE INDEX IF NOT EXISTS idx_paper_run_scans_run_id ON paper_run_scans(run_id);
            CREATE INDEX IF NOT EXISTS idx_paper_run_events_run_id ON paper_run_events(run_id);
        """)

        await self._db.commit()

        # Migration: Add new columns if they don't exist (for existing databases)
        await self._migrate_paper_runs_columns()

    # =========================================================================
    # Market operations
    # =========================================================================

    async def save_market(self, market: Market) -> None:
        """Save a market"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO markets (
                market_id, title, description, category, status,
                total_volume_usd, volume_24h_usd, is_ambiguous, is_forbidden_auto,
                fetched_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market.market_id,
                market.title,
                market.description,
                market.category.value,
                market.status.value,
                market.total_volume_usd,
                market.volume_24h_usd,
                1 if market.is_ambiguous else 0,
                1 if market.is_forbidden_auto else 0,
                market.fetched_at.isoformat(),
                market.created_at.isoformat() if market.created_at else None,
            ),
        )
        await self._db.commit()

    async def get_market(self, market_id: str) -> Market | None:
        """Get a market by ID"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            "SELECT * FROM markets WHERE market_id = ?", (market_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_market(row)
        return None

    def _row_to_market(self, row: aiosqlite.Row) -> Market:
        """Convert row to Market"""
        from polysignal.models.market import MarketCategory, MarketStatus

        return Market(
            market_id=row["market_id"],
            title=row["title"],
            description=row["description"],
            category=MarketCategory(row["category"]),
            status=MarketStatus(row["status"]),
            total_volume_usd=row["total_volume_usd"],
            volume_24h_usd=row["volume_24h_usd"],
            is_ambiguous=bool(row["is_ambiguous"]),
            is_forbidden_auto=bool(row["is_forbidden_auto"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )

    # =========================================================================
    # Signal operations
    # =========================================================================

    async def save_signal(self, signal: Signal) -> None:
        """Save a signal"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO signals (
                signal_id, timestamp, market_id, market_title, market_category,
                strategy_name, side, price, raw_score, risk_flags, reason,
                path_type, data_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.signal_id,
                signal.timestamp.isoformat(),
                signal.market_id,
                signal.market_title,
                signal.market_category,
                signal.strategy_name,
                signal.side.value,
                signal.price,
                signal.raw_score,
                json.dumps(signal.risk_flags),
                signal.reason,
                signal.path_type,
                signal.data_source,
            ),
        )
        await self._db.commit()

    async def get_recent_signals(self, limit: int = 100) -> list[Signal]:
        """Get recent signals"""
        if not self._db:
            raise RuntimeError("Database not connected")

        signals = []
        async with self._db.execute(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            async for row in cursor:
                signals.append(self._row_to_signal(row))
        return signals

    def _row_to_signal(self, row: aiosqlite.Row) -> Signal:
        """Convert row to Signal"""
        from polysignal.models.signal import SignalSide

        return Signal(
            signal_id=row["signal_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            market_id=row["market_id"],
            market_title=row["market_title"] or "",
            market_category=row["market_category"] or "other",
            strategy_name=row["strategy_name"],
            side=SignalSide(row["side"]),
            price=row["price"],
            raw_score=row["raw_score"],
            risk_flags=json.loads(row["risk_flags"]) if row["risk_flags"] else [],
            reason=row["reason"] or "",
            path_type=row["path_type"],
            data_source=row["data_source"],
        )

    # =========================================================================
    # Risk decision operations
    # =========================================================================

    async def save_risk_decision(self, decision: RiskDecision) -> None:
        """Save a risk decision"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO risk_decisions (
                decision_id, signal_id, timestamp, action, trade_score,
                hard_reject_reasons, explanation, risk_flags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                decision.signal_id,
                decision.timestamp.isoformat(),
                decision.action.value,
                decision.trade_score,
                json.dumps(decision.hard_reject_reasons),
                decision.explanation,
                json.dumps(decision.risk_flags),
            ),
        )
        await self._db.commit()

    # =========================================================================
    # Paper order operations
    # =========================================================================

    async def save_paper_order(self, order: PaperOrder) -> None:
        """Save a paper order"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO paper_orders (
                order_id, signal_id, risk_decision_id, timestamp, market_id,
                market_title, side, price, size, filled_size, filled_price,
                status, strategy_name, realized_pnl_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.signal_id,
                order.risk_decision_id,
                order.timestamp.isoformat(),
                order.market_id,
                order.market_title,
                order.side.value,
                order.price,
                order.size,
                order.filled_size,
                order.filled_price,
                order.status.value,
                order.strategy_name,
                order.realized_pnl_usd,
            ),
        )
        await self._db.commit()

    async def get_recent_orders(self, limit: int = 100) -> list[PaperOrder]:
        """Get recent paper orders"""
        if not self._db:
            raise RuntimeError("Database not connected")

        orders = []
        async with self._db.execute(
            "SELECT * FROM paper_orders ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            async for row in cursor:
                orders.append(self._row_to_paper_order(row))
        return orders

    def _row_to_paper_order(self, row: aiosqlite.Row) -> PaperOrder:
        """Convert row to PaperOrder"""
        from polysignal.models.paper_trade import OrderSide, OrderStatus

        return PaperOrder(
            order_id=row["order_id"],
            signal_id=row["signal_id"],
            risk_decision_id=row["risk_decision_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            market_id=row["market_id"],
            market_title=row["market_title"] or "",
            side=OrderSide(row["side"]),
            price=row["price"],
            size=row["size"],
            filled_size=row["filled_size"],
            filled_price=row["filled_price"],
            status=OrderStatus(row["status"]),
            strategy_name=row["strategy_name"] or "",
            realized_pnl_usd=row["realized_pnl_usd"],
        )

    # =========================================================================
    # Paper position operations
    # =========================================================================

    async def save_paper_position(self, position: PaperPosition) -> None:
        """Save a paper position"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO paper_positions (
                position_id, market_id, market_title, side, size,
                avg_entry_price, current_price, unrealized_pnl_usd,
                realized_pnl_usd, opened_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.position_id,
                position.market_id,
                position.market_title,
                position.side.value,
                position.size,
                position.avg_entry_price,
                position.current_price,
                position.unrealized_pnl_usd,
                position.realized_pnl_usd,
                position.opened_at.isoformat(),
                position.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_all_positions(self) -> list[PaperPosition]:
        """Get all paper positions"""
        if not self._db:
            raise RuntimeError("Database not connected")

        positions = []
        async with self._db.execute(
            "SELECT * FROM paper_positions WHERE size > 0"
        ) as cursor:
            async for row in cursor:
                positions.append(self._row_to_paper_position(row))
        return positions

    def _row_to_paper_position(self, row: aiosqlite.Row) -> PaperPosition:
        """Convert row to PaperPosition"""
        from polysignal.models.paper_trade import OrderSide

        return PaperPosition(
            position_id=row["position_id"],
            market_id=row["market_id"],
            market_title=row["market_title"] or "",
            side=OrderSide(row["side"]),
            size=row["size"],
            avg_entry_price=row["avg_entry_price"],
            current_price=row["current_price"],
            unrealized_pnl_usd=row["unrealized_pnl_usd"],
            realized_pnl_usd=row["realized_pnl_usd"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # =========================================================================
    # System health operations
    # =========================================================================

    async def log_health(
        self,
        component: str,
        status: str,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log system health"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT INTO system_health (timestamp, component, status, message, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                component,
                status,
                message,
                json.dumps(metadata) if metadata else None,
            ),
        )
        await self._db.commit()

    async def get_health_status(self) -> dict[str, Any]:
        """Get system health status"""
        if not self._db:
            raise RuntimeError("Database not connected")

        # Get recent health records
        health_records = []
        async with self._db.execute(
            """
            SELECT * FROM system_health
            ORDER BY timestamp DESC
            LIMIT 10
            """
        ) as cursor:
            async for row in cursor:
                health_records.append({
                    "timestamp": row["timestamp"],
                    "component": row["component"],
                    "status": row["status"],
                    "message": row["message"],
                })

        # Get counts
        signal_count = 0
        order_count = 0
        position_count = 0

        row_signal: aiosqlite.Row | None
        async with self._db.execute("SELECT COUNT(*) FROM signals") as cursor:
            row_signal = await cursor.fetchone()
            signal_count = row_signal[0] if row_signal else 0

        row_order: aiosqlite.Row | None
        async with self._db.execute("SELECT COUNT(*) FROM paper_orders") as cursor:
            row_order = await cursor.fetchone()
            order_count = row_order[0] if row_order else 0

        row_position: aiosqlite.Row | None
        async with self._db.execute("SELECT COUNT(*) FROM paper_positions WHERE size > 0") as cursor:
            row_position = await cursor.fetchone()
            position_count = row_position[0] if row_position else 0

        return {
            "signal_count": signal_count,
            "order_count": order_count,
            "position_count": position_count,
            "recent_health": health_records,
        }

    # =========================================================================
    # Telegram action operations
    # =========================================================================

    async def log_telegram_action(
        self,
        action_id: str,
        action: str,
        user_id: int,
        result: str,
        result_message: str,
        signal_id: str | None = None,
        username: str | None = None,
        market_id: str | None = None,
        strategy_name: str | None = None,
        wallet_address: str | None = None,
    ) -> None:
        """Log a Telegram action"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT INTO telegram_actions (
                action_id, signal_id, action, user_id, username, market_id,
                strategy_name, wallet_address, result, result_message, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                signal_id,
                action,
                user_id,
                username,
                market_id,
                strategy_name,
                wallet_address,
                result,
                result_message,
                datetime.utcnow().isoformat(),
            ),
        )
        await self._db.commit()

    async def get_telegram_action(
        self,
        signal_id: str,
        action: str,
    ) -> dict[str, Any] | None:
        """Check if a Telegram action already exists for a signal"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            """
            SELECT * FROM telegram_actions
            WHERE signal_id = ? AND action = ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (signal_id, action),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    # =========================================================================
    # Ignore rules operations
    # =========================================================================

    async def add_ignore_rule(
        self,
        market_id: str | None,
        strategy_name: str | None,
        added_by: str,
    ) -> bool:
        """Add an ignore rule. Returns True if added, False if already exists."""
        if not self._db:
            raise RuntimeError("Database not connected")

        try:
            await self._db.execute(
                """
                INSERT INTO ignore_rules (market_id, strategy_name, added_by, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (market_id, strategy_name, added_by, datetime.utcnow().isoformat()),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def is_signal_ignored(
        self,
        market_id: str,
        strategy_name: str,
    ) -> bool:
        """Check if a signal should be ignored based on rules"""
        if not self._db:
            raise RuntimeError("Database not connected")

        # Check exact match
        async with self._db.execute(
            """
            SELECT 1 FROM ignore_rules
            WHERE (market_id = ? OR market_id IS NULL)
            AND (strategy_name = ? OR strategy_name IS NULL)
            """,
            (market_id, strategy_name),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def get_ignore_rules(self) -> list[dict[str, Any]]:
        """Get all ignore rules"""
        if not self._db:
            raise RuntimeError("Database not connected")

        rules = []
        async with self._db.execute("SELECT * FROM ignore_rules") as cursor:
            async for row in cursor:
                rules.append(dict(row))
        return rules

    # =========================================================================
    # Blacklist operations
    # =========================================================================

    async def add_blacklist(
        self,
        target_type: str,
        target_id: str,
        added_by: str,
        reason: str | None = None,
    ) -> bool:
        """Add to blacklist. Returns True if added, False if already exists."""
        if not self._db:
            raise RuntimeError("Database not connected")

        try:
            await self._db.execute(
                """
                INSERT INTO blacklist (target_type, target_id, reason, added_by, added_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (target_type, target_id, reason, added_by, datetime.utcnow().isoformat()),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def is_blacklisted(
        self,
        target_type: str,
        target_id: str,
    ) -> bool:
        """Check if target is blacklisted"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            """
            SELECT 1 FROM blacklist
            WHERE target_type = ? AND target_id = ?
            """,
            (target_type, target_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def get_blacklist(self) -> list[dict[str, Any]]:
        """Get all blacklist entries"""
        if not self._db:
            raise RuntimeError("Database not connected")

        entries = []
        async with self._db.execute("SELECT * FROM blacklist ORDER BY added_at DESC") as cursor:
            async for row in cursor:
                entries.append(dict(row))
        return entries

    # =========================================================================
    # Wallet watchlist runtime operations
    # =========================================================================

    async def add_wallet_to_watchlist(
        self,
        wallet_address: str,
        added_by: str,
        notes: str | None = None,
    ) -> bool:
        """Add wallet to runtime watchlist. Returns True if added, False if exists."""
        if not self._db:
            raise RuntimeError("Database not connected")

        try:
            await self._db.execute(
                """
                INSERT INTO wallet_watchlist_runtime (wallet_address, added_by, added_at, notes)
                VALUES (?, ?, ?, ?)
                """,
                (wallet_address, added_by, datetime.utcnow().isoformat(), notes),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def is_wallet_watched(self, wallet_address: str) -> bool:
        """Check if wallet is in runtime watchlist"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            "SELECT 1 FROM wallet_watchlist_runtime WHERE wallet_address = ?",
            (wallet_address,),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def get_wallet_watchlist(self) -> list[dict[str, Any]]:
        """Get all wallets in runtime watchlist"""
        if not self._db:
            raise RuntimeError("Database not connected")

        wallets = []
        async with self._db.execute(
            "SELECT * FROM wallet_watchlist_runtime ORDER BY added_at DESC"
        ) as cursor:
            async for row in cursor:
                wallets.append(dict(row))
        return wallets

    # =========================================================================
    # System state operations
    # =========================================================================

    async def get_system_state(self, key: str) -> str | None:
        """Get system state value"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            "SELECT value FROM system_state WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def set_system_state(
        self,
        key: str,
        value: str,
        updated_by: str | None = None,
    ) -> None:
        """Set system state value"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO system_state (key, value, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, value, updated_by, datetime.utcnow().isoformat()),
        )
        await self._db.commit()

    # =========================================================================
    # Signal review operations
    # =========================================================================

    async def mark_signal_reviewed(
        self,
        signal_id: str,
        reviewed_by: str,
        notes: str | None = None,
    ) -> None:
        """Mark a signal as reviewed"""
        if not self._db:
            raise RuntimeError("Database not connected")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO signal_reviews (signal_id, reviewed_by, reviewed_at, notes)
            VALUES (?, ?, ?, ?)
            """,
            (signal_id, reviewed_by, datetime.utcnow().isoformat(), notes),
        )
        await self._db.commit()

    async def is_signal_reviewed(self, signal_id: str) -> bool:
        """Check if signal has been reviewed"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            "SELECT 1 FROM signal_reviews WHERE signal_id = ?",
            (signal_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    # =========================================================================
    # Signal lookup operations
    # =========================================================================

    async def get_signal(self, signal_id: str) -> Signal | None:
        """Get a signal by ID"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            "SELECT * FROM signals WHERE signal_id = ?",
            (signal_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_signal(row)
        return None

    async def get_risk_decision(self, signal_id: str) -> RiskDecision | None:
        """Get a risk decision by signal ID"""
        if not self._db:
            raise RuntimeError("Database not connected")

        async with self._db.execute(
            "SELECT * FROM risk_decisions WHERE signal_id = ?",
            (signal_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_risk_decision(row)
        return None

    def _row_to_risk_decision(self, row: aiosqlite.Row) -> RiskDecision:
        """Convert row to RiskDecision"""
        from polysignal.models.risk import RiskAction

        return RiskDecision(
            decision_id=row["decision_id"],
            signal_id=row["signal_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            action=RiskAction(row["action"]),
            trade_score=row["trade_score"],
            hard_reject_reasons=json.loads(row["hard_reject_reasons"]) if row["hard_reject_reasons"] else [],
            explanation=row["explanation"] or "",
            risk_flags=json.loads(row["risk_flags"]) if row["risk_flags"] else [],
        )
