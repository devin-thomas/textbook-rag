from __future__ import annotations

import json
from pathlib import Path

import httpx

from textbook_rag.quiz import (
    HistoryHint,
    QuizInput,
    QuizQuestion,
    RequestRateLimiter,
    TextbookDeskQuizClient,
    apply_history,
    load_quiz_input,
    render_quiz_html,
    run_quiz,
)


def test_load_quiz_input_cleans_aliases_and_removes_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "title": "Review",
                "questions": [
                    "  Q1:  What is virtual   memory?  ",
                    {"text": "what is virtual memory?"},
                    {"prompt": "2) Select every process state.", "select_all": "yes"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = load_quiz_input(path)

    assert [item.question for item in result.questions] == [
        "What is virtual memory?",
        "Select every process state.",
    ]
    assert result.questions[1].select_all_that_apply is True
    assert result.removed_duplicates[0]["kept_id"] == result.questions[0].id


def test_same_question_with_different_scope_is_not_removed(tmp_path: Path) -> None:
    path = tmp_path / "scoped.json"
    path.write_text(
        json.dumps(
            [
                {"question": "Compare memory models.", "course_ids": ["COURSE-1"]},
                {"question": "Compare memory models.", "course_ids": ["COURSE-2"]},
            ]
        ),
        encoding="utf-8",
    )

    result = load_quiz_input(path)

    assert len(result.questions) == 2
    assert result.removed_duplicates == ()


def test_history_only_fills_omitted_question_metadata() -> None:
    questions = (
        QuizQuestion("q1", "What is virtual memory?", (), (), None),
        QuizQuestion("q2", "What is virtual memory?", ("EXPLICIT",), (), False),
    )
    history = (
        HistoryHint("conversation-1", "What is virtual memory?", ("COURSE-1",), True),
    )

    result = apply_history(questions, history)

    assert result[0].course_ids == ("COURSE-1",)
    assert result[0].select_all_that_apply is True
    assert result[0].history_fields_applied == ("course_ids", "select_all_that_apply")
    assert result[1].course_ids == ("EXPLICIT",)
    assert result[1].select_all_that_apply is False
    assert result[1].history_fields_applied == ()


def test_rate_limiter_spaces_request_starts() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RequestRateLimiter(6, clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    now[0] += 3
    limiter.wait()

    assert sleeps == [7.0]


def test_client_forces_nvidia_and_retries_rate_limit() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503,
                json={
                    "error": {
                        "code": "provider_unavailable",
                        "kind": "rate_limit",
                        "message": "nvidia returned HTTP 429",
                        "conversation_id": "conversation-1",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "answer": "A page fault loads the page.",
                "actual_provider": "nvidia",
                "citations": [],
            },
        )

    client = TextbookDeskQuizClient(
        "http://desk/textbooks",
        requests_per_minute=60,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )
    result, attempts = client.answer(
        QuizQuestion("q1", "What is virtual memory?", (), (), False),
        max_retries=2,
    )

    assert attempts == 2
    assert result["actual_provider"] == "nvidia"
    request_payloads = [json.loads(request.content) for request in requests]
    assert all(payload["provider"] == "nvidia" for payload in request_payloads)
    assert "conversation_id" not in request_payloads[0]
    assert request_payloads[1]["conversation_id"] == "conversation-1"
    assert sleeps == [15.0, 1.0]


def test_run_quiz_checkpoints_json_and_renders_safe_html(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("question-history"):
            return httpx.Response(
                200,
                json={
                    "questions": [
                        {
                            "conversation_id": "history-1",
                            "question": "What is virtual memory?",
                            "course_ids": ["COURSE-1"],
                            "select_all_that_apply": False,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "answer": "Pages are loaded <safely>.",
                "actual_provider": "nvidia",
                "citations": [
                    {
                        "source_title": "Book & Notes",
                        "page_label": "42",
                        "pdf_url": "/textbooks/api/sources/book/pdf#page=42",
                    }
                ],
            },
        )

    quiz_input = QuizInput(
        "Memory <Review>",
        (QuizQuestion("q1", "What is virtual memory?", (), (), None),),
        (),
    )
    client = TextbookDeskQuizClient(
        "http://desk/textbooks",
        requests_per_minute=60,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    json_path = tmp_path / "quiz-results.json"
    html_path = tmp_path / "quiz-results.html"

    report = run_quiz(
        quiz_input,
        client=client,
        json_path=json_path,
        html_path=html_path,
        max_retries=0,
        resume=False,
        use_history=True,
    )

    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")
    assert report["counts"]["completed"] == 1
    assert persisted["items"][0]["course_ids"] == ["COURSE-1"]
    assert "Memory &lt;Review&gt;" in html
    assert "Pages are loaded &lt;safely&gt;." in html
    assert 'href="http://desk/textbooks/api/sources/book/pdf#page=42"' in html


def test_render_quiz_html_handles_failure_without_executing_markup() -> None:
    html = render_quiz_html(
        {
            "title": "Quiz",
            "counts": {"answered": 0, "insufficient_evidence": 0, "failed": 1},
            "items": [
                {
                    "id": "q1",
                    "question": "<script>alert(1)</script>",
                    "course_ids": [],
                    "run_status": "failed",
                    "error": {"message": "bad <input>"},
                }
            ],
        },
        base_url="http://desk/textbooks",
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "bad &lt;input&gt;" in html


def test_render_quiz_html_formats_cata_answers_as_counted_bullets() -> None:
    html = render_quiz_html(
        {
            "title": "Quiz",
            "counts": {"answered": 1, "insufficient_evidence": 0, "failed": 0},
            "items": [
                {
                    "id": "q1",
                    "question": "Which choices apply?",
                    "course_ids": ["ITSE-1311"],
                    "select_all_that_apply": True,
                    "run_status": "completed",
                    "result": {
                        "status": "ok",
                        "answer": "1. First answer; 2. Second answer; 3. Third answer",
                    },
                }
            ],
        },
        base_url="http://desk/textbooks",
    )

    assert '<div class="answer cata-answer"><strong>3 correct answers</strong>' in html
    assert "<li>First answer</li>" in html
    assert "<li>Second answer</li>" in html
    assert "<li>Third answer</li>" in html
