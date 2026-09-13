#!/usr/bin/env python3
"""
PolySignal Pro Dashboard Launcher

Usage:
    python3 scripts/run_dashboard.py              # Launch dashboard
    python3 scripts/run_dashboard.py --check      # Run safety & environment checks
    python3 scripts/run_dashboard.py --port 8502  # Custom port

Safety constraints:
    - Dashboard is READ-ONLY
    - Does NOT write to runs/
    - Does NOT modify config/
    - Does NOT trigger trades
    - Does NOT call real APIs or LLMs
    - localhost only (default 8501)
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
CONFIG_DIR = PROJECT_ROOT / "config"


def check_runs_directory() -> list[str]:
    """Check runs/ directory exists and has data."""
    issues: list[str] = []
    if not RUNS_DIR.exists():
        issues.append("runs/ directory does not exist")
        return issues

    run_dirs = [d for d in RUNS_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")]
    if not run_dirs:
        issues.append("No run_ directories found in runs/")

    summary_count = sum(1 for d in run_dirs if (d / "summary.json").exists())
    if summary_count == 0:
        issues.append("No summary.json files found in any run directory")

    return issues


def check_safety_config() -> list[str]:
    """Check safety config values."""
    issues: list[str] = []
    risk_yaml = CONFIG_DIR / "risk.yaml"
    if not risk_yaml.exists():
        issues.append("config/risk.yaml does not exist")
        return issues

    try:
        import yaml

        with open(risk_yaml, "r") as f:  # noqa: UP015 (read-only gate, see test_dashboard)
            risk_config = yaml.safe_load(f) or {}

        if risk_config.get("live_trading_enabled") is not False:
            issues.append("live_trading_enabled is NOT false in risk.yaml")
        if risk_config.get("allow_auto_execution") is not False:
            issues.append("allow_auto_execution is NOT false in risk.yaml")
        if risk_config.get("paper_trading_enabled") is not True:
            issues.append("paper_trading_enabled is NOT true in risk.yaml")
    except ImportError:
        issues.append("PyYAML not installed (pip install pyyaml)")
    except Exception as e:
        issues.append(f"Failed to read risk.yaml: {e}")

    return issues


def check_data_files() -> dict[str, bool]:
    """Check which data files exist."""
    return {
        "persistent_watchlist.csv": (RUNS_DIR / "persistent_watchlist.csv").exists(),
        "alpha_candidates.csv": (RUNS_DIR / "alpha_candidates.csv").exists(),
        "avoid_candidates.csv": (RUNS_DIR / "avoid_candidates.csv").exists(),
        "intelligence_comparison_summary.json": (
            RUNS_DIR / "intelligence_comparison_summary.json"
        ).exists(),
        "market_trajectories.json": (RUNS_DIR / "market_trajectories.json").exists(),
    }


def check_dashboard_import() -> list[str]:
    """Check that dashboard module can be imported safely."""
    issues: list[str] = []
    try:
        spec = importlib.util.find_spec("polysignal.interface.dashboard")
        if spec is None:
            issues.append("polysignal.interface.dashboard module not found")
    except Exception as e:
        issues.append(f"Cannot locate dashboard module: {e}")

    return issues


def check_no_trading_imports() -> list[str]:
    """Verify dashboard source does not import trading modules (AST-based)."""
    import ast

    issues: list[str] = []
    dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
    if not dashboard_file.exists():
        issues.append("dashboard.py not found")
        return issues

    source = dashboard_file.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        issues.append("dashboard.py has syntax errors")
        return issues

    forbidden_modules = [
        "polysignal.execution.live_trader",
        "polysignal.execution.paper_trader",
        "polysignal.risk.risk_governor",
    ]
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.append(node.module)

    for mod in forbidden_modules:
        if mod in imported_modules:
            issues.append(f"Forbidden import found in dashboard.py: {mod}")

    return issues


def run_check() -> int:
    """Run all safety and environment checks."""
    print("=" * 60)
    print("PolySignal Pro Dashboard — Safety & Environment Check")
    print("=" * 60)
    print()

    all_ok = True

    # 1. Safety config
    print("[1] Safety Configuration")
    safety_issues = check_safety_config()
    if safety_issues:
        for issue in safety_issues:
            print(f"    FAIL: {issue}")
        all_ok = False
    else:
        risk_yaml = CONFIG_DIR / "risk.yaml"
        try:
            import yaml

            with open(risk_yaml, "r") as f:  # noqa: UP015 (read-only gate, see test_dashboard)
                cfg = yaml.safe_load(f) or {}
            print(f"    live_trading_enabled: {cfg.get('live_trading_enabled', 'MISSING')}")
            print(f"    allow_auto_execution: {cfg.get('allow_auto_execution', 'MISSING')}")
            print(f"    paper_trading_enabled: {cfg.get('paper_trading_enabled', 'MISSING')}")
            print("    PASS")
        except Exception:
            print("    PASS (could not read details)")
    print()

    # 2. Runs directory
    print("[2] Runs Directory")
    runs_issues = check_runs_directory()
    if runs_issues:
        for issue in runs_issues:
            print(f"    WARN: {issue}")
    else:
        run_dirs = [d for d in RUNS_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")]
        print(f"    Run directories: {len(run_dirs)}")
        print("    PASS")
    print()

    # 3. Data files
    print("[3] Data Files")
    data_files = check_data_files()
    for name, exists in data_files.items():
        status = "FOUND" if exists else "MISSING"
        print(f"    {name}: {status}")
    print()

    # 4. Dashboard import
    print("[4] Dashboard Module")
    import_issues = check_dashboard_import()
    if import_issues:
        for issue in import_issues:
            print(f"    FAIL: {issue}")
        all_ok = False
    else:
        print("    polysignal.interface.dashboard: FOUND")
        print("    PASS")
    print()

    # 5. Trading imports check
    print("[5] Trading Import Safety")
    trading_issues = check_no_trading_imports()
    if trading_issues:
        for issue in trading_issues:
            print(f"    FAIL: {issue}")
        all_ok = False
    else:
        print("    No LiveTrader import: PASS")
        print("    No PaperTrader import: PASS")
        print("    No RiskGovernor import: PASS")
    print()

    # Summary
    print("=" * 60)
    if all_ok:
        print("ALL CHECKS PASSED")
        print("Dashboard is safe to launch at http://localhost:8501")
        print()
        print("To launch:")
        print("  streamlit run polysignal/interface/dashboard.py --server.port 8501")
        print("  or")
        print("  python3 scripts/run_dashboard.py")
    else:
        print("SOME CHECKS FAILED — review issues above")
    print("=" * 60)

    return 0 if all_ok else 1


def launch_dashboard(port: int = 8501) -> None:
    """Launch Streamlit dashboard."""
    dashboard_file = PROJECT_ROOT / "polysignal" / "interface" / "dashboard.py"
    if not dashboard_file.exists():
        print(f"ERROR: {dashboard_file} not found")
        sys.exit(1)

    try:
        import streamlit.web.cli as st_cli
    except ImportError:
        try:
            import streamlit.web.cli as st_cli
        except ImportError:
            print("ERROR: streamlit not installed. Run: pip install streamlit")
            sys.exit(1)

    sys.argv = [
        "streamlit",
        "run",
        str(dashboard_file),
        "--server.port",
        str(port),
        "--server.address",
        "localhost",
        "--server.headless",
        "true",
    ]
    st_cli.main()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PolySignal Pro Dashboard Launcher",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run safety & environment checks only (do not launch)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port for Streamlit server (default: 8501)",
    )
    args = parser.parse_args()

    if args.check:
        sys.exit(run_check())
    else:
        launch_dashboard(port=args.port)


if __name__ == "__main__":
    main()
