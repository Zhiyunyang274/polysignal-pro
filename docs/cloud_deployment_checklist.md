# Phase 7A — Cloud Deployment Checklist

This checklist documents how to deploy PolySignal Pro to a cloud server for read-only, paper-only research data collection.

PolySignal Pro must remain a research system. Cloud deployment is for data collection, validation, and reporting only.

---

## A. Phase 7A Goals

- Run cloud-side research/data collection.
- Enable read-only market monitoring.
- Enable paper-only runner workflows.
- Move long data collection runs away from local manual waiting.
- Keep local development focused on code, pytest, and short smoke tests.
- Do not connect live trading.
- Do not process private keys.
- Do not store main wallet keys.

---

## B. Recommended Server

Minimum practical server:

- CPU: 2 vCPU
- RAM: 4 GB minimum, 8 GB preferred
- SSD: 40-80 GB
- OS: Ubuntu 22.04 LTS or Ubuntu 24.04 LTS
- Deployment style: Python `venv` first, Docker later

Recommendation: start with `venv` for transparency and simpler debugging. Add Docker after the cloud workflow is stable.

---

## C. Cloud Directory Layout

Recommended root:

```text
/opt/polysignal/
  app/        # PolySignal Pro project code
  runs/       # generated run outputs and validation CSV/JSON/MD files
  logs/       # application, validation, and service logs
  data/       # SQLite database and local data files
  backups/    # compressed runs/data backups
  .env        # server-local environment variables only
```

Keep generated data outside the source tree when possible. If existing code expects local `runs/`, `logs/`, or `data/`, use config paths or symlinks deliberately.

---

## D. Linux User And Permissions

Create a dedicated Linux user:

```bash
sudo adduser --disabled-password --gecos "" polysignal
sudo mkdir -p /opt/polysignal/{app,runs,logs,data,backups}
sudo chown -R polysignal:polysignal /opt/polysignal
```

Permission guidance:

- Run the application as `polysignal`, not `root`.
- Store `/opt/polysignal/.env` locally on the server only.
- Set `.env` permissions:

```bash
chmod 600 /opt/polysignal/.env
chown polysignal:polysignal /opt/polysignal/.env
```

SSH guidance:

- Use SSH key login only.
- Consider disabling password login in `sshd_config`.
- Restrict sudo access to administrators.

---

## E. Deployment Steps

Switch to the server and install base dependencies:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git build-essential
```

Create the directory layout:

```bash
sudo mkdir -p /opt/polysignal/{app,runs,logs,data,backups}
sudo chown -R polysignal:polysignal /opt/polysignal
```

Upload or clone the project into:

```text
/opt/polysignal/app
```

Create and activate a virtual environment:

```bash
sudo -iu polysignal
cd /opt/polysignal/app
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
```

Install project requirements. Use whichever install path the repository currently supports:

```bash
python3 -m pip install -e .
```

If the repository uses a requirements file instead:

```bash
python3 -m pip install -r requirements.txt
```

Configure server-local environment variables:

```bash
nano /opt/polysignal/.env
chmod 600 /opt/polysignal/.env
```

Confirm `.env` is not tracked by Git:

```bash
cd /opt/polysignal/app
git status --short --ignored | grep -E '(^|/)\.env$|(^|/)\.env '
git ls-files --error-unmatch .env
```

Expected result: `.env` is ignored or absent from Git tracking. `git ls-files --error-unmatch .env` should fail.

Confirm `config/risk.yaml` stays safe:

```bash
grep -n "live_trading_enabled: false" config/risk.yaml
grep -n "allow_auto_execution: false" config/risk.yaml
grep -n "paper_trading_enabled: true" config/risk.yaml
```

---

## F. Environment Variables

Environment variables are optional unless a specific provider or alert channel is enabled.

Examples of variable categories:

```bash
# Optional LLM providers
LLM_PROVIDER=mock
DEEPSEEK_API_KEY=
ZAI_API_KEY=
SENSENOVA_API_KEY=
XFYUN_API_KEY=

# Optional Telegram alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Rules:

- Do not write real keys into documentation.
- Do not commit `.env`.
- Keep `.env` only on the server.
- Do not configure private wallet keys.
- Default LLM provider should remain `mock` unless a specific data collection run explicitly requires a real provider.

---

## G. Safety Check Commands

Run these before any cloud collection run:

```bash
cd /opt/polysignal/app
source .venv/bin/activate
```

Safety flags:

```bash
grep -n "live_trading_enabled: false" config/risk.yaml
grep -n "allow_auto_execution: false" config/risk.yaml
grep -n "paper_trading_enabled: true" config/risk.yaml
grep -n 'provider: "mock"' config/llm.yaml
```

Git and secret checks:

