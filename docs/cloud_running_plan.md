# Cloud Running Plan

Phase 7C defines the standard cloud running plan for PolySignal Pro data collection.

This plan is for research and data collection only:

- read-only market monitoring
- paper-only runner
- scheduled validation loop execution
- automatic report generation through the validation loop
- no live trading
- no private key handling
- no main wallet key storage

---

## A. Phase 7C Goal

The goal is to make cloud data collection repeatable and observable without turning it into a live trading system.

Phase 7C provides:

- tmux commands for supervised manual long runs
- systemd service and timer templates for scheduled cloud runs
- standard paths for app, runs, logs, data, backups, and local environment
- safety checks before any scheduled data collection
- stop, restart, status, and log inspection commands

The cloud host should run only in read-only + paper-only mode.

---

## B. tmux Manual Running Plan

Use tmux when you want an attended long run that can survive SSH disconnects.

Create a session:

```bash
tmux new -s polysignal-validation
```

Go to the app directory:

```bash
cd /opt/polysignal/app
source .venv/bin/activate
```

Run a validation loop dry run first:

```bash
python3 scripts/run_validation_loop.py \
  --duration_minutes 5 \
  --max_markets 5 \
  --scan_interval_seconds 60 \
  --data_mode mock \
  --llm_provider mock \
  --dry_run
```

Run a short smoke test before any long collection:

```bash
python3 scripts/run_validation_loop.py \
  --duration_minutes 5 \
  --max_markets 5 \
  --scan_interval_seconds 60 \
  --data_mode mock \
  --llm_provider mock \
  --output_dir /opt/polysignal/runs
```

Optional real read-only smoke test:

```bash
python3 scripts/run_validation_loop.py \
  --duration_minutes 5 \
  --max_markets 5 \
  --scan_interval_seconds 60 \
  --data_mode real_readonly \
  --use_websocket true \
  --llm_provider mock \
  --output_dir /opt/polysignal/runs
```

Start an attended overnight collection only after the smoke test passes:

```bash
python3 scripts/run_validation_loop.py \
  --duration_hours 8 \
  --max_markets 30 \
  --scan_interval_seconds 180 \
  --data_mode real_readonly \
  --use_websocket true \
  --llm_provider mock \
  --monitor_mode hybrid \
  --watchlist_file /opt/polysignal/runs/persistent_watchlist.csv \
  --alpha_candidates_file /opt/polysignal/runs/alpha_candidates.csv \
  --avoid_candidates_file /opt/polysignal/runs/avoid_candidates.csv \
  --alpha_priority_ratio 0.5 \
  --alpha_repeat_target 3 \
  --control_group_sampling_ratio 0.1 \
  --output_dir /opt/polysignal/runs \
  2>&1 | tee -a /opt/polysignal/logs/validation-loop-manual.log
```

Detach from tmux:

```bash
Ctrl-b d
```

Attach again:

```bash
tmux attach -t polysignal-validation
```

List sessions:

```bash
tmux ls
```

View logs:

```bash
tail -f /opt/polysignal/logs/validation-loop-manual.log
```

Safe stop:

```bash
Ctrl-c
```

If the process does not stop cleanly, find it before killing it:

```bash
pgrep -af "scripts/run_validation_loop.py"
```

Then stop only the matching validation loop process:

```bash
kill <pid>
```

tmux is good for manual supervision. It is not the preferred long-term unattended scheduler.

---

## C. systemd Formal Running Plan

Use systemd for scheduled, unattended cloud data collection.

The service should be a one-shot job launched by a timer. The timer controls the schedule, and the service performs exactly one validation loop run.

Recommended behavior:

- `Type=oneshot`
- `User=polysignal`
- fixed `WorkingDirectory`
- local `.env` loaded by `EnvironmentFile`
- stdout and stderr appended to files under `/opt/polysignal/logs`
- no restart loop for data collection failures
- failures remain visible through `systemctl status` and `journalctl`
- timer uses `Persistent=true` so missed runs execute after downtime
- schedule should be daily or similarly conservative, not frequent

Do not put secrets into the unit file. Keep them in `/opt/polysignal/.env` with `chmod 600`.

---

## D. Suggested File Paths

```text
/etc/systemd/system/polysignal-validation.service
/etc/systemd/system/polysignal-validation.timer
/opt/polysignal/app
/opt/polysignal/logs
/opt/polysignal/runs
/opt/polysignal/.env
```

