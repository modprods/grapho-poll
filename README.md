# grapho-poll

Michela Ledwidge

Simple poll UI for presenter working with graph databases

Configure a CYPHER query to pull multiple choice questions (and optional correct answers) from Neo4j and construct a simple poll UI. 

The admin page provides real-time responses 

## Supervisor

Tested on Debian

In the conf samples below, replace  ```<SOMETHING>``` with valid values for your environment

NOTE For supervisor replace space after "Basic " in OTEL_EXPORTER_OTLP_HEADERS with %20

```
cat >>> .env-supervisor
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-<ZONE>-1.grafana.net/otlp
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<TOKEN>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_SERVICE_NAME=grapho-poll
HOME=/home/<USER>
EOF
```

```
cat >> run-otel.sh
#!/bin/bash
set -a
source <HOME>/.env-supervisor
set +a
printf 'HEADERS=%q\n' "$OTEL_EXPORTER_OTLP_HEADERS" >&2
printf 'ENDPOINT=%q\n' "$OTEL_EXPORTER_OTLP_ENDPOINT" >&2
cd <PROJECT_HOME>
exec /home/<USER>/.local/bin/uv run opentelemetry-instrument uvicorn main:app --host 0.0.0.0 --port 5001
EOF
```

supervisor conf 
```
[program:grapho-poll]
autostart=true
user=<USER>
directory=<PROJECT_HOME>
command=<PROJECT_HOME>/run-otel.sh
priority=1
redirect_stderr=true
stopsignal=TERM
stopasgroup=true
killasgroup=true
stopwaitsecs=10
stdout_logfile=/var/log/grapho-poll/supervisor.log
stdout_logfile_maxbytes=10MB
```

## Telemetry

To enable telemetry in your production pipeline, set these in .env

{{{
MOD_ENV=<prod | staging | dev>
OTEL_TELEMETRY_ENABLED=<true | false>
}}}

Tested on Grafana Cloud as metrics, logs and traces

{{{
Loki: {service_name="grapho-poll"} |= "answer posted"
Mimir: answers_posted_total
}}}

