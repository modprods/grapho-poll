import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fasthtml.common import *
from monsterui.franken import Button, Card, CardBody, CardHeader, Container
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

WS_PING_INTERVAL = 15  # seconds
DB_FILE = "data/poll.db"
BRAND_IMAGE_URL = "https://docs.grapho.app/img/graphobymod-black.png"
NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
NEO4J_USER = os.getenv("NEO4J_USER", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
QUIZ_CYPHER_QUERY = os.getenv("QUIZ_CYPHER_QUERY", "").strip()
QUIZ_CACHED_QUERY = os.getenv("QUIZ_CACHED_QUERY", "").strip()

quiz_name: str = ""
quiz_questions: list[dict[str, Any]] = []


class PollResponse:
    question: str
    answer: str
    session_id: str
    datetime: str


def record_to_dict(record: dict[str, Any]) -> dict[str, Any]:
    lookup = record["_fieldLookup"]
    fields = record["_fields"]
    return {key: fields[idx] for key, idx in lookup.items()}


def parse_quiz_records(raw: str | list) -> list[dict[str, Any]]:
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, list):
        return []
    if parsed and "_fieldLookup" in parsed[0]:
        return [record_to_dict(r) for r in parsed]
    return parsed


def load_quiz_from_cache(path: str) -> list[dict[str, Any]] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return parse_quiz_records(json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "QUIZ_CACHED_QUERY %r is not valid JSON (%s); falling back to Neo4j",
            path,
            exc,
        )
        return None


def save_quiz_to_cache(path: str, records: list[dict[str, Any]]) -> None:
    cache_dir = os.path.dirname(path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("Saved %d questions to %s", len(records), path)


def question_choices(record: dict[str, Any]) -> list[str]:
    if record.get("all_answers"):
        return [answer for answer in record["all_answers"] if answer]
    choices: list[str] = []
    correct = record.get("correct_choice")
    if correct:
        choices.append(correct)
    for option in record.get("other_choices") or []:
        if option and option not in choices:
            choices.append(option)
    return choices


async def fetch_quiz_from_neo4j() -> list[dict[str, Any]]:
    if not QUIZ_CYPHER_QUERY:
        log.error("QUIZ_CYPHER_QUERY is not set")
        return []
    if not NEO4J_URI:
        log.error("NEO4J_URI is not set")
        return []
    try:
        async with AsyncGraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
        ) as driver:
            async with driver.session(database=NEO4J_DATABASE) as session:
                result = await session.run(QUIZ_CYPHER_QUERY)
                return await result.data()
    except Neo4jError as exc:
        log.error("Neo4j query failed: %s", exc)
        return []


async def load_quiz_data() -> None:
    global quiz_name, quiz_questions
    if QUIZ_CACHED_QUERY:
        cached = load_quiz_from_cache(QUIZ_CACHED_QUERY)
        if cached is not None:
            quiz_questions = cached
            log.info("Loaded %d questions from %s", len(quiz_questions), QUIZ_CACHED_QUERY)
        else:
            quiz_questions = await fetch_quiz_from_neo4j()
            save_quiz_to_cache(QUIZ_CACHED_QUERY, quiz_questions)
            log.info("Loaded %d questions from Neo4j", len(quiz_questions))
    else:
        quiz_questions = await fetch_quiz_from_neo4j()
        log.info("Loaded %d questions from Neo4j", len(quiz_questions))
    quiz_name = quiz_questions[0]["quiz"] if quiz_questions else "Quiz"


def get_session_id(sess: dict[str, Any]) -> str:
    if "session_id" not in sess:
        sess["session_id"] = str(uuid.uuid4())
    return sess["session_id"]


def get_user_answers(session_id: str) -> dict[str, str]:
    rows = responses("session_id=?", (session_id,))
    return {row.question: row.answer for row in rows}


