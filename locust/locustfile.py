import json
import logging
import random
import time
from pathlib import Path

import websocket
from locust import HttpUser, between, events, task

log = logging.getLogger(__name__)

QUIZ_CACHE = Path(__file__).resolve().parent.parent / ".cypher_cache" / "quiz-3.json"


def load_quiz() -> list[dict[str, list[str] | str]]:
    records = json.loads(QUIZ_CACHE.read_text(encoding="utf-8"))
    quiz: list[dict[str, list[str] | str]] = []
    for record in records:
        choices = record.get("all_answers") or []
        if not choices:
            correct = record.get("correct_choice")
            other = record.get("other_choices") or []
            choices = [c for c in ([correct] if correct else []) + other if c]
        quiz.append({"question": record["question"], "choices": choices})
    return quiz


QUIZ = load_quiz()


def http_to_ws_url(host: str, path: str) -> str:
    if host.startswith("https://"):
        return "wss://" + host.removeprefix("https://") + path
    if host.startswith("http://"):
        return "ws://" + host.removeprefix("http://") + path
    return f"ws://{host}{path}"


def cookie_header(client) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def fire_ws_event(
    request_type: str,
    name: str,
    start_time: float,
    response_length: int,
    exception: BaseException | None = None,
) -> None:
    events.request.fire(
        request_type=request_type,
        name=name,
        response_time=(time.time() - start_time) * 1000,
        response_length=response_length,
        exception=exception,
    )


class PollAudienceUser(HttpUser):
    wait_time = between(2, 8)

    @task
    def complete_quiz(self) -> None:
        self.client.get("/", name="GET /")
        ws_url = http_to_ws_url(self.host, "/ws")
        headers = [f"Cookie: {cookie_header(self.client)}"]
        start_connect = time.time()
        try:
            ws = websocket.create_connection(ws_url, header=headers, timeout=30)
        except Exception as exc:
            fire_ws_event("WS", "WS connect /ws", start_connect, 0, exc)
            raise
        fire_ws_event("WS", "WS connect /ws", start_connect, 0)

        try:
            for question in QUIZ:
                payload = {
                    "question": question["question"],
                    "answer": random.choice(question["choices"]),
                    "HEADERS": {
                        "HX-Request": "true",
                        "HX-Current-URL": f"{self.host}/",
                    },
                }
                start_send = time.time()
                try:
                    ws.send(json.dumps(payload))
                    response = ws.recv()
                    fire_ws_event("WS", "WS answer", start_send, len(response))
                except Exception as exc:
                    fire_ws_event("WS", "WS answer", start_send, 0, exc)
                    raise
        finally:
            ws.close()