The repository contains example templates only:

```text
deploy/systemd/polysignal-validation.service.example
deploy/systemd/polysignal-validation.timer.example
```

Copy and review these examples on the cloud server before installing them into `/etc/systemd/system/`.

---

## E. systemd Service Template

Example:

```ini
[Unit]
Description=PolySignal Pro validation loop
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=polysignal
Group=polysignal
WorkingDirectory=/opt/polysignal/app
EnvironmentFile=/opt/polysignal/.env
ExecStart=/opt/polysignal/app/.venv/bin/python3 scripts/run_validation_loop.py --duration_hours 4 --max_markets 30 --scan_interval_seconds 180 --data_mode real_readonly --use_websocket true --llm_provider mock --max_llm_calls_per_hour 0 --enable_llm_sampling false --monitor_mode hybrid --alpha_candidates_file /opt/polysignal/runs/alpha_candidates.csv --avoid_candidates_file /opt/polysignal/runs/avoid_candidates.csv --watchlist_file /opt/polysignal/runs/persistent_watchlist.csv --alpha_priority_ratio 0.5 --alpha_repeat_target 3 --control_group_sampling_ratio 0.1 --output_dir /opt/polysignal/runs
StandardOutput=append:/opt/polysignal/logs/validation-loop.log
StandardError=append:/opt/polysignal/logs/validation-loop.err.log
TimeoutStartSec=6h
Restart=no
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

This template:

- runs as `polysignal`
- uses `/opt/polysignal/app` as the working directory
- loads `/opt/polysignal/.env`
- runs `python3 scripts/run_validation_loop.py`
- uses conservative paper-only parameters
- keeps `llm_provider=mock` by default
- does not use live trading flags
- does not expose dashboard
- does not write or reference private keys

---

## F. systemd Timer Template

Example daily timer:

```ini
[Unit]
Description=Run PolySignal Pro validation loop daily

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
RandomizedDelaySec=10m
Unit=polysignal-validation.service

[Install]
WantedBy=timers.target
```

Use one daily schedule first. Avoid frequent repeated triggers because a data collection run can take hours.

Alternative examples:

```ini
OnCalendar=Mon..Fri 02:30:00
```

```ini
OnCalendar=*-*-* 01:00:00
```

Do not use short intervals such as every 5 minutes for long-running data collection.

---

## G. Common Commands

Copy reviewed templates into place:

```bash
sudo cp deploy/systemd/polysignal-validation.service.example /etc/systemd/system/polysignal-validation.service
sudo cp deploy/systemd/polysignal-validation.timer.example /etc/systemd/system/polysignal-validation.timer
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable timer:

```bash
sudo systemctl enable polysignal-validation.timer
```

Start timer:

```bash
sudo systemctl start polysignal-validation.timer
```

Start one run manually:

```bash
sudo systemctl start polysignal-validation.service
```

Check status:

```bash
systemctl status polysignal-validation.service
systemctl status polysignal-validation.timer
```

Restart the timer after editing the schedule:

```bash
sudo systemctl restart polysignal-validation.timer
```

Restart a one-shot service intentionally:

```bash
sudo systemctl restart polysignal-validation.service
```

View logs:

```bash
journalctl -u polysignal-validation.service -n 200 --no-pager
journalctl -u polysignal-validation.service -f
```

Stop an active service:

```bash
sudo systemctl stop polysignal-validation.service
```

Disable scheduled runs:

```bash
sudo systemctl disable --now polysignal-validation.timer
```

---

## H. Log Viewing

Journal logs:

```bash
journalctl -u polysignal-validation.service -n 200 --no-pager
journalctl -u polysignal-validation.service -f
```

File logs:

```bash
tail -f /opt/polysignal/logs/validation-loop.log
tail -f /opt/polysignal/logs/validation-loop.err.log
```

Latest run reports:

```bash
ls -td /opt/polysignal/runs/run_* | head -1
cat /opt/polysignal/runs/validation_loop_summary.json
cat /opt/polysignal/runs/strategy_validation_report.md
cat /opt/polysignal/runs/intelligence_comparison_report.md
```

If intelligence analysis ran for a specific run:

```bash
latest_run="$(ls -td /opt/polysignal/runs/run_* | head -1)"
cat "$latest_run/intelligence_report.md"
cat "$latest_run/intelligence_summary.json"
```

