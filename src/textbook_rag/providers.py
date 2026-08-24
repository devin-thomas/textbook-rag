from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Literal, Protocol

import httpx

from .retrieval import Evidence


ProviderName = Literal["nvidia", "ollama"]
ProviderChoice = Literal["auto", "nvidia", "ollama"]


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        provider: ProviderName,
        kind: str,
        message: str,
        *,
        retryable: bool,
        fallback_used: bool = False,
        initial_failure_kind: str | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.kind = kind
        self.retryable = retryable
        self.fallback_used = fallback_used
        self.initial_failure_kind = initial_failure_kind


class GroundingFailure(ProviderFailure):
    pass


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    status: Literal["ok", "insufficient_evidence"]
    answer: str
    cited_chunk_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    answer: GeneratedAnswer
    actual_provider: ProviderName
    fallback_used: bool
    initial_failure_kind: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderScope:
    sources: tuple[tuple[str, str], ...] = ()
    courses: tuple[tuple[str, str], ...] = ()


class GenerationProvider(Protocol):
    name: ProviderName

    def generate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
        scope: ProviderScope | None = None,
    ) -> GeneratedAnswer: ...


def _prompt(
    question: str,
    evidence: tuple[Evidence, ...],
    scope: ProviderScope | None = None,
) -> list[dict[str, str]]:
    scope = scope or ProviderScope()
    source_scope = (
        "\n".join(f"- {source_id}: {label}" for source_id, label in scope.sources)
        or "- all configured sources"
    )
    course_scope = (
        "\n".join(f"- {course_id}: {label}" for course_id, label in scope.courses)
        or "- all configured courses"
    )
    excerpts = "\n\n".join(
        f"CHUNK_ID: {item.chunk_id}\nSOURCE: {item.source_title}\n"
        f"PDF_PAGE: {item.physical_page}\nBOOK_LABEL: {item.page_label}\nTEXT:\n{item.excerpt}"
        for item in evidence
    )
    system = (
        "You answer only from the supplied textbook excerpts. Keep the answer concise. "
        "Every factual claim must be supported by a cited CHUNK_ID. If the excerpts are not "
        "enough, abstain. Put CHUNK_ID values only in the citations array; the answer text must "
        "not contain chunk IDs, bracketed citation markers, or internal retrieval metadata. "
        "Never invent a title, page, quote, or citation. Return only JSON: "
        '{"status":"ok|insufficient_evidence","answer":"...","citations":["exact chunk id"]}.'
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"SELECTED SOURCE SCOPE:\n{source_scope}\n\n"
                f"SELECTED COURSE SCOPE:\n{course_scope}\n\n"
                f"QUESTION:\n{question}\n\nEXCERPTS:\n{excerpts}"
            ),
        },
    ]


def _decode_answer(provider: ProviderName, content: object, evidence: tuple[Evidence, ...]) -> GeneratedAnswer:
    if not isinstance(content, str) or not content.strip():
        raise GroundingFailure(provider, "malformed_response", "provider returned no answer", retryable=True)
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        try:
            payload = json.loads(candidate[start : end + 1])
        except (json.JSONDecodeError, ValueError) as exc:
            raise GroundingFailure(
                provider, "malformed_response", "provider returned invalid JSON", retryable=True
            ) from exc
    if not isinstance(payload, dict):
        raise GroundingFailure(
            provider,
            "malformed_response",
            "provider JSON must be an object",
            retryable=True,
        )
    status = payload.get("status")
    answer = payload.get("answer")
    citations = payload.get("citations")
    if status not in {"ok", "insufficient_evidence"} or not isinstance(answer, str) or not isinstance(citations, list):
        raise GroundingFailure(
            provider, "malformed_response", "provider JSON does not match the answer schema", retryable=True
        )
    if not all(isinstance(item, str) for item in citations):
        raise GroundingFailure(provider, "invalid_citations", "citations must be chunk IDs", retryable=False)
    valid_ids = {item.chunk_id for item in evidence}
    invalid = set(citations) - valid_ids
    if invalid:
        raise GroundingFailure(
            provider,
            "invalid_citations",
            "provider cited evidence that was not retrieved",
            retryable=False,
        )
    if status == "ok" and (not answer.strip() or not citations):
        raise GroundingFailure(
            provider, "invalid_citations", "grounded answer requires at least one citation", retryable=False
        )
    if status == "insufficient_evidence" and citations:
        raise GroundingFailure(
            provider, "invalid_citations", "abstention cannot cite evidence", retryable=False
        )
    if status == "insufficient_evidence" and not answer.strip():
        raise GroundingFailure(
            provider,
            "malformed_response",
            "abstention requires an explanation",
            retryable=True,
        )
    return GeneratedAnswer(status=status, answer=answer.strip(), cited_chunk_ids=tuple(dict.fromkeys(citations)))


