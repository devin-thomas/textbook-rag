from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
from html import escape
import json
from pathlib import Path
import re
import time
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urljoin

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8766/textbooks"
DEFAULT_REQUESTS_PER_MINUTE = 6.0
RETRYABLE_ERROR_KINDS = {
    "connection",
    "malformed_response",
    "provider_5xx",
    "rate_limit",
    "timeout",
}


class QuizInputError(ValueError):
    pass


class QuizApiError(RuntimeError):
    def __init__(self, status_code: int, payload: Mapping[str, object]):
        error = payload.get("error")
        details = error if isinstance(error, Mapping) else {}
        self.status_code = status_code
        self.code = str(details.get("code", "http_error"))
        self.kind = str(details.get("kind", ""))
        self.conversation_id = (
            str(details["conversation_id"])
            if details.get("conversation_id")
            else None
        )
        self.retryable = status_code == 429 or (
            status_code >= 500 and self.kind in RETRYABLE_ERROR_KINDS
        )
        self.attempts = 1
        message = str(details.get("message", f"Textbook Desk returned HTTP {status_code}"))
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QuizQuestion:
    id: str
    question: str
    course_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    select_all_that_apply: bool | None
    history_match_id: str | None = None
    history_fields_applied: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryHint:
    conversation_id: str
    question: str
    course_ids: tuple[str, ...]
    select_all_that_apply: bool


