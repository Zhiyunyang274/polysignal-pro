#!/usr/bin/env python3
"""
Phase 7B — Validation Loop Orchestrator.

Run one read-only + paper-only data collection cycle and then generate offline
validation, intelligence, and comparison reports.

IMPORTANT SAFETY CONSTRAINTS:
- Does NOT import LiveTrader, PaperTrader, RiskGovernor, or strategies
- Does NOT connect live trading
- Does NOT handle private keys
- Does NOT modify config
- Does NOT open any dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from polysignal.utils.time import utc_now

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"
SUMMARY_FILENAME = "validation_loop_summary.json"
SECRET_ENV_TOKENS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE", "MNEMONIC")


class SafetyCheckError(RuntimeError):
    """Raised when safety configuration rejects execution."""


@dataclass
class StepResult:
    """Result of one orchestration step."""

    name: str
    command: list[str]
    success: bool = False
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "success": self.success,
            "returncode": self.returncode,
            "stdout": self.stdout[-4000:] if self.stdout else "",
            "stderr": self.stderr[-4000:] if self.stderr else "",
            "error": self.error,
        }


@dataclass
class LoopState:
    """State accumulated during a validation loop run."""

    started_at: datetime = field(default_factory=utc_now)
    ended_at: datetime | None = None
    run_command: list[str] = field(default_factory=list)
    run_id: str | None = None
    run_success: bool = False
    validation_success: bool = False
    intelligence_success: bool = False
    comparison_success: bool = False
    generated_files: list[str] = field(default_factory=list)
    safety_verification: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        ended_at = self.ended_at or utc_now()
        return {
            "started_at": self.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": (ended_at - self.started_at).total_seconds(),
            "run_command": self.run_command,
            "run_id": self.run_id,
            "run_success": self.run_success,
            "validation_success": self.validation_success,
            "intelligence_success": self.intelligence_success,
            "comparison_success": self.comparison_success,
            "generated_files": self.generated_files,
            "safety_verification": self.safety_verification,
            "errors": self.errors,
            "steps": [s.to_dict() for s in self.steps],
        }


def parse_bool(value: str) -> bool:
    """Parse CLI bool values."""
    return value.lower() in ("true", "1", "yes", "y", "on")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 7B — run one read-only validation loop and reports",
    )

    parser.add_argument("--duration_hours", type=float, default=None)
    parser.add_argument("--duration_minutes", type=int, default=30)
    parser.add_argument("--max_markets", type=int, default=10)
    parser.add_argument("--scan_interval_seconds", type=int, default=120)
    parser.add_argument(
        "--data_mode",
        choices=["mock", "real_readonly", "hybrid"],
        default="mock",
    )
    parser.add_argument("--use_websocket", type=parse_bool, default=True)
    parser.add_argument("--llm_provider", type=str, default="mock")
    parser.add_argument("--max_llm_calls_per_hour", type=int, default=0)
    parser.add_argument("--enable_llm_sampling", type=parse_bool, default=False)
    parser.add_argument("--llm_sampling_per_scan", type=int, default=1)
    parser.add_argument("--watchlist_file", type=str, default=None)
    parser.add_argument("--alpha_candidates_file", type=str, default=None)
    parser.add_argument("--avoid_candidates_file", type=str, default=None)
    parser.add_argument(
        "--monitor_mode",
        choices=["default", "hybrid", "watchlist"],
        default="default",
    )
    parser.add_argument("--alpha_priority_ratio", type=float, default=0.0)
    parser.add_argument("--alpha_repeat_target", type=int, default=3)
    parser.add_argument("--control_group_sampling_ratio", type=float, default=0.0)
    parser.add_argument("--output_dir", type=str, default="runs")

    parser.add_argument("--skip_run", action="store_true")
    parser.add_argument("--skip_validation", action="store_true")
    parser.add_argument("--skip_intelligence", action="store_true")
    parser.add_argument("--skip_comparison", action="store_true")
    parser.add_argument("--dry_run", action="store_true")

    return parser.parse_args(argv)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def verify_safety(
    risk_config_path: Path = REPO_ROOT / "config" / "risk.yaml",
    llm_config_path: Path = REPO_ROOT / "config" / "llm.yaml",
) -> dict[str, Any]:
    """Verify that the validation loop can only run in safe defaults."""
    risk = load_yaml(risk_config_path)
    llm = load_yaml(llm_config_path)

    safety = {
        "live_trading_enabled": bool(risk.get("live_trading_enabled")),
        "allow_auto_execution": bool(risk.get("allow_auto_execution")),
        "paper_trading_enabled": bool(risk.get("paper_trading_enabled")),
        "default_llm_provider": llm.get("provider"),
        "risk_config_path": str(risk_config_path),
        "llm_config_path": str(llm_config_path),
    }

    if safety["live_trading_enabled"]:
        raise SafetyCheckError("Refusing to run: live_trading_enabled must be false")
    if safety["allow_auto_execution"]:
        raise SafetyCheckError("Refusing to run: allow_auto_execution must be false")
    if not safety["paper_trading_enabled"]:
        raise SafetyCheckError("Refusing to run: paper_trading_enabled must be true")
    if safety["default_llm_provider"] != "mock":
        raise SafetyCheckError("Refusing to run: config/llm.yaml provider must default to mock")

    safety["safe_to_run"] = True
    return safety


def build_run_command(args: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, "scripts/run_paper.py"]

    if args.duration_hours is not None:
        cmd.extend(["--duration_hours", str(args.duration_hours)])
    else:
        cmd.extend(["--duration_minutes", str(args.duration_minutes)])

    cmd.extend([
        "--max_markets", str(args.max_markets),
        "--scan_interval_seconds", str(args.scan_interval_seconds),
        "--data_mode", args.data_mode,
        "--use_websocket", "true" if args.use_websocket else "false",
        "--llm_provider", args.llm_provider,
        "--max_llm_calls_per_hour", str(args.max_llm_calls_per_hour),
        "--enable_llm_sampling", "true" if args.enable_llm_sampling else "false",
        "--llm_sampling_per_scan", str(args.llm_sampling_per_scan),
        "--monitor_mode", args.monitor_mode,
        "--alpha_priority_ratio", str(args.alpha_priority_ratio),
        "--alpha_repeat_target", str(args.alpha_repeat_target),
        "--control_group_sampling_ratio", str(args.control_group_sampling_ratio),
        "--telegram_enabled", "false",
        "--max_telegram_messages_per_hour", "0",
    ])

    optional_paths = {
        "--watchlist_file": args.watchlist_file,
        "--alpha_candidates_file": args.alpha_candidates_file,
        "--avoid_candidates_file": args.avoid_candidates_file,
    }
    for flag, value in optional_paths.items():
        if value:
            cmd.extend([flag, value])

    return cmd


def build_validation_command(output_dir: Path) -> list[str]:
    out = str(output_dir)
    return [
        sys.executable,
        "scripts/validate_strategy_signals.py",
        "--runs_dir",
        out,
        "--output_dir",
        out,
        "--min_appearances",
        "2",
    ]


def build_intelligence_command(run_dir: Path) -> list[str]:
    return [
        sys.executable,
        "scripts/analyze_run_intelligence.py",
        "--run_dir",
        str(run_dir),
        "--export_csv",
    ]


def build_comparison_command(output_dir: Path) -> list[str]:
    out = str(output_dir)
    return [
        sys.executable,
        "scripts/compare_run_intelligence.py",
        "--runs_dir",
        out,
        "--output_dir",
        out,
        "--latest_n",
        "30",
        "--export_csv",
    ]


def find_latest_run(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    run_dirs = [
        p for p in runs_dir.iterdir()
        if p.is_dir() and p.name.startswith("run_") and (p / "summary.json").exists()
    ]
    if not run_dirs:
        return None
    run_dirs.sort(key=lambda p: p.name, reverse=True)
    return run_dirs[0]


def collect_generated_files(output_dir: Path, run_dir: Path | None) -> list[str]:
    candidates = [
        output_dir / "strategy_validation_report.md",
        output_dir / "strategy_validation_summary.json",
        output_dir / "alpha_validation.csv",
        output_dir / "avoid_validation.csv",
        output_dir / "watchlist_validation.csv",
        output_dir / "intelligence_comparison_report.md",
        output_dir / "intelligence_comparison_summary.json",
        output_dir / "persistent_watchlist.csv",
        output_dir / "alpha_candidates.csv",
        output_dir / "avoid_candidates.csv",
        output_dir / "market_trajectories.json",
        output_dir / SUMMARY_FILENAME,
    ]
    if run_dir:
        candidates.extend([
            run_dir / "summary.json",
            run_dir / "report.md",
            run_dir / "intelligence_report.md",
            run_dir / "intelligence_summary.json",
            run_dir / "sampled_markets.csv",
            run_dir / "alpha_repeat_observation_summary.json",
            run_dir / "alpha_repeat_observation_report.md",
            run_dir / "control_group_samples.csv",
            run_dir / "validation_loop_summary.json",
        ])
    return [str(p) for p in candidates if p.exists()]


def redact_secrets(text: str) -> str:
    """Best-effort redaction for logs and subprocess output."""
    redacted = text or ""
    for key, value in os.environ.items():
        if not value:
            continue
        if any(token in key.upper() for token in SECRET_ENV_TOKENS):
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def run_step(name: str, command: list[str], cwd: Path = REPO_ROOT) -> StepResult:
    print(f"\n=== {name} ===")
    print(" ".join(command))
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
        )
        result = StepResult(
            name=name,
            command=command,
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=redact_secrets(proc.stdout),
            stderr=redact_secrets(proc.stderr),
        )
        if not result.success:
            result.error = f"{name} failed with return code {proc.returncode}"
        return result
    except Exception as exc:
        return StepResult(
            name=name,
            command=command,
            success=False,
            error=redact_secrets(str(exc)),
        )


def write_summary(output_dir: Path, state: LoopState) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    state.ended_at = state.ended_at or utc_now()
    path = output_dir / SUMMARY_FILENAME
    path.write_text(json.dumps(state.to_summary(), indent=2))
    return path


def print_dry_run(commands: list[tuple[str, list[str]]]) -> None:
    print("DRY RUN: commands that would execute")
    for name, cmd in commands:
        print(f"\n[{name}]")
        print(" ".join(cmd))


def run_validation_loop(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    state = LoopState()

    try:
        state.safety_verification = verify_safety()
    except SafetyCheckError as exc:
        state.safety_verification = {"safe_to_run": False}
        state.errors.append({"step": "safety_check", "error": str(exc)})
        write_summary(output_dir, state)
        print(f"SAFETY CHECK FAILED: {exc}")
        return 2

    run_command = build_run_command(args)
    state.run_command = run_command

    latest_before = find_latest_run(output_dir)
    run_dir: Path | None = None
    commands: list[tuple[str, list[str]]] = []

    if not args.skip_run:
        commands.append(("run_paper", run_command))

    if args.skip_run:
        run_dir = find_latest_run(output_dir)
        if not run_dir:
            state.errors.append({"step": "skip_run", "error": "No latest run found"})
            write_summary(output_dir, state)
            print("No latest run found for --skip_run")
            return 1
        state.run_id = run_dir.name
        state.run_success = True

    if not args.skip_validation:
        commands.append(("validate_strategy_signals", build_validation_command(output_dir)))
    if not args.skip_intelligence:
        dry_run_dir = run_dir or latest_before or (output_dir / "run_<new_run_id>")
        commands.append(("analyze_run_intelligence", build_intelligence_command(dry_run_dir)))
    if not args.skip_comparison:
        commands.append(("compare_run_intelligence", build_comparison_command(output_dir)))

    if args.dry_run:
        print_dry_run(commands)
        return 0

    if not args.skip_run:
        result = run_step("run_paper", run_command)
        state.steps.append(result)
        state.run_success = result.success
        if not result.success:
            state.errors.append(result.to_dict())
            state.generated_files = collect_generated_files(output_dir, None)
            write_summary(output_dir, state)
            return 1

        latest_after = find_latest_run(output_dir)
        run_dir = latest_after or latest_before
        if run_dir:
            state.run_id = run_dir.name
        else:
            state.errors.append({"step": "run_paper", "error": "Run succeeded but no run directory found"})
            write_summary(output_dir, state)
            return 1

    if not args.skip_validation:
        result = run_step("validate_strategy_signals", build_validation_command(output_dir))
        state.steps.append(result)
        state.validation_success = result.success
        if not result.success:
            state.errors.append(result.to_dict())
            state.generated_files = collect_generated_files(output_dir, run_dir)
            write_summary(output_dir, state)
            return 1
    else:
        state.validation_success = True

    if not args.skip_intelligence:
        if not run_dir:
            state.errors.append({"step": "analyze_run_intelligence", "error": "No run directory available"})
            write_summary(output_dir, state)
            return 1
        result = run_step("analyze_run_intelligence", build_intelligence_command(run_dir))
        state.steps.append(result)
        state.intelligence_success = result.success
        if not result.success:
            state.errors.append(result.to_dict())
            state.generated_files = collect_generated_files(output_dir, run_dir)
            write_summary(output_dir, state)
            return 1
    else:
        state.intelligence_success = True

    if not args.skip_comparison:
        result = run_step("compare_run_intelligence", build_comparison_command(output_dir))
        state.steps.append(result)
        state.comparison_success = result.success
        if not result.success:
            state.errors.append(result.to_dict())
            state.generated_files = collect_generated_files(output_dir, run_dir)
            write_summary(output_dir, state)
            return 1
    else:
        state.comparison_success = True

    state.generated_files = collect_generated_files(output_dir, run_dir)
    summary_path = write_summary(output_dir, state)
    print(f"\nValidation loop summary: {summary_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_validation_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