def save_answer(session_id: str, question: str, answer: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    responses.upsert(
        {"question": question, "session_id": session_id, "answer": answer, "datetime": now},
        pk=("session_id", "question"),
    )


def brand_image() -> FT:
    return Div(
        Img(src=BRAND_IMAGE_URL, alt="grapho by MOD"),
        cls="brand-image",
    )


def question_panel_id(index: int) -> str:
    return f"question-{index}"


def answer_button(question: str, answer: str, selected: bool) -> FT:
    cls = "answer-btn selected" if selected else "answer-btn"
    return Form(
        Input(type="hidden", name="question", value=question),
        Input(type="hidden", name="answer", value=answer),
        Button(answer, cls=cls, type="submit"),
        ws_send=True,
    )


def question_panel(index: int, record: dict[str, Any], selected_answers: dict[str, str]) -> FT:
    question = record["question"]
    buttons = [
        answer_button(question, choice, selected_answers.get(question) == choice)
        for choice in question_choices(record)
    ]
    return Card(
        id=question_panel_id(index),
        cls="question-panel",
    )(
        CardHeader(H3(question)),
        CardBody(Div(*buttons, cls="answer-buttons")),
    )


def compute_answer_stats(
    choices: list[str],
    correct: str,
    answers: list[str],
) -> list[dict[str, Any]]:
    total = len(answers)
    counts: dict[str, int] = {}
    for answer in answers:
        counts[answer] = counts.get(answer, 0) + 1
    stats = [
        {
            "answer": choice,
            "count": counts.get(choice, 0),
            "percentage": round(counts.get(choice, 0) / total * 100) if total else 0,
            "correct": choice == correct,
            "highlight": None,
        }
        for choice in choices
    ]
    if not answers:
        return stats
    max_count = max(s["count"] for s in stats)
    if max_count == 0:
        return stats
    leaders = {s["answer"] for s in stats if s["count"] == max_count}
    leader = next(choice for choice in choices if choice in leaders)
    highlight = "green" if leader == correct else "red"
    for stat in stats:
        if stat["answer"] == leader:
            stat["highlight"] = highlight
    return stats


def answer_stats(record: dict[str, Any]) -> list[dict[str, Any]]:
    question = record["question"]
    answers = [row.answer for row in responses("question=?", (question,))]
    return compute_answer_stats(
        question_choices(record),
        record.get("correct_choice") or "",
        answers,
    )


def clear_all_responses() -> None:
    responses.delete_where()


def stat_row_class(highlight: str | None) -> str:
    if highlight == "green":
        return "stats-row stats-row--top stats-row--correct"
    if highlight == "red":
        return "stats-row stats-row--top stats-row--wrong"
    return "stats-row"


def admin_question_panel(record: dict[str, Any]) -> FT:
    stats = answer_stats(record)
    rows = [
        Tr(
            Td(stat["answer"]),
            Td(f"{stat['percentage']}%"),
            cls=stat_row_class(stat["highlight"]),
        )
        for stat in stats
    ]
    return Card(cls="question-panel")(
        CardHeader(H3(record["question"])),
        CardBody(
            Table(
                Thead(Tr(Th("Answer"), Th("%"))),
                Tbody(*rows),
                cls="stats-table",
            ),
        ),
    )


def admin_page() -> FT:
    panels = [admin_question_panel(record) for record in quiz_questions]
    return Titled(
        f"{quiz_name} — Results",
        Container(
            P(A("← Poll", href="/"), cls="admin-nav"),
            *panels,
            Div(
                Form(method="post", action="/admin/clear")(
                    Button("Clear all responses", cls="clear-btn", type="submit"),
                ),
                cls="admin-actions",
            ),
        ),
    )


poll_styles = Style("""
main.container:has(.brand-image) {
    display: flex;
    flex-direction: column;
}
.brand-image {
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 2rem;
    order: -1;
}
.brand-image img {
    max-width: min(100%, 480px);
    height: auto;
}
.question-panel { margin-bottom: 1.5rem; }
.answer-buttons { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.answer-btn.selected {
    background: var(--pico-primary, #0172ad);
    color: var(--pico-primary-inverse, #fff);
    border-color: var(--pico-primary, #0172ad);
}
@media (prefers-color-scheme: light) {
    .answer-buttons .uk-btn.answer-btn {
        background-color: #f6f8fa;
        color: #24292f;
        border: 2px solid #d0d7de;
    }
    .answer-buttons .uk-btn.answer-btn.selected {
        background-color: #0969da;
        color: #ffffff;
        border-color: #0550ae;
        box-shadow: inset 0 0 0 1px #0550ae;
        font-weight: 600;
    }
}
:root[data-theme="light"] .answer-buttons .uk-btn.answer-btn {
    background-color: #f6f8fa;
    color: #24292f;
    border: 2px solid #d0d7de;
}
:root[data-theme="light"] .answer-buttons .uk-btn.answer-btn.selected {
    background-color: #0969da;
    color: #ffffff;
    border-color: #0550ae;
    box-shadow: inset 0 0 0 1px #0550ae;
    font-weight: 600;
}
.stats-row--top.stats-row--correct td { background: #e8f5e9; }
.stats-row--top.stats-row--wrong td { background: #ffebee; }
@media (prefers-color-scheme: dark) {
    .stats-row--top.stats-row--correct td {
        background: #14532d;
        box-shadow: inset 3px 0 0 #4ade80;
    }
    .stats-row--top.stats-row--wrong td {
        background: #7f1d1d;
        box-shadow: inset 3px 0 0 #f87171;
    }
}
:root[data-theme="dark"] .stats-row--top.stats-row--correct td {
    background: #14532d;
    box-shadow: inset 3px 0 0 #4ade80;
}
:root[data-theme="dark"] .stats-row--top.stats-row--wrong td {
    background: #7f1d1d;
    box-shadow: inset 3px 0 0 #f87171;
}
.admin-nav { margin-bottom: 1.5rem; }
.admin-actions { margin-top: 2rem; }
.stats-table { width: 100%; }
""")


async def startup() -> None:
    os.makedirs("data", exist_ok=True)
    await load_quiz_data()


os.makedirs("data", exist_ok=True)

app, rt = fast_app(
    exts="ws",
    hdrs=(poll_styles,),
    on_startup=[startup],
)

db = database(DB_FILE)
responses = db.create(PollResponse, pk=("session_id", "question"), transform=True)
PollResponse = responses.dataclass()


@rt("/")
async def index(sess):
    session_id = get_session_id(sess)
    selected = get_user_answers(session_id)
    panels = [
        question_panel(i, record, selected)
        for i, record in enumerate(quiz_questions)
    ]
    return Titled(
        quiz_name,
        brand_image(),
        Container(
            Div(hx_ext="ws", ws_connect="/ws")(*panels),
        ),
    )


@app.ws("/ws")
async def ws(question: str, answer: str, sess):
    session_id = get_session_id(sess)
    save_answer(session_id, question, answer)
    log.info("session=%s question=%r answer=%r", session_id, question, answer)
    selected = get_user_answers(session_id)
    for i, record in enumerate(quiz_questions):
        if record["question"] == question:
            return question_panel(i, record, selected)
    return ""


@rt("/admin")
async def admin():
    return admin_page()


@rt("/admin/clear", methods=["POST"])
async def admin_clear():
    clear_all_responses()
    log.info("Cleared all poll responses")
    return RedirectResponse("/admin", status_code=303)


serve()
