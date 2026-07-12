# grapho-poll

Michela Ledwidge

Simple poll UI for presenter working with graph databases

The admin page provides real-time responses and the means to clear the results.

## Poll data

Configure a CYPHER query to pull multiple choice questions (and optional correct answers) from Neo4j and construct a simple poll UI. 

The app expects data returned in a specific format but it is up to you how your database schema is structured.

In this case, the graph contains node labels Quiz, Question, Answer

e.g.

```cypher
MATCH (z:Quiz {slug:'quiz-3'})
WITH z
MATCH (z)-[:CONTAINS]->(q:Question)-[:CONTAINS]->(a:Answer)
WITH z, q, a ORDER BY a.slug
WITH z, q,
     COLLECT(CASE WHEN a.correct = true THEN a.name END) AS correct_answers,
     COLLECT(a.name) AS all_answers
RETURN z.name AS quiz,
       q.text AS question,
       correct_answers[0] AS correct_choice,
       all_answers
```

returning data in this format

| quiz | question | correct_choice | all_answers |
|------|----------|----------------|-------------|
| Avian Influenza Quiz | What animal can catch avian influenza? | All of the above | ["Humans", "Birds", "Seals", "All of the above"] |
| Avian Influenza Quiz | What do you collect on a swab to test for avian influenza? | Poo | ["Blood", "Skin", "Poo", "Feathers"] |
| Avian Influenza Quiz | What should you record on the sample bag? | Date, location, GPS and name of Ranger group | ["The name of your favourite NAQS vet", "Date, location, GPS and name of Ranger group", "Weather conditions at the time of sampling", "Distance from the ranger base to sampling location"] |


## Supervisor

Tested on Debian

In the conf samples below, replace  ```<SOMETHING>``` with valid values for your environment

### Telemetry

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

Supervisor runs the app via this shell script

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

