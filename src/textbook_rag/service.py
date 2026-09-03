from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog
from .history import HistoryStore
from .providers import (
    ProviderChoice,
    ProviderFailure,
    ProviderOutcome,
    ProviderRouter,
    ProviderScope,
)
from .retrieval import HybridRetriever
from .embeddings import EmbeddingError


class ScopeValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QueryResult:
    status: str
    answer: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    provider_choice: ProviderChoice
    actual_provider: str | None
    fallback_used: bool
    initial_failure_kind: str | None
    retrieval_fallback_used: bool
    select_all_that_apply: bool
    citations: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]


class QueryService:
    def __init__(
        self,
        catalog: Catalog,
        retriever: HybridRetriever,
        providers: ProviderRouter,
        history: HistoryStore,
    ) -> None:
        self.catalog = catalog
        self.retriever = retriever
        self.providers = providers
        self.history = history

    def query(
        self,
        question: str,
        choice: ProviderChoice,
        *,
        source_ids: tuple[str, ...] = (),
        course_ids: tuple[str, ...] = (),
        conversation_id: str | None = None,
        select_all_that_apply: bool = False,
    ) -> QueryResult:
        known_sources = {source.id for source in self.catalog.sources}
        known_courses = {course.id for course in self.catalog.courses}
        if not set(source_ids) <= known_sources:
            raise ScopeValidationError("one or more source IDs are not configured")
        if not set(course_ids) <= known_courses:
            raise ScopeValidationError("one or more course IDs are not configured")
        requested_sources = set(source_ids)
        requested_courses = set(course_ids)
        effective_sources = tuple(
            source
            for source in self.catalog.sources
            if (not requested_sources or source.id in requested_sources)
            and (
                not requested_courses
                or bool(requested_courses.intersection(source.course_ids))
            )
        )
        effective_course_ids = course_ids or tuple(
            dict.fromkeys(
                course_id
                for source in effective_sources
                for course_id in source.course_ids
            )
        )
        conversation_id = self.history.ensure_conversation(conversation_id, question)
        user_message_id = self.history.append_user(
            conversation_id,
            question,
            choice,
            course_ids=effective_course_ids,
            select_all_that_apply=select_all_that_apply,
        )
        try:
            retrieval = self.retriever.retrieve(
                question,
                source_ids=source_ids,
                course_ids=course_ids,
                allow_semantic_fallback=choice in {"auto", "nvidia"},
            )
        except (EmbeddingError, RuntimeError):
            self.history.append_assistant(
                conversation_id,
                text="Textbook retrieval is temporarily unavailable.",
                choice=choice,
                status="retrieval_unavailable",
                evidence=(),
                outcome=None,
                retrieval_fallback_used=False,
            )
            raise
        evidence_dicts = tuple(item.to_dict() for item in retrieval.evidence)
        if retrieval.status == "insufficient_evidence":
            answer = "The selected textbooks do not contain enough information to answer that question."
            assistant_message_id = self.history.append_assistant(
                conversation_id,
                text=answer,
                choice=choice,
                status="insufficient_evidence",
                evidence=retrieval.evidence,
                outcome=None,
                retrieval_fallback_used=retrieval.semantic_fallback_used,
            )
            return QueryResult(
                status="insufficient_evidence",
                answer=answer,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                provider_choice=choice,
                actual_provider=None,
                fallback_used=False,
                initial_failure_kind=None,
                retrieval_fallback_used=retrieval.semantic_fallback_used,
                select_all_that_apply=select_all_that_apply,
                citations=(),
                evidence=evidence_dicts,
            )
        try:
            course_names = {course.id: course.name for course in self.catalog.courses}
            scope = ProviderScope(
                sources=tuple((source.id, source.title) for source in effective_sources),
                courses=tuple(
                    (course_id, course_names[course_id])
                    for course_id in effective_course_ids
                ),
                select_all_that_apply=select_all_that_apply,
            )
            outcome = self.providers.generate(choice, question, retrieval.evidence, scope)
        except ProviderFailure as exc:
            self.history.append_assistant(
                conversation_id,
                text=f"{exc.provider.title()} is temporarily unavailable for this question.",
                choice=choice,
                status="provider_unavailable",
                evidence=retrieval.evidence,
                outcome=None,
                failure=exc,
                retrieval_fallback_used=retrieval.semantic_fallback_used,
            )
            raise
        assistant_message_id = self.history.append_assistant(
            conversation_id,
            text=outcome.answer.answer,
            choice=choice,
            status=outcome.answer.status,
            evidence=retrieval.evidence,
            outcome=outcome,
            retrieval_fallback_used=retrieval.semantic_fallback_used,
        )
        evidence_by_id = {item.chunk_id: item for item in retrieval.evidence}
        citations = tuple(
            {
                "citation_index": citation_index,
                "chunk_id": chunk_id,
                "source_id": evidence_by_id[chunk_id].source_id,
                "source_title": evidence_by_id[chunk_id].source_title,
                "physical_page": evidence_by_id[chunk_id].physical_page,
                "page_label": evidence_by_id[chunk_id].page_label,
                "pdf_url": f"/textbooks/api/sources/{evidence_by_id[chunk_id].source_id}/pdf#page={evidence_by_id[chunk_id].physical_page}",
            }
            for citation_index, chunk_id in enumerate(outcome.answer.cited_chunk_ids, 1)
        )
        return QueryResult(
            status=outcome.answer.status,
            answer=outcome.answer.answer,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            provider_choice=choice,
            actual_provider=outcome.actual_provider,
            fallback_used=outcome.fallback_used,
            initial_failure_kind=outcome.initial_failure_kind,
            retrieval_fallback_used=retrieval.semantic_fallback_used,
            select_all_that_apply=select_all_that_apply,
            citations=citations,
            evidence=evidence_dicts,
        )
