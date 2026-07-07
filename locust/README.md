# Locust load tests for grapho-poll

Simulates audience members: each virtual user loads `/`, opens a WebSocket to `/ws`, and submits three answers (one per question).

Quiz data is read from [`.cypher_cache/quiz-3.json`](../.cypher_cache/quiz-3.json) at import time.

## Install (Locust worker / dev machine)

```bash
uv sync --extra load
```

## Pre-flight (production)

Before running against prod:

1. **Baseline** — note current `answers_posted_total` in Grafana (optional).
2. **Clear poll data** — `curl -X POST https://<prod-host>/admin/clear`
3. **Telemetry** — temporarily set `MOD_ENV=dev` on the app host to avoid Grafana quota burn during load; restore `MOD_ENV=prod` after.
4. **Network** — Locust workers must reach prod on port 5001 (or 443 behind ALB). Open security group egress/ingress as needed.
5. **Capacity** — single `uvicorn` process + SQLite; expect write contention at high concurrency.

## Local smoke test

Terminal 1 — start the app:

```bash
uv run python main.py
```

Terminal 2 — one user for 30 seconds:

```bash
uv run locust -f locust/locustfile.py --headless -u 1 -r 1 -t 30s --host http://127.0.0.1:5001
```

Expect zero failures. Open http://127.0.0.1:5001/admin — one response per question.

Clear: `curl -X POST http://127.0.0.1:5001/admin/clear`

## Production smoke test (AWS)

From a Locust worker with network access to prod:

```bash
uv run locust -f locust/locustfile.py --headless -u 1 -r 1 -t 30s --host https://<prod-host>
```

Verify `/admin` shows 1 response per question, then clear before the full swarm.

## Phased swarm (production)

| Phase | Users | Spawn rate | Duration |
|-------|-------|------------|----------|
| Smoke | 10 | 2/s | 2 min |
| Ramp | 200 | 5/s | 10 min |
| Peak | 300–500 | 10/s | 5 min |
| Soak | 100 | — | 15 min |

Headless example (ramp phase):

```bash
uv run locust -f locust/locustfile.py --headless -u 200 -r 5 -t 10m --host https://<prod-host>
```

Distributed (master + workers):

```bash
# Master
uv run locust -f locust/locustfile.py --master --expect-workers=4

# Each worker
uv run locust -f locust/locustfile.py --worker --master-host=<master-private-ip>
```

Or run all phases sequentially (set `HOST` to prod URL):

```bash
chmod +x locust/run-phases.sh
HOST=https://<prod-host> ./locust/run-phases.sh
```

Web UI: http://\<master\>:8089 — set host to prod URL, start swarm.

### Monitor during test

- **Locust UI** — failure rate, `GET /` p95, `WS answer` p95
- **Server** — CPU/memory, `/var/log/grapho-poll/supervisor.log`, `error.log`
- **Admin** — http://\<prod-host\>/admin updates in real time
- **Grafana** (if telemetry on) — `answers_posted_total`, Loki `{service_name="grapho-poll"} |= "answer posted"`

### Success criteria

| Check | Target |
|-------|--------|
| Failure rate | < 1% |
| `GET /` p95 | < 2s |
| `WS answer` p95 | < 1s |
| Admin page | Updates without refresh |
| Server | Stays up through soak |

## Post-test cleanup

```bash
curl -X POST https://<prod-host>/admin/clear
```

Restore `MOD_ENV=prod` if changed for the test. Record Locust stats and any bottlenecks (SQLite, CPU, WS failures).