---

## I. Safety Checks

Run these checks before enabling the timer:

```bash
cd /opt/polysignal/app
source .venv/bin/activate
python3 - <<'PY'
from pathlib import Path
import yaml

risk = yaml.safe_load(Path("config/risk.yaml").read_text())
llm = yaml.safe_load(Path("config/llm.yaml").read_text())

assert risk["live_trading_enabled"] is False
assert risk["allow_auto_execution"] is False
assert risk["paper_trading_enabled"] is True
assert llm["provider"] == "mock"

print("safety ok")
PY
```

Check `.env` permissions:

```bash
stat -c "%a %U %G %n" /opt/polysignal/.env
chmod 600 /opt/polysignal/.env
chown polysignal:polysignal /opt/polysignal/.env
```

Confirm `.env` does not contain a private key:

```bash
grep -Ei "PRIVATE_KEY|MNEMONIC|SEED|WALLET_SECRET" /opt/polysignal/.env || true
```

Expected result: no configured main wallet private key.

Confirm the dashboard is localhost only if it is ever run:

```bash
grep -R "server.address" /opt/polysignal/app/.streamlit 2>/dev/null || true
```

Dashboard should not be exposed on a public interface.

Also confirm:

- `live_trading_enabled=false`
- `allow_auto_execution=false`
- `paper_trading_enabled=true`
- default LLM provider is `mock`
- `.env` is not tracked by Git
- no private key is configured
- dashboard access uses localhost or SSH tunnel only

---

## J. Troubleshooting

service failed:

```bash
systemctl status polysignal-validation.service
journalctl -u polysignal-validation.service -n 200 --no-pager
```

permission denied:

```bash
sudo chown -R polysignal:polysignal /opt/polysignal
ls -ld /opt/polysignal /opt/polysignal/app /opt/polysignal/runs /opt/polysignal/logs
```

missing `.env`:

```bash
ls -l /opt/polysignal/.env
sudo install -o polysignal -g polysignal -m 600 /dev/null /opt/polysignal/.env
```

API key missing:

```bash
grep -E "API_KEY|TOKEN" /opt/polysignal/.env
```

Do not paste key values into logs or tickets.

Python venv path wrong:

```bash
ls -l /opt/polysignal/app/.venv/bin/python3
/opt/polysignal/app/.venv/bin/python3 --version
```

disk full:

```bash
df -h /opt/polysignal
du -sh /opt/polysignal/runs /opt/polysignal/logs
```

network error:

```bash
curl -I https://gamma-api.polymarket.com/markets
```

run already active:

```bash
pgrep -af "scripts/run_validation_loop.py"
systemctl status polysignal-validation.service
```

If a run is already active, do not start another long run. Wait, inspect logs, or stop the active service intentionally.

---

## K. Phase 7D Daily Report Automation

Phase 7D adds an offline daily report generator:

```text
scripts/generate_daily_report.py
```

It reads existing files from `/opt/polysignal/runs` and generates:

```text
/opt/polysignal/runs/daily_report.md
/opt/polysignal/runs/daily_report_summary.json
```

Dry run:

```bash
cd /opt/polysignal/app
source .venv/bin/activate
python3 scripts/generate_daily_report.py \
  --runs_dir /opt/polysignal/runs \
  --output_dir /opt/polysignal/runs \
  --latest_n 10 \
  --dry_run
```

Generate the report:

```bash
python3 scripts/generate_daily_report.py \
  --runs_dir /opt/polysignal/runs \
  --output_dir /opt/polysignal/runs \
  --latest_n 10
```

The script is offline-only:

- does not run `run_paper.py`
- does not call real APIs
- does not call real LLM providers
- does not modify config
- does not import trading execution modules
- does not place orders

The report includes daily activity, LLM activity, strategy validation snapshot, alpha candidates, avoid candidates, watchlist snapshot, API/WebSocket health, safety verification, and recommended next actions.

---

## L. What This Phase Does Not Do

Phase 7C does not:

- connect live trading
- handle private keys
- auto-place orders
- modify Risk Governor
- lower strategy thresholds
- turn alpha_score into a trading signal
- open public dashboard ports
- install service files into `/etc/systemd/system/`
- run `systemctl`
- start overnight collection

Long-running cloud collection remains read-only + paper-only.
