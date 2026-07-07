#!/usr/bin/env bash
# Phased load test against HOST env var (default http://127.0.0.1:5001)
set -euo pipefail

HOST="${HOST:-http://127.0.0.1:5001}"
LOCUSTFILE="${LOCUSTFILE:-locust/locustfile.py}"

run_phase() {
    local name="$1"
    local users="$2"
    local rate="$3"
    local duration="$4"
    echo "=== Phase: $name ($users users, ${rate}/s, $duration) ==="
    uv run locust -f "$LOCUSTFILE" --headless \
        -u "$users" -r "$rate" -t "$duration" \
        --host "$HOST" \
        --html "locust/report-${name}.html" \
        --csv "locust/report-${name}"
}

echo "Target: $HOST"
echo "Clearing poll responses before test..."
curl -fsS -X POST "${HOST}/admin/clear" -o /dev/null

run_phase smoke 10 2 2m
run_phase ramp 200 5 10m
run_phase peak 300 10 5m
run_phase soak 100 10 15m

echo "Clearing poll responses after test..."
curl -fsS -X POST "${HOST}/admin/clear" -o /dev/null
echo "Done. Reports in locust/report-*.html"