def _http_failure(provider: ProviderName, exc: Exception) -> ProviderFailure:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderFailure(provider, "timeout", f"{provider} request timed out", retryable=True)
    if isinstance(exc, httpx.NetworkError):
        return ProviderFailure(provider, "connection", f"{provider} is unreachable", retryable=True)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            kind = "authentication"
        elif status == 429:
            kind = "rate_limit"
        elif status >= 500:
            kind = "provider_5xx"
        else:
            kind = "request_rejected"
        return ProviderFailure(
            provider,
            kind,
            f"{provider} returned HTTP {status}",
            retryable=kind != "request_rejected",
        )
    return ProviderFailure(provider, "malformed_response", f"{provider} returned an invalid response", retryable=True)


class NvidiaProvider:
    name: ProviderName = "nvidia"

    def __init__(self, base_url: str, model: str, api_key: str | None, *, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = client

    def generate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
        scope: ProviderScope | None = None,
    ) -> GeneratedAnswer:
        if not self.api_key:
            raise ProviderFailure("nvidia", "authentication", "NVIDIA_API_KEY is not configured", retryable=True)
        client = self._client or httpx.Client(timeout=90.0)
        close_client = self._client is None
        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": _prompt(question, evidence, scope),
                    "temperature": 0.1,
                    "max_tokens": 900,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise _http_failure("nvidia", exc) from exc
        finally:
            if close_client:
                client.close()
        return _decode_answer("nvidia", content, evidence)


class OllamaProvider:
    name: ProviderName = "ollama"

    def __init__(self, base_url: str, model: str, *, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client

    def generate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
        scope: ProviderScope | None = None,
    ) -> GeneratedAnswer:
        client = self._client or httpx.Client(timeout=180.0)
        close_client = self._client is None
        try:
            response = client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": _prompt(question, evidence, scope),
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise _http_failure("ollama", exc) from exc
        finally:
            if close_client:
                client.close()
        return _decode_answer("ollama", content, evidence)


class ProviderRouter:
    def __init__(self, nvidia: GenerationProvider, ollama: GenerationProvider):
        self.providers: dict[ProviderName, GenerationProvider] = {
            "nvidia": nvidia,
            "ollama": ollama,
        }

    def generate(
        self,
        choice: ProviderChoice,
        question: str,
        evidence: tuple[Evidence, ...],
        scope: ProviderScope | None = None,
    ) -> ProviderOutcome:
        if choice != "auto":
            answer = self.providers[choice].generate(question, evidence, scope)
            return ProviderOutcome(answer, choice, False)
        try:
            answer = self.providers["nvidia"].generate(question, evidence, scope)
            return ProviderOutcome(answer, "nvidia", False)
        except ProviderFailure as exc:
            if not exc.retryable:
                raise
            try:
                answer = self.providers["ollama"].generate(question, evidence, scope)
            except ProviderFailure as fallback_exc:
                fallback_exc.fallback_used = True
                fallback_exc.initial_failure_kind = exc.kind
                raise
            return ProviderOutcome(answer, "ollama", True, exc.kind)