@dataclass(frozen=True, slots=True)
class QuizInput:
    title: str
    questions: tuple[QuizQuestion, ...]
    removed_duplicates: tuple[dict[str, str], ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def question_fingerprint(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def clean_question_text(value: object) -> str:
    if not isinstance(value, str):
        raise QuizInputError("each question must contain string question text")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if lines:
        lines[0] = re.sub(
            r"^(?:(?:question|q)\s*\d+\s*[:.)-]|\d+\s*[.)-]|[-*])\s*",
            "",
            lines[0],
            flags=re.IGNORECASE,
        )
    cleaned_lines: list[str] = []
    for line in lines:
        if line or (cleaned_lines and cleaned_lines[-1]):
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines).strip()
    if len(text) < 2:
        raise QuizInputError("question text must contain at least two characters")
    if len(text) > 4000:
        raise QuizInputError("question text exceeds Textbook Desk's 4000-character limit")
    return text


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        values: Iterable[object] = value.split(",")
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        raise QuizInputError(f"{field_name} must be a string or list of strings")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise QuizInputError(f"{field_name} must contain only strings")
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _optional_bool(value: object, field_name: str) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0"}:
            return False
    raise QuizInputError(f"{field_name} must be true or false")


def _question_id(value: object, question: str, index: int) -> str:
    if value is not None and str(value).strip():
        candidate = str(value).strip()
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", question.casefold()).strip("-")[:48]
        candidate = f"q-{index:03d}-{slug or 'question'}"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip("-") or f"q-{index:03d}"


def _clean_record(raw: object, index: int) -> QuizQuestion:
    if isinstance(raw, str):
        record: Mapping[str, object] = {"question": raw}
    elif isinstance(raw, Mapping):
        record = raw
    else:
        raise QuizInputError(f"question {index} must be a string or object")
    raw_text = record.get("question", record.get("text", record.get("prompt")))
    question = clean_question_text(raw_text)
    course_ids = _string_tuple(record.get("course_ids", record.get("course")), "course_ids")
    source_ids = _string_tuple(record.get("source_ids", record.get("source")), "source_ids")
    select_all = _optional_bool(
        record.get("select_all_that_apply", record.get("select_all")),
        "select_all_that_apply",
    )
    return QuizQuestion(
        id=_question_id(record.get("id"), question, index),
        question=question,
        course_ids=course_ids,
        source_ids=source_ids,
        select_all_that_apply=select_all,
    )


def _execution_fingerprint(question: QuizQuestion) -> str:
    payload = {
        "question": question_fingerprint(question.question),
        "course_ids": question.course_ids,
        "source_ids": question.source_ids,
        "select_all_that_apply": question.select_all_that_apply,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_quiz_input(path: Path) -> QuizInput:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            raw_questions = payload
            title = path.stem.replace("-", " ").replace("_", " ").title()
        elif isinstance(payload, Mapping):
            raw_questions = payload.get("questions")
            title = str(payload.get("title") or path.stem).strip()
        else:
            raise QuizInputError("JSON input must be a list or an object with a questions list")
        if not isinstance(raw_questions, list):
            raise QuizInputError("JSON input must contain a questions list")
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_questions = list(csv.DictReader(handle))
        title = path.stem.replace("-", " ").replace("_", " ").title()
    elif suffix in {".txt", ".md"}:
        raw_questions = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        title = path.stem.replace("-", " ").replace("_", " ").title()
    else:
        raise QuizInputError("input must be JSON, CSV, TXT, or Markdown")

    cleaned: list[QuizQuestion] = []
    removed: list[dict[str, str]] = []
    fingerprints: dict[str, str] = {}
    ids: set[str] = set()
    for index, raw in enumerate(raw_questions, 1):
        question = _clean_record(raw, index)
        fingerprint = _execution_fingerprint(question)
        if fingerprint in fingerprints:
            removed.append({"duplicate_id": question.id, "kept_id": fingerprints[fingerprint]})
            continue
        identifier = question.id
        suffix_index = 2
        while identifier in ids:
            identifier = f"{question.id}-{suffix_index}"
            suffix_index += 1
        question = replace(question, id=identifier)
        ids.add(identifier)
        fingerprints[fingerprint] = identifier
        cleaned.append(question)
    if not cleaned:
        raise QuizInputError("input contains no usable questions")
    return QuizInput(title=title or "Completed Quiz", questions=tuple(cleaned), removed_duplicates=tuple(removed))


def apply_history(
    questions: Sequence[QuizQuestion], history: Sequence[HistoryHint]
) -> tuple[QuizQuestion, ...]:
    latest_by_fingerprint: dict[str, HistoryHint] = {}
    for item in history:
        latest_by_fingerprint.setdefault(question_fingerprint(item.question), item)
    enriched: list[QuizQuestion] = []
    for question in questions:
        hint = latest_by_fingerprint.get(question_fingerprint(question.question))
        if hint is None:
            enriched.append(replace(question, select_all_that_apply=question.select_all_that_apply or False))
            continue
        applied: list[str] = []
        course_ids = question.course_ids
        select_all = question.select_all_that_apply
        if not course_ids and hint.course_ids:
            course_ids = hint.course_ids
            applied.append("course_ids")
        if select_all is None:
            select_all = hint.select_all_that_apply
            applied.append("select_all_that_apply")
        enriched.append(
            replace(
                question,
                course_ids=course_ids,
                select_all_that_apply=bool(select_all),
                history_match_id=hint.conversation_id,
                history_fields_applied=tuple(applied),
            )
        )
    return tuple(enriched)


class RequestRateLimiter:
    def __init__(
        self,
        requests_per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be greater than zero")
        self.minimum_interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self.minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()


class TextbookDeskQuizClient:
    def __init__(
        self,
        base_url: str,
        *,
        requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=180.0)
        self.rate_limiter = RequestRateLimiter(
            requests_per_minute, clock=clock, sleep=sleep
        )
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get_json(self, path: str) -> Mapping[str, object]:
        response = self.client.get(urljoin(self.base_url, path))
        try:
            payload = response.json()
        except ValueError as exc:
            raise QuizApiError(response.status_code, {"error": {"message": "Textbook Desk returned invalid JSON"}}) from exc
        if not isinstance(payload, Mapping):
            raise QuizApiError(response.status_code, {"error": {"message": "Textbook Desk returned a non-object response"}})
        if response.is_error:
            raise QuizApiError(response.status_code, payload)
        return payload

    def question_history(self) -> tuple[HistoryHint, ...]:
        payload = self._get_json("api/question-history")
        raw_history = payload.get("questions", [])
        if not isinstance(raw_history, list):
            raise QuizApiError(500, {"error": {"message": "question history has an invalid shape"}})
        result: list[HistoryHint] = []
        for item in raw_history:
            if not isinstance(item, Mapping) or not isinstance(item.get("question"), str):
                continue
            result.append(
                HistoryHint(
                    conversation_id=str(item.get("conversation_id", "")),
                    question=str(item["question"]),
                    course_ids=_string_tuple(item.get("course_ids"), "course_ids"),
                    select_all_that_apply=bool(item.get("select_all_that_apply", False)),
                )
            )
        return tuple(result)

    def answer(self, question: QuizQuestion, *, max_retries: int) -> tuple[dict[str, object], int]:
        request: dict[str, object] = {
            "question": question.question,
            "provider": "nvidia",
            "course_ids": list(question.course_ids),
            "source_ids": list(question.source_ids),
            "select_all_that_apply": bool(question.select_all_that_apply),
        }
        for attempt in range(1, max_retries + 2):
            self.rate_limiter.wait()
            try:
                response = self.client.post(urljoin(self.base_url, "api/query"), json=request)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise QuizApiError(response.status_code, {"error": {"message": "query returned a non-object response"}})
                if response.is_error:
                    raise QuizApiError(response.status_code, payload)
                if payload.get("status") == "ok" and payload.get("actual_provider") != "nvidia":
                    raise QuizApiError(502, {"error": {"message": "query was not answered by NVIDIA", "kind": "provider_mismatch"}})
                return payload, attempt
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                error = QuizApiError(503, {"error": {"message": str(exc), "kind": "connection"}})
            except ValueError as exc:
                error = QuizApiError(502, {"error": {"message": "query returned invalid JSON", "kind": "malformed_response"}})
            except QuizApiError as exc:
                error = exc
            if error.conversation_id:
                request["conversation_id"] = error.conversation_id
            if not error.retryable or attempt > max_retries:
                error.attempts = attempt
                raise error
            retry_delay = max(self.rate_limiter.minimum_interval, min(120.0, 15.0 * (2 ** (attempt - 1))))
            self._sleep(retry_delay)
        raise AssertionError("retry loop exhausted unexpectedly")


def _question_output(question: QuizQuestion) -> dict[str, object]:
    return {
        "id": question.id,
        "question": question.question,
        "course_ids": list(question.course_ids),
        "source_ids": list(question.source_ids),
        "select_all_that_apply": bool(question.select_all_that_apply),
        "history": {
            "matched_conversation_id": question.history_match_id,
            "fields_applied": list(question.history_fields_applied),
        },
    }


def _report_counts(items: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        "total": len(items),
        "completed": sum(item.get("run_status") == "completed" for item in items),
        "failed": sum(item.get("run_status") == "failed" for item in items),
        "answered": sum(
            item.get("run_status") == "completed"
            and isinstance(item.get("result"), Mapping)
            and item["result"].get("status") == "ok"
            for item in items
        ),
        "insufficient_evidence": sum(
            item.get("run_status") == "completed"
            and isinstance(item.get("result"), Mapping)
            and item["result"].get("status") == "insufficient_evidence"
            for item in items
        ),
    }


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _cata_answer_parts(answer: str) -> tuple[str, ...]:
    parts = re.split(r"(?:\r?\n|;\s*)", answer.strip())
    cleaned = tuple(
        re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", part).strip()
        for part in parts
        if re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", part).strip()
    )
    return cleaned or (answer.strip(),)


def render_quiz_html(report: Mapping[str, object], *, base_url: str) -> str:
    raw_items = report.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    cards: list[str] = []
    book_icon = '''<svg class="book-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 1 2.5 2.5z"/><path d="M6.5 7H9M15 7h2.5"/></svg>'''
    for number, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            continue
        question = escape(str(item.get("question", "")))
        result = item.get("result") if isinstance(item.get("result"), Mapping) else {}
        error = item.get("error") if isinstance(item.get("error"), Mapping) else {}
        status = str(result.get("status", item.get("run_status", "unknown")))
        status_label = {
            "ok": "Answered",
            "insufficient_evidence": "Insufficient evidence",
            "failed": "Failed",
        }.get(status, status.replace("_", " ").title())
        raw_answer = str(result.get("answer", error.get("message", "No answer was produced.")))
        is_cata = bool(item.get("select_all_that_apply", False))
        if is_cata and status == "ok":
            answer_parts = _cata_answer_parts(raw_answer)
            answer = (
                f'<div class="answer cata-answer"><strong>{len(answer_parts)} correct answers</strong>'
                f'<ul>{"".join(f"<li>{escape(part)}</li>" for part in answer_parts)}</ul></div>'
            )
        else:
            answer = f'<div class="answer">{escape(raw_answer)}</div>'
        raw_citations = result.get("citations", [])
        citation_links: list[str] = []
        if isinstance(raw_citations, list):
            for citation in raw_citations:
                if not isinstance(citation, Mapping):
                    continue
                pdf_url = str(citation.get("pdf_url", ""))
                href = escape(urljoin(base_url.rstrip("/") + "/", pdf_url), quote=True)
                label = escape(
                    f"{citation.get('source_title', 'Textbook')} - page {citation.get('page_label') or citation.get('physical_page', '?')}"
                )
                citation_links.append(f'<a href="{href}" target="_blank" rel="noreferrer">{label}</a>')
        citations = "".join(f'<li><span class="citation-icon">{book_icon}</span>{link}</li>' for link in citation_links)
        scope = ", ".join(str(value) for value in item.get("course_ids", []) if value) or "All courses"
        cards.append(
            f'''<article class="question-card" data-status="{escape(status, quote=True)}">
  <header><span class="number">{number:02d}</span><span class="status">{escape(status_label)}</span></header>
  <h2>{question}</h2>
  <p class="scope">{escape(scope)}</p>
  {answer}
  {f'<ol class="citations">{citations}</ol>' if citations else ''}
</article>'''
        )
    counts = report.get("counts") if isinstance(report.get("counts"), Mapping) else {}
    title = escape(str(report.get("title", "Completed Quiz")))
    generated_at = escape(str(report.get("completed_at", report.get("updated_at", ""))))
    return f'''<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="theme-color" content="#0d1512">
  <meta name="darkreader-lock">
  <link rel="icon" href="data:,">
  <title>{title} - Textbook Desk</title>
  <style>
    :root {{ --bg:#0d1512; --grid:rgba(201,245,212,.035); --surface:#121d18; --surface-raised:#18271f; --text:#eff7f0; --muted:#92a79a; --line:#293b31; --line-strong:#3a5042; --accent:#79d98d; --accent-soft:rgba(121,217,141,.12); --success:#82d8a6; --danger:#f08a83; color-scheme:dark; }}
    * {{ box-sizing:border-box; }}
    html {{ min-width:320px; background:var(--bg); }}
    body {{ margin:0; min-width:320px; min-height:100vh; color:var(--text); background-color:var(--bg); background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px),radial-gradient(circle at 26% 0%,rgba(121,217,141,.08),transparent 28rem); background-size:32px 32px,32px 32px,auto; font-family:Geist,'Segoe UI',sans-serif; font-synthesis:none; }}
    main {{ width:min(980px,calc(100% - 32px)); margin:0 auto; padding:48px 0 76px; }}
    .masthead {{ border-bottom:1px solid var(--line); padding:0 0 28px; margin-bottom:24px; }}
    .brandline {{ display:flex; align-items:center; gap:10px; color:var(--muted); font:600 .74rem 'IBM Plex Mono',Consolas,monospace; letter-spacing:.08em; text-transform:uppercase; }}
    .brand-mark {{ display:grid; place-items:center; width:34px; height:34px; border:1px solid rgba(121,217,141,.55); border-radius:8px; color:var(--accent); background:var(--accent-soft); }}
    .book-icon {{ width:18px; height:18px; fill:none; stroke:currentColor; stroke-linecap:round; stroke-linejoin:round; stroke-width:1.6; }}
    .eyebrow {{ color:var(--accent); font-weight:700; margin:0; }}
    h1 {{ color:var(--text); font-size:clamp(2.35rem,7vw,5.3rem); line-height:.95; letter-spacing:-.06em; margin:22px 0 0; max-width:850px; }}
    .meta {{ display:flex; gap:10px 22px; flex-wrap:wrap; color:var(--muted); font:500 .72rem 'IBM Plex Mono',Consolas,monospace; margin-top:22px; }}
    .grid {{ display:grid; gap:14px; }}
    .question-card {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:clamp(20px,4vw,30px); }}
    .question-card header {{ display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line); padding-bottom:12px; }}
    .number {{ color:var(--accent); font:500 1rem 'IBM Plex Mono',Consolas,monospace; }}
    .status {{ color:var(--success); font:600 .7rem 'IBM Plex Mono',Consolas,monospace; letter-spacing:.08em; text-transform:uppercase; }}
    [data-status='failed'] .status {{ color:var(--danger); }}
    h2 {{ color:var(--text); font-size:clamp(1.2rem,2.5vw,1.65rem); line-height:1.2; letter-spacing:-.03em; margin:20px 0 8px; }}
    .scope {{ color:var(--muted); font:500 .68rem 'IBM Plex Mono',Consolas,monospace; letter-spacing:.08em; text-transform:uppercase; margin:0 0 20px; }}
    .answer {{ white-space:pre-wrap; font-size:1rem; line-height:1.65; padding:15px 17px; border:1px solid var(--line); border-left:3px solid var(--accent); border-radius:7px; background:var(--surface-raised); }}
    .cata-answer strong {{ display:block; color:var(--accent); font:650 .72rem 'IBM Plex Mono',Consolas,monospace; letter-spacing:.08em; text-transform:uppercase; }}
    .cata-answer ul {{ margin:10px 0 0; padding-left:24px; }}
    .cata-answer li {{ margin:5px 0; padding-left:4px; }}
    .cata-answer li::marker {{ color:var(--accent); font-weight:700; }}
    .citations {{ margin:18px 0 0; padding:15px 0 0 4px; border-top:1px dashed var(--line); list-style:none; }}
    .citations li {{ display:flex; align-items:center; gap:8px; margin:8px 0; }}
    .citation-icon {{ color:var(--accent); display:inline-flex; }}
    .citation-icon .book-icon {{ width:15px; height:15px; }}
    a {{ color:var(--accent); text-underline-offset:3px; }}
    a:hover {{ color:var(--text); }}
    @media (max-width:600px) {{ main {{ width:min(100% - 20px,980px); padding-top:28px; }} .question-card {{ padding:20px 16px; }} .meta {{ gap:10px 18px; }} }}
  </style>
</head>
<body>
  <main>
    <section class="masthead">
      <div class="brandline"><span class="brand-mark">{book_icon}</span><span class="eyebrow">Textbook Desk / Quiz Mode</span></div>
      <h1>{title}</h1>
      <div class="meta"><span>{counts.get('answered', 0)} answered</span><span>{counts.get('insufficient_evidence', 0)} abstained</span><span>{counts.get('failed', 0)} failed</span><span>{generated_at}</span></div>
    </section>
    <section class="grid">{''.join(cards)}</section>
  </main>
</body>
</html>
'''


def run_quiz(
    quiz_input: QuizInput,
    *,
    client: TextbookDeskQuizClient,
    json_path: Path,
    html_path: Path,
    max_retries: int,
    resume: bool,
    use_history: bool,
) -> dict[str, object]:
    history = client.question_history() if use_history else ()
    questions = apply_history(quiz_input.questions, history)
    previous: dict[str, Mapping[str, object]] = {}
    started_at = _utc_now()
    if resume and json_path.is_file():
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        started_at = str(existing.get("started_at", started_at)) if isinstance(existing, Mapping) else started_at
        if isinstance(existing, Mapping) and isinstance(existing.get("items"), list):
            previous = {
                f"{item.get('id')}:{question_fingerprint(str(item.get('question', '')))}": item
                for item in existing["items"]
                if isinstance(item, Mapping) and item.get("run_status") == "completed"
            }
    items: list[dict[str, object]] = []
    report: dict[str, object] = {}
    for question in questions:
        resume_key = f"{question.id}:{question_fingerprint(question.question)}"
        if resume_key in previous:
            item = dict(previous[resume_key])
            item["resumed"] = True
        else:
            item = _question_output(question)
            item["started_at"] = _utc_now()
            try:
                result, attempts = client.answer(question, max_retries=max_retries)
                item.update(
                    run_status="completed",
                    attempts=attempts,
                    result=result,
                    completed_at=_utc_now(),
                )
            except QuizApiError as exc:
                item.update(
                    run_status="failed",
                    attempts=exc.attempts,
                    error={
                        "code": exc.code,
                        "kind": exc.kind,
                        "message": str(exc),
                        "status_code": exc.status_code,
                    },
                    completed_at=_utc_now(),
                )
        items.append(item)
        report = {
            "schema_version": 1,
            "title": quiz_input.title,
            "provider": "nvidia",
            "base_url": client.base_url.rstrip("/"),
            "started_at": started_at,
            "updated_at": _utc_now(),
            "completed_at": None,
            "history": {
                "enabled": use_history,
                "questions_loaded": len(history),
                "matches": sum(question.history_match_id is not None for question in questions),
                "fields_applied": sum(len(question.history_fields_applied) for question in questions),
            },
            "cleaning": {
                "input_questions": len(quiz_input.questions) + len(quiz_input.removed_duplicates),
                "unique_questions": len(quiz_input.questions),
                "removed_duplicates": list(quiz_input.removed_duplicates),
            },
            "counts": _report_counts(items),
            "items": items,
        }
        write_json_atomic(json_path, report)
    report["completed_at"] = _utc_now()
    report["updated_at"] = report["completed_at"]
    write_json_atomic(json_path, report)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_quiz_html(report, base_url=client.base_url), encoding="utf-8")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a rate-limited NVIDIA quiz through Textbook Desk")
    parser.add_argument("input", type=Path, help="JSON, CSV, TXT, or Markdown question file")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/generated/quiz"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--requests-per-minute", type=float, default=DEFAULT_REQUESTS_PER_MINUTE)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-history", action="store_true", help="Do not use exact matches from local question history")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be zero or greater")
    quiz_input = load_quiz_input(args.input.resolve())
    output_dir = args.output_dir.resolve()
    json_path = output_dir / "quiz-results.json"
    html_path = output_dir / "quiz-results.html"
    client = TextbookDeskQuizClient(
        args.base_url, requests_per_minute=args.requests_per_minute
    )
    try:
        report = run_quiz(
            quiz_input,
            client=client,
            json_path=json_path,
            html_path=html_path,
            max_retries=args.max_retries,
            resume=args.resume,
            use_history=not args.no_history,
        )
    finally:
        client.close()
    counts = report["counts"]
    print(f"Quiz complete: {counts['completed']} completed, {counts['failed']} failed")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