```bash
git ls-files --error-unmatch .env
git status --short
grep -RIn "PRIVATE_KEY\\|WALLET_PRIVATE\\|MNEMONIC\\|SECRET_KEY" . \
  --exclude-dir=.git \
  --exclude-dir=.venv \
  --exclude=.env
```

Expected:

- `.env` is not tracked by Git.
- No private key is configured.
- `config/risk.yaml` keeps live trading disabled.
- `config/llm.yaml` default provider remains `mock`.

Dashboard locality:

```bash
python3 scripts/run_dashboard.py --check
```

Expected:

- Dashboard safety check passes.
- Dashboard remains localhost-only.
- No live trading or execution controls are exposed.

---

## H. First Cloud Verification Flow

Run these in order:

1. Full test suite:

```bash
python3 -m pytest tests/ -v
```

2. Dashboard safety check:

```bash
python3 scripts/run_dashboard.py --check
```

3. 5-minute mock smoke test.

4. 5-minute real-readonly smoke test.

5. Confirm output directories are writable:

```bash
test -w /opt/polysignal/runs
test -w /opt/polysignal/logs
test -w /opt/polysignal/data
```

6. Confirm reports are generated in the expected run directory.

---

## I. Recommended 5-Minute Smoke Commands

Mock smoke test:

```bash
python3 scripts/run_paper.py \
  --duration_minutes 5 \
  --max_markets 5 \
  --scan_interval_seconds 60 \
  --data_mode mock \
  --llm_provider mock \
  --max_llm_calls_per_hour 0 \
  --telegram_enabled false
```

Real-readonly smoke test:

```bash
python3 scripts/run_paper.py \
  --duration_minutes 5 \
  --max_markets 5 \
  --scan_interval_seconds 60 \
  --data_mode real_readonly \
  --llm_provider mock \
  --use_websocket true \
  --max_llm_calls_per_hour 0 \
  --telegram_enabled false
```

Notes:

- These smoke tests are short verification runs only.
- Keep `llm_provider mock` unless explicitly testing real LLM connectivity.
- These commands must not create live orders.

---

## J. tmux Manual Run Option

tmux is useful for manual cloud-side observation or one-off long data collection.

Create a session:

```bash
tmux new -s polysignal
```

Run a collection command:

```bash
cd /opt/polysignal/app
source .venv/bin/activate
python3 scripts/run_paper.py \
  --duration_hours 8 \
  --max_markets 30 \
  --scan_interval_seconds 180 \
  --data_mode real_readonly \
  --llm_provider mock \
  --monitor_mode hybrid \
  --alpha_candidates_file runs/alpha_candidates.csv \
  --alpha_priority_ratio 0.5 \
  --alpha_repeat_target 3
```

Detach:

```text
Ctrl-b d
```

Attach:

```bash
tmux attach -t polysignal
```

View logs:

```bash
tail -f /opt/polysignal/logs/*.log
```

Stop safely:

- Press `Ctrl-c` inside the tmux session.
- Wait for graceful shutdown and report generation.

tmux is good for manual runs. It is not ideal for long-term unattended scheduling.

---

## K. systemd Preview

Phase 7A only documents the deployment checklist. It does not create service files.

Phase 7C adds the detailed running plan in:

```text
docs/cloud_running_plan.md
```

It also provides example templates:

```text
deploy/systemd/polysignal-validation.service.example
deploy/systemd/polysignal-validation.timer.example
```

The systemd plan handles:

- scheduled collection
- stdout/stderr capture
- failure visibility
- clean environment loading
- no live trading flags
- no dashboard exposure

These files are examples only. Do not install them until the cloud server has passed the safety checks and smoke tests.

---

## K.1 Phase 7B Validation Loop Script

Phase 7B adds:

```text
scripts/run_validation_loop.py
```

Purpose:

- Run one read-only + paper-only data collection cycle.
- Then run offline validation and report generation:
  - `scripts/validate_strategy_signals.py`
  - `scripts/analyze_run_intelligence.py`
  - `scripts/compare_run_intelligence.py`
- Write `runs/validation_loop_summary.json`.
- Record step success/failure and errors.
- Refuse to run if safety flags are unsafe.

Dry-run command for deployment checks:

```bash
python3 scripts/run_validation_loop.py \
  --duration_minutes 5 \
  --max_markets 5 \
  --scan_interval_seconds 60 \
  --data_mode mock \
  --llm_provider mock \
  --dry_run
```

Skip-run command for regenerating reports from the latest run:

```bash
python3 scripts/run_validation_loop.py \
  --skip_run \
  --output_dir runs
```

Example cloud validation loop:

