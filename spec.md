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

## Constraints

- Do NOT use `requests` library — use `httpx`
- Keep everything in `main.py` for now (no separate modules beyond tests)

