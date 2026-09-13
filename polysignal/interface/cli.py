"""
CLI Module - Command line interface for PolySignal Pro

Provides summary output and basic commands.
"""

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polysignal.models.paper_trade import PaperOrder, PaperPosition, PaperTradeStats
from polysignal.models.risk import RiskDecision
from polysignal.models.signal import Signal

console = Console()


def print_header(title: str = "PolySignal Pro") -> None:
    """Print header"""
    console.print(Panel(title, style="bold blue"))


def print_config_summary(config_data: dict[str, Any]) -> None:
    """Print configuration summary"""
    console.print("\n[bold]Configuration Summary[/bold]")

    table = Table(show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    for key, value in config_data.items():
        if isinstance(value, dict):
            for k, v in value.items():
                table.add_row(f"{key}.{k}", str(v))
        else:
            table.add_row(key, str(value))

    console.print(table)


def print_system_health(health: dict[str, Any]) -> None:
    """Print system health"""
    console.print("\n[bold]System Health[/bold]")

    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Signal Count", str(health.get("signal_count", 0)))
    table.add_row("Order Count", str(health.get("order_count", 0)))
    table.add_row("Position Count", str(health.get("position_count", 0)))

    console.print(table)


def print_signals(signals: list[Signal], limit: int = 10) -> None:
    """Print recent signals"""
    console.print("\n[bold]Recent Signals[/bold]")

    if not signals:
        console.print("[yellow]No signals[/yellow]")
        return

    table = Table()
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Time", style="dim", width=20)
    table.add_column("Market", style="white", width=30)
    table.add_column("Strategy", style="blue", width=15)
    table.add_column("Side", style="magenta", width=6)
    table.add_column("Price", style="green", width=8)
    table.add_column("Score", style="yellow", width=6)

    for signal in signals[:limit]:
        table.add_row(
            signal.signal_id[:8],
            signal.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            signal.market_title[:30],
            signal.strategy_name,
            signal.side.value,
            f"{signal.price:.4f}",
            f"{signal.raw_score:.1f}",
        )

    console.print(table)


def print_orders(orders: list[PaperOrder], limit: int = 10) -> None:
    """Print recent paper orders"""
    console.print("\n[bold]Recent Paper Orders[/bold]")

    if not orders:
        console.print("[yellow]No orders[/yellow]")
        return

    table = Table()
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Time", style="dim", width=20)
    table.add_column("Market", style="white", width=30)
    table.add_column("Side", style="magenta", width=10)
    table.add_column("Price", style="green", width=8)
    table.add_column("Size", style="blue", width=8)
    table.add_column("Status", style="yellow", width=12)
    table.add_column("PnL", style="red", width=8)

    for order in orders[:limit]:
        pnl_str = f"${order.realized_pnl_usd:.2f}" if order.realized_pnl_usd else "-"
        table.add_row(
            order.order_id[:8],
            order.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            order.market_title[:30],
            order.side.value,
            f"{order.price:.4f}",
            f"{order.size:.2f}",
            order.status.value,
            pnl_str,
        )

    console.print(table)


def print_positions(positions: list[PaperPosition]) -> None:
    """Print current positions"""
    console.print("\n[bold]Current Positions[/bold]")

    if not positions:
        console.print("[yellow]No open positions[/yellow]")
        return

    table = Table()
    table.add_column("Market", style="white", width=30)
    table.add_column("Side", style="magenta", width=10)
    table.add_column("Size", style="blue", width=8)
    table.add_column("Entry", style="green", width=8)
    table.add_column("Current", style="cyan", width=8)
    table.add_column("Unrealized", style="yellow", width=10)
    table.add_column("Realized", style="red", width=10)

    for pos in positions:
        table.add_row(
            pos.market_title[:30],
            pos.side.value,
            f"{pos.size:.2f}",
            f"{pos.avg_entry_price:.4f}",
            f"{pos.current_price:.4f}",
            f"${pos.unrealized_pnl_usd:.2f}",
            f"${pos.realized_pnl_usd:.2f}",
        )

    console.print(table)


def print_stats(stats: PaperTradeStats) -> None:
    """Print trading statistics"""
    console.print("\n[bold]Paper Trading Statistics[/bold]")

    table = Table()
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Trades", str(stats.total_trades))
    table.add_row("Winning Trades", str(stats.winning_trades))
    table.add_row("Losing Trades", str(stats.losing_trades))
    table.add_row("Win Rate", f"{stats.win_rate:.1%}")
    table.add_row("Total PnL", f"${stats.total_pnl_usd:.2f}")
    table.add_row("Avg Win", f"${stats.avg_win_usd:.2f}")
    table.add_row("Avg Loss", f"${stats.avg_loss_usd:.2f}")
    table.add_row("Max Drawdown", f"${stats.max_drawdown_usd:.2f}")

    console.print(table)


def print_risk_decision(decision: RiskDecision) -> None:
    """Print a risk decision"""
    console.print("\n[bold]Risk Decision[/bold]")

    # Action with color
    action_color = {
        "ignore": "dim",
        "log_only": "dim",
        "alert": "yellow",
        "paper_trade": "green",
        "manual_review": "orange",
        "live_execute": "red",
        "hard_reject": "red bold",
    }

    action_text = Text(decision.action.value, style=action_color.get(decision.action.value, "white"))

    table = Table()
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Decision ID", decision.decision_id[:8])
    table.add_row("Signal ID", decision.signal_id[:8])
    table.add_row("Action", action_text)
    table.add_row("Trade Score", f"{decision.trade_score:.1f}")
    table.add_row("Hard Rejects", str(len(decision.hard_reject_reasons)))
    table.add_row("Explanation", decision.explanation[:50] if decision.explanation else "-")

    console.print(table)


def print_summary(
    health: dict[str, Any],
    signals: list[Signal],
    orders: list[PaperOrder],
    positions: list[PaperPosition],
    stats: PaperTradeStats | None = None,
) -> None:
    """Print full summary"""
    console.clear()
    print_header()

    console.print(f"\n[dim]Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

    print_system_health(health)
    print_signals(signals)
    print_orders(orders)
    print_positions(positions)

    if stats:
        print_stats(stats)

    console.print("\n[bold green]✓ PolySignal Pro Running[/bold green]")
    console.print("[dim]Mode: READ-ONLY + PAPER TRADING[/dim]")
    console.print("[dim]Live Trading: DISABLED[/dim]")


def print_error(message: str) -> None:
    """Print error message"""
    console.print(f"[bold red]Error: {message}[/bold red]")


def print_warning(message: str) -> None:
    """Print warning message"""
    console.print(f"[bold yellow]Warning: {message}[/bold yellow]")


def print_success(message: str) -> None:
    """Print success message"""
    console.print(f"[bold green]✓ {message}[/bold green]")