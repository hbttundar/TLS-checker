# TLS Checker Telegram Bot

Monitor a TLSContact (visa appointment) portal and broadcast Telegram notifications when appointment slots appear. Built with a clean Ports & Adapters design, resilient backoff / rate limiting, and a headless Chromium Selenium session.

## Features

- Periodic page refresh with adaptive rate limiting + jitter
- Circuit breaker with exponential backoff & cooldown on CAPTCHA / blocks
- CAPTCHA / temporary block detection (patterns configurable)
- Telegram commands: /start, /subscribe (/sub), /unsubscribe (/unsub), /status
- File or in‑memory subscriber store (thread‑safe JSON persistence)
- Headless Chromium with stealth options & reusable profile directory
- Configurable via environment variables (.env for non‑production)
- High test coverage (>=90%) enforced in CI (GitHub Actions)
- Optional Prometheus metrics endpoint (if ENABLE_METRICS + METRICS_PORT)
- Docker & docker‑compose ready; sample systemd unit file included

## Architecture Overview

The code follows a small hexagonal (Ports & Adapters) layout:

Ports (protocols) in `ports/`:

- `TLSChecker` (page login + refresh + slot detection)
- `Notifier` (send messages to chat IDs)
- `SubscriberStore` (persist/manage subscriber IDs)

Adapters in `adapters/` implement these ports (Selenium checker, Telegram notifier, file store, Chrome driver factory). The `services/` layer provides orchestration:

- `MonitorService`: background thread that schedules checks, applies rate limiting / breaker logic, and broadcasts transitions
- `limits`: `RateLimiter` & `CircuitBreaker` utilities
- `tls_checker_selenium`: Selenium implementation with classification heuristics & cached last status

`bot.py` wires everything: loads config, creates driver & checker, starts the monitor, and runs the Telegram application (unless OFFLINE mode is enabled).

## Status Lifecycle

Internal statuses roughly include: NO_SLOTS, MAYBE_SLOTS (positive), CAPTCHA (cooldown), BLOCKED (backoff), ERROR. Transitions drive notifications so subscribers only receive meaningful changes (e.g., from NO_SLOTS -> MAYBE_SLOTS).

## Quick Start (Local)

```bash
# 1. Clone and enter
git clone <your-fork-url> tls-checker
cd tls-checker

# 2. Create & edit .env
cp .env.example .env  # (create one; see Environment Variables)

# Required at minimum:
echo TELEGRAM_TOKEN=123456:ABCDEF >> .env

# 3. Install deps (Python 3.11+)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Run
python bot.py
```

### Offline Demo Mode

Set `OFFLINE=true` to skip Telegram network calls and use a dummy driver; process exits after a short demo window.

```bash
OFFLINE=true python bot.py
```

### Fake Driver Mode

Set `FAKE_DRIVER=true` to bypass real Chromium/Selenium while still exercising Telegram integration (uses static page source).

## Docker

Build & run with local bind-mounted profile and data:

```bash
docker build -t tlschecker .
# Supply TELEGRAM_TOKEN via env or --env-file
docker run --rm -it \
  -e TELEGRAM_TOKEN=123456:ABCDEF \
  -v $(pwd)/data:/data \
  -v $(pwd)/chrome_profile:/app/chrome_profile \
  tlschecker
```

### docker-compose

```bash
docker compose up --build -d
```
Ensure `.env` contains at least `TELEGRAM_TOKEN`.

## Systemd (Optional)

A sample unit file `systemd-tlschecker.service` is provided. Copy it to `/etc/systemd/system/`, adjust `WorkingDirectory` & environment, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now systemd-tlschecker.service
```

## Environment Variables

Key variables (see `config.py` for defaults and full list):

- TELEGRAM_TOKEN (required) Telegram bot token
- TLS_LOGIN_URL Base login URL (default TLSContact DE -> IR)
- CHECK_INTERVAL Base seconds between checks (default 300)
- MIN_CHECK_INTERVAL / MAX_CHECK_INTERVAL Bounds for adaptive limiter (180 / 420)
- JITTER_RATIO Fractional jitter (0.20)
- NEGATIVE_PATTERNS Semi‑colon or comma separated strings indicating no slots
- CAPTCHA_MARKERS / BLOCK_MARKERS Patterns indicating CAPTCHA or temporary block
- HEADLESS true|false (Chromium headless)
- USER_DATA_DIR Chrome profile directory (persist session)
- REMOTE_DEBUG_PORT Optional remote debugging port
- START_MONITOR_AFTER_LOGIN true|false (attempt ensure_logged_in first)
- SUBSCRIBERS_FILE Path to JSON store (default subscribers.json)
- SUBSCRIBER_BACKEND file|memory
- ERROR_BACKOFF_BASE / ERROR_BACKOFF_MAX Backoff (30 / 600)
- COOLDOWN_ON_CAPTCHA Seconds to pause after CAPTCHA (1800)
- FAILURE_THRESHOLD Consecutive failures threshold (5)
- WHITELIST_USERNAMES Semicolon/comma separated allowed usernames (optional)
- LOG_LEVEL INFO|DEBUG|...
- LOG_FORMAT text|json
- ENABLE_STATUS_COMMAND true|false
- ENABLE_METRICS true|false (needs METRICS_PORT)
- METRICS_PORT Integer port to expose Prometheus metrics
- OFFLINE true|false (development only) – no Telegram network, dummy monitor run
- FAKE_DRIVER true|false Use trivial in‑process fake driver (testing)

## Telegram Commands

- /start Greeting
- /subscribe or /sub Add current chat ID
- /unsubscribe or /unsub Remove current chat ID
- /status (if enabled) Operational snapshot & breaker status

## Testing

Run the (fast) pytest suite with coverage threshold enforced:

```bash
pytest -q --cov=. --cov-report=term-missing:skip-covered --cov-fail-under=90
```

## CI

GitHub Actions workflow `CI` runs Ruff lint + a Python (3.11–3.13) test matrix with coverage gating. Add badges (replace `<USER>` / `<REPO>`):


```text
[![CI](https://github.com/<USER>/<REPO>/actions/workflows/ci.yml/badge.svg)](https://github.com/<USER>/<REPO>/actions/workflows/ci.yml)
```

## Metrics (Optional)

If `ENABLE_METRICS=true` and `METRICS_PORT` set, a simple Prometheus HTTP server can be started (implementation stub / extend as needed) to expose internal counters / gauges.

## Design Notes

- Ports & Adapters keep Selenium & Telegram swap‑able
- RateLimiter adds jitter to avoid synchronized request bursts
- CircuitBreaker prevents hammering when blocked / failing
- Stateless command handlers keep `bot.py` orchestration thin (future extraction possible)
- Threaded monitor keeps Telegram event loop responsive

## Roadmap Ideas

- Extract command handlers into dedicated module
- Add Bandit / pip‑audit / CodeQL security scanning
- Implement metrics server & richer status caching
- Add RedisSubscriberStore option
- Graceful driver restart on fatal Chromium errors

## License

Add your chosen license (MIT, Apache 2.0, etc.) – currently unspecified.

---
Contributions & suggestions welcome. Stay lawful: ensure site monitoring complies with target site's terms of service.