```bash
python3 scripts/run_validation_loop.py \
  --duration_hours 4 \
  --max_markets 30 \
  --scan_interval_seconds 180 \
  --data_mode real_readonly \
  --use_websocket true \
  --llm_provider mock \
  --monitor_mode hybrid \
  --alpha_candidates_file runs/alpha_candidates.csv \
  --avoid_candidates_file runs/avoid_candidates.csv \
  --watchlist_file runs/persistent_watchlist.csv \
  --alpha_priority_ratio 0.5 \
  --alpha_repeat_target 3 \
  --control_group_sampling_ratio 0.1 \
  --output_dir runs
```

Safety:

- The script does not import LiveTrader, PaperTrader, RiskGovernor, or strategies.
- The script does not modify config.
- The script does not open dashboard ports.
- Long runs should execute on cloud, not as local development blockers.

---

## K.2 Phase 7D Daily Report Automation

Phase 7D adds:

```text
scripts/generate_daily_report.py
```

Purpose:

- Read existing run outputs under `runs/`.
- Summarize recent run activity.
- Summarize validation and intelligence comparison outputs.
- Summarize persistent watchlist, alpha candidates, and avoid candidates.
- Write `daily_report.md`.
- Write `daily_report_summary.json`.

Dry-run command:

```bash
python3 scripts/generate_daily_report.py \
  --runs_dir runs \
  --output_dir runs \
  --latest_n 10 \
  --dry_run
```

Generate report:

```bash
python3 scripts/generate_daily_report.py \
  --runs_dir runs \
  --output_dir runs \
  --latest_n 10
```

Safety:

- Offline-only report generation.
- Does not run `run_paper.py`.
- Does not call real APIs or real LLM providers.
- Does not modify config, Risk Governor, or strategy logic.
- Does not turn alpha or avoid scores into trading decisions.

See `docs/cloud_running_plan.md` for cloud usage.

---

## L. Logs And Backups

Logs:

```text
/opt/polysignal/logs/
  app.log
  validation_loop.log
  daily_report.log
  health_check.log
```

Backup recommendations:

- Daily compressed backup of `runs/`.
- Daily SQLite backup from `data/`.
- Keep recent backups in `/opt/polysignal/backups`.
- Add remote backup later if needed.

Example local backup:

```bash
tar -czf /opt/polysignal/backups/runs_$(date +%Y%m%d).tar.gz -C /opt/polysignal runs
sqlite3 /opt/polysignal/data/polysignal.db ".backup '/opt/polysignal/backups/polysignal_$(date +%Y%m%d).db'"
```

Log rotation:

- Add `logrotate` later.
- Rotate daily.
- Keep 14-30 days.
- Compress old logs.
- Never log secrets.

---

## M. Dashboard Safe Access

Dashboard rules:

- Bind only to localhost.
- Do not expose dashboard ports directly to the public internet.
- Use SSH tunnel for access.

Example SSH tunnel:

```bash
ssh -L 8501:127.0.0.1:8501 polysignal@SERVER_IP
```

Then open locally:

```text
http://127.0.0.1:8501
```

---

## N. Troubleshooting

Python environment problems:

```bash
which python3
python3 --version
source /opt/polysignal/app/.venv/bin/activate
python3 -m pip list
```

Missing API key:

- Keep provider as `mock` unless real LLM testing is intentional.
- If real providers are enabled, confirm required env vars exist.
- Do not paste real keys into logs or reports.

Network errors:

- Check DNS and outbound HTTPS.
- Retry short smoke tests.
- Confirm Polymarket public endpoints are reachable.

Permission denied:

```bash
ls -ld /opt/polysignal /opt/polysignal/{runs,logs,data,backups}
sudo chown -R polysignal:polysignal /opt/polysignal
```

Disk full:

```bash
df -h
du -sh /opt/polysignal/runs /opt/polysignal/logs /opt/polysignal/backups
```

Streamlit missing:

```bash
source /opt/polysignal/app/.venv/bin/activate
python3 -m pip install streamlit
python3 scripts/run_dashboard.py --check
```

pytest failures:

- Read the first failure, not just the summary.
- Confirm Python version and env vars.
- Clear unexpected provider/model overrides.
- Re-run only the failing test module before the full suite.

---

## O. Prohibited Actions

Do not:

- Connect live trading.
- Process private keys.
- Modify Risk Governor for deployment convenience.
- Lower strategy thresholds.
- Let `alpha_score` become a trading signal.
- Automatically place orders.
- Open dashboard to the public internet.
- Commit `.env` to Git.
- Store main wallet private keys on the server.

---

## P. Phase 7A Acceptance Criteria

Phase 7A is complete when:

- `docs/cloud_deployment_checklist.md` exists.
- Deployment steps are executable by an operator.
- Safety checks are explicit and complete.
- Business code is not modified.
- `config/risk.yaml` is not modified.
- No live trading pathway is added.
- Long data collection is documented as cloud-side work, not local development blocking work.
