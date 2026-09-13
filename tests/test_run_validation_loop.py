"""Tests for Phase 7B validation loop orchestration."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import run_validation_loop as rvl


def write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def safe_config(tmp_path: Path) -> tuple[Path, Path]:
    risk = tmp_path / "config" / "risk.yaml"
    llm = tmp_path / "config" / "llm.yaml"
    write_yaml(
        risk,
        "\n".join([
            "live_trading_enabled: false",
            "allow_auto_execution: false",
            "paper_trading_enabled: true",
        ]),
    )
    write_yaml(llm, 'provider: "mock"\n')
    return risk, llm


def test_safety_check_reads_safe_defaults(safe_config: tuple[Path, Path]):
    risk, llm = safe_config

    safety = rvl.verify_safety(risk, llm)

    assert safety["live_trading_enabled"] is False
    assert safety["allow_auto_execution"] is False
    assert safety["paper_trading_enabled"] is True
    assert safety["default_llm_provider"] == "mock"
    assert safety["safe_to_run"] is True


def test_live_trading_enabled_refuses_run(safe_config: tuple[Path, Path]):
    risk, llm = safe_config
    write_yaml(
        risk,
        "\n".join([
            "live_trading_enabled: true",
            "allow_auto_execution: false",
            "paper_trading_enabled: true",
        ]),
    )

    with pytest.raises(rvl.SafetyCheckError, match="live_trading_enabled"):
        rvl.verify_safety(risk, llm)


def test_allow_auto_execution_refuses_run(safe_config: tuple[Path, Path]):
    risk, llm = safe_config
    write_yaml(
        risk,
        "\n".join([
            "live_trading_enabled: false",
            "allow_auto_execution: true",
            "paper_trading_enabled: true",
        ]),
    )

    with pytest.raises(rvl.SafetyCheckError, match="allow_auto_execution"):
        rvl.verify_safety(risk, llm)


def test_default_parameters_are_safe():
    args = rvl.parse_args([])

    assert args.data_mode == "mock"
    assert args.llm_provider == "mock"
    assert args.max_llm_calls_per_hour == 0
    assert args.enable_llm_sampling is False
    assert args.alpha_priority_ratio == 0.0
    assert args.alpha_repeat_target == 3
    assert args.control_group_sampling_ratio == 0.0


def test_command_construction_includes_requested_parameters():
    args = rvl.parse_args([
        "--duration_minutes", "5",
        "--max_markets", "7",
        "--scan_interval_seconds", "30",
        "--data_mode", "real_readonly",
        "--use_websocket", "true",
        "--llm_provider", "mock",
        "--max_llm_calls_per_hour", "0",
        "--enable_llm_sampling", "true",
        "--llm_sampling_per_scan", "2",
        "--alpha_candidates_file", "runs/alpha_candidates.csv",
        "--monitor_mode", "hybrid",
        "--alpha_priority_ratio", "0.5",
        "--alpha_repeat_target", "3",
        "--control_group_sampling_ratio", "0.2",
    ])

    cmd = rvl.build_run_command(args)

    assert "scripts/run_paper.py" in cmd
    assert cmd[cmd.index("--duration_minutes") + 1] == "5"
    assert cmd[cmd.index("--data_mode") + 1] == "real_readonly"
    assert cmd[cmd.index("--use_websocket") + 1] == "true"
    assert cmd[cmd.index("--enable_llm_sampling") + 1] == "true"
    assert cmd[cmd.index("--alpha_priority_ratio") + 1] == "0.5"
    assert cmd[cmd.index("--alpha_repeat_target") + 1] == "3"
    assert cmd[cmd.index("--control_group_sampling_ratio") + 1] == "0.2"
    assert "--telegram_enabled" in cmd
    assert cmd[cmd.index("--telegram_enabled") + 1] == "false"


def test_dry_run_does_not_execute_external_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("subprocess.run should not be called in dry_run")

    monkeypatch.setattr(rvl.subprocess, "run", fake_run)
    args = rvl.parse_args(["--dry_run", "--output_dir", str(tmp_path)])

    exit_code = rvl.run_validation_loop(args)

    assert exit_code == 0
    assert calls == []


def test_skip_run_only_runs_reporting_steps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    run_dir = tmp_path / "run_20260511_000000_test"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text("{}")
    executed = []

    def fake_verify():
        return {
            "live_trading_enabled": False,
            "allow_auto_execution": False,
            "paper_trading_enabled": True,
            "default_llm_provider": "mock",
            "safe_to_run": True,
        }

    def fake_run_step(name: str, command: list[str], cwd: Path = rvl.REPO_ROOT):
        executed.append(name)
        return rvl.StepResult(name=name, command=command, success=True, returncode=0)

    monkeypatch.setattr(rvl, "verify_safety", fake_verify)
    monkeypatch.setattr(rvl, "run_step", fake_run_step)
    args = rvl.parse_args(["--skip_run", "--output_dir", str(tmp_path)])

    exit_code = rvl.run_validation_loop(args)

    assert exit_code == 0
    assert executed == [
        "validate_strategy_signals",
        "analyze_run_intelligence",
        "compare_run_intelligence",
    ]
    summary = json.loads((tmp_path / rvl.SUMMARY_FILENAME).read_text())
    assert summary["run_success"] is True
    assert summary["run_id"] == run_dir.name


def test_summary_json_format(tmp_path: Path):
    state = rvl.LoopState()
    state.run_command = ["python3", "scripts/run_paper.py"]
    state.run_id = "run_test"
    state.run_success = True
    state.validation_success = True
    state.intelligence_success = True
    state.comparison_success = True
    state.safety_verification = {"live_trading_enabled": False}

    path = rvl.write_summary(tmp_path, state)
    data = json.loads(path.read_text())

    for key in [
        "started_at",
        "ended_at",
        "duration_seconds",
        "run_command",
        "run_id",
        "run_success",
        "validation_success",
        "intelligence_success",
        "comparison_success",
        "generated_files",
        "safety_verification",
        "errors",
    ]:
        assert key in data


def test_step_failure_records_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def fake_verify():
        return {"safe_to_run": True}

    def fake_run_step(name: str, command: list[str], cwd: Path = rvl.REPO_ROOT):
        return rvl.StepResult(
            name=name,
            command=command,
            success=False,
            returncode=1,
            stderr="boom",
            error="failed",
        )

    monkeypatch.setattr(rvl, "verify_safety", fake_verify)
    monkeypatch.setattr(rvl, "run_step", fake_run_step)
    args = rvl.parse_args(["--output_dir", str(tmp_path)])

    exit_code = rvl.run_validation_loop(args)

    assert exit_code == 1
    data = json.loads((tmp_path / rvl.SUMMARY_FILENAME).read_text())
    assert data["run_success"] is False
    assert data["errors"]
    assert data["errors"][0]["name"] == "run_paper"


def test_redact_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XFYUN_API_KEY", "super-secret-key")

    redacted = rvl.redact_secrets("provider failed with super-secret-key")

    assert "super-secret-key" not in redacted
    assert "[REDACTED]" in redacted


def test_no_forbidden_trading_imports():
    source = (Path(__file__).resolve().parent.parent / "scripts" / "run_validation_loop.py").read_text()
    tree = ast.parse(source)
    forbidden = (
        "polysignal.execution.live_trader",
        "polysignal.execution.paper_trader",
        "polysignal.risk.risk_governor",
        "polysignal.strategies",
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not any(module.startswith(name) for name in forbidden)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(alias.name.startswith(name) for name in forbidden)


def test_dry_run_does_not_modify_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    risk_path = Path(__file__).resolve().parent.parent / "config" / "risk.yaml"
    before = risk_path.read_text()

    monkeypatch.setattr(rvl, "verify_safety", lambda: {"safe_to_run": True})
    args = rvl.parse_args(["--dry_run", "--output_dir", str(tmp_path)])

    assert rvl.run_validation_loop(args) == 0
    assert risk_path.read_text() == before


def test_safety_failure_writes_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def fake_verify():
        raise rvl.SafetyCheckError("Refusing to run: live_trading_enabled must be false")

    monkeypatch.setattr(rvl, "verify_safety", fake_verify)
    args = rvl.parse_args(["--output_dir", str(tmp_path)])

    exit_code = rvl.run_validation_loop(args)

    assert exit_code == 2
    data = json.loads((tmp_path / rvl.SUMMARY_FILENAME).read_text())
    assert data["safety_verification"]["safe_to_run"] is False
    assert "live_trading_enabled" in data["errors"][0]["error"]
