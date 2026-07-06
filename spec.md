# grapho-poll — Cursor Spec

## Context

FastHTML app managed by uv. Pulls multiple questions and answers from a Neo4j db via a CYPHER query string in .env, renders a tile grid of thumbnail buttons for each possible answer. Pressing a button sends the answer as a websocket message

Stack: python-fasthtml, httpx, websockets, pytest. Python >=3.12. Managed by uv.

Reference repos for style conventions:
- https://github.com/modprods/mca-mo-mobile (project structure, pyproject.toml, main.py pattern)

## Files

```
moreoptimism/
├── main.py              # FastHTML app entry point (update)
├── pyproject.toml       # uv project config (update)
├── .python-version      # pin to 3.12 
├── .cursorrules         # project conventions 
├── README.md            # quickstart docs
└── tests/
    └── test_images.py   # pytest tests (update)
```

## pyproject.toml

```toml
[project]
name = "grapho-poll"
version = "0.1.0"
description = "Audience polling tool backed by graph database"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "python-fasthtml>=0.12.50",
    "httpx>=0.27",
    "websockets>=13.0",
    "monsterui>=1.0.45",
    "python-dotenv>=1.2.2"
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

## main.py

### Environment variables

Update .env if these do not exist.

```
QUIZ_CYPHER_QUERY="
MATCH (z:Quiz {slug:'quiz-3'}) 
WITH z
MATCH (z)-[:CONTAINS]->(q:Question)-[:CONTAINS]->(a:Answer)
WITH z, q, 
     COLLECT(CASE WHEN a.correct = true THEN a.name END) as correct_answers,
     COLLECT(CASE WHEN a.correct <> true OR a.correct IS NULL THEN a.name END) as other_options
RETURN z.name as quiz, 
       q.text as question, 
       correct_answers[0] as correct_choice,
       [option IN other_options WHERE option IS NOT NULL] as other_choices"

NEO4J_HOST
NEO4J_PORT
NEO4J_DATABASE
QUIZ_CACHED_QUERY=

If QUIZ_CACHED_QUERY references a local file that is valid JSON - use this as a cached database query response instead of a Neo4j database query

If the file is not valid JSON, print a warning and call the Neo4j database query

### Constants

```python

WS_PING_INTERVAL = 15  # seconds

```

### Feature 1: Populate questions from database

On app startup, fetch quiz data from QUIZ_CACHED_QUERY. If empty or not in .env then call  QUIZ_CYPHER_QUERY and parse response to populate the home page


- Home page has placeholder brand image followed by a panel for each question

  - For each question
    - Show a button for each answer with the text of the answer
    - Highlight button when pressed and send answer via websocket route
    - Save answers to a fastlite table with the following fields and access via dataclass
       - answer: str
       - session_id: str
       - datetime: datetime
  - Use cookies to create a session for each device - users can change their answer by returning to this page and pressing a different button

### Feature 2: Admin page to show saved poll results

- Admin page
  - For each question use the fastlite table
    - List answer, percentage of responses that gave this answer, and a green tick if this is the correct answer
  - Show a clear button to delete all responses

### Feature 3: CYPHER cache

This feature implements a CYPHER database query cache

Before running database query, if QUIZ_CACHED_QUERY .env is set to a valid JSON file, use this instead of a database query to Neo4j

If QUIZ_CACHED_QUERY .env is set and there is no valid JSON file, query Neo4j and save the response to this file. 

If QUIZ_CACHED_QUERY .env is not set, query the Neo4j database  

### Feature 4: Logging

Add error.log - log error if Neo4j database query fails

Add .env LOG_LEVEL = DEBUG

### Feature 5: OTel telemetry

Instrument the app to send telemetry to Grafana Cloud

* errors - e.g. database query error
* answer_post - e.g. answer posted from main page

Use the following instructions as a guide

With Grafana Cloud you can skip the collector entirely for now and send OTLP straight from the app. That's the "Quickstart" path, and it's the right call while you're getting your first signals flowing; you can slot a collector/Alloy in front later without touching app code. The Quickstart guide configures instrumentation to send OTLP data directly to the Grafana Cloud OTLP endpoint, without setting up a data pipeline with an OpenTelemetry Collector.

## 1. Grab your OTLP credentials

In the Grafana Cloud portal: launch your stack → **Connections → Add new connection → OpenTelemetry**. It generates the two things you need — a gateway endpoint and an API token. Grafana Cloud exposes a **single OTLP endpoint that auto-routes** metrics → Mimir, logs → Loki, traces → Tempo, so you don't wire up three backends yourself.

