"""Regression checks for the locked, non-root research container boundary."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_lock_and_contains_research_scripts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "uv.lock" in dockerfile
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "COPY scripts ./scripts" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "pip install" not in dockerfile
    assert dockerfile.count("@sha256:") == 3


def test_dockerignore_excludes_local_state_and_secrets() -> None:
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {".env", ".env.*", "runs", "data", "logs"} <= ignored
    assert "uv.lock" not in ignored
    assert "scripts" not in ignored


def test_compose_services_enforce_safe_runtime_boundary() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in ("polysignal", "research"):
        service = services[service_name]
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert service["environment"]["LIVE_TRADING_ENABLED"] == "false"
        assert service["environment"]["ALLOW_AUTO_EXECUTION"] == "false"
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert "env_file" not in service

    research = services["research"]
    assert "research" in research["profiles"]
    assert "./config:/app/config:ro" in research["volumes"]
    assert "./runs:/app/runs" in research["volumes"]
    assert research["command"][-1] == "--help"