Set these as environment variables (the console gives you the exact values, including your zone and the base64 token):

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp-gateway-<zone>.grafana.net/otlp"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64(instanceID:token)>"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_RESOURCE_ATTRIBUTES="service.namespace=mod,deployment.environment=prod"
```

One gotcha the docs flag specifically for Python: if you use Python, replace "Basic " in your connection variables shell script with "Basic " — i.e. make sure the header value is literally `Basic <token>` with a single space, since some of their generated snippets double it up. `http/protobuf` is the protocol to use for direct-to-cloud; save gRPC for when you have a local collector.

## 2. Install

```bash
uv add opentelemetry-distro opentelemetry-exporter-otlp \
       opentelemetry-instrumentation-starlette \
       opentelemetry-instrumentation-httpx
```

## 3. The `mod_telemetry` module

This is the shared init we discussed — extended to cover logs and metrics, not just traces. It's what every app calls once at startup.

```python
# mod_telemetry/__init__.py
import logging
import os
from opentelemetry import metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

_meter = None

def init(service_name: str, version: str = "0.0.0"):
    global _meter
    resource = Resource.create({
        "service.name": service_name,
        "service.version": version,
    })

    # --- Logs: bridge stdlib logging -> OTLP -> Loki ---
    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter())
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    # --- Metrics: for custom counters like answers_posted ---
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(service_name)
    return _meter

def meter():
    return _meter
```

Note I'm using the `proto.http` exporters here, not `proto.grpc`, to match the `http/protobuf` protocol you're sending direct-to-cloud.

## 4. Error logs

The `LoggingHandler` above already routes anything through Python's stdlib `logging` out to Loki. So your error logs are just normal logging calls:

```python
import logging
log = logging.getLogger("grapho-poll")

try:
    result = do_the_thing()
except Exception:
    log.exception("answer submission failed")   # ERROR + stack trace -> Loki
```

`log.exception(...)` captures the traceback automatically. In Grafana you'll query these in Loki with something like `{service_name="grapho-poll"} | level="ERROR"`. If you also turn on Starlette auto-instrumentation (below), unhandled exceptions in request handlers get recorded on the trace span too, so you can jump from an error log to the exact failing request.

## 5. "Answers posted"

This is a business event, best modeled as a **counter** you increment each time an answer is posted. Aggregate count over time, rate per minute, breakdown by whatever attributes matter:

```python
import mod_telemetry
meter = mod_telemetry.init("grapho-poll", "0.0.1")

answers_posted = meter.create_counter(
    "answers.posted",
    unit="1",
    description="Number of answers posted",
)

# in your FastHTML route:
@rt("/answer")
async def post_answer(...):
    ...
    answers_posted.add(1, {"channel": "web", "session": session_id})
    log.info("answer posted", extra={"session": session_id})
```

The counter gives you the dashboardable metric (`answers.posted` → a time series in Mimir you can graph and alert on). The `log.info` line alongside it gives you the per-event record in Loki if you ever need to inspect individual posts rather than just the aggregate. Keep counter attributes low-cardinality — `channel`, `type`, `status` are fine; don't put user IDs or session IDs as metric attributes (they explode series count), which is exactly why the session goes in the log line instead.

## 6. Baseline auto-instrumentation (optional but cheap)

Wrap your run command and you also get request spans/traces for every FastHTML route for free, with no code changes:

```bash
OTEL_SERVICE_NAME=grapho-poll opentelemetry-instrument uvicorn app:app
```

If you go this route, drop the tracing setup from the module and let auto-instrumentation own it — your custom counter and logs still work alongside it since they share the same OTLP env vars.

## 7. Verify

In Grafana Cloud: **Explore** → pick the Loki data source and query your service for the error logs; pick the Mimir/Prometheus data source and search for `answers_posted_total` (the counter gets a `_total` suffix on the Prometheus side). Once both show up, you've got the full loop.

One thing worth deciding now rather than later: put `mod_telemetry.init()` behind an env check (`MOD_ENV`) so local dev doesn't ship telemetry to your Grafana Cloud quota — that free tier is generous but the load tests could chew through it fast if pointed at the cloud endpoint. That's also the natural seam where a local collector slots in later.

Want me to write the `mod_telemetry` module out as an actual file with the env-gating and a `noop` fallback baked in, so it's drop-in for the other apps?

### Feature 6: Real-time admin updates

Admin page listens to websocket for answers - display updates in real-time - no need to reload page

Admin page shows the number of answers per question in the right column

Change "%" to "% (of <count>)" e.g. "% (of 25)"

## Constraints

- Do NOT use `requests` library — use `httpx`
- Keep everything in `main.py` for now (no separate modules beyond tests)

