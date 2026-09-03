from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from .catalog import Catalog
from .db import Database
from .embeddings import EmbeddingError, OllamaEmbeddingClient
from .history import HistoryNotFound, HistoryStore
from .providers import NvidiaProvider, OllamaProvider, ProviderFailure, ProviderRouter
from .retrieval import HybridRetriever
from .service import QueryService, ScopeValidationError
from .settings import Settings


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=4000)
    provider: Literal["auto", "nvidia", "ollama"] = "auto"
    course_ids: list[str] = Field(default_factory=list, max_length=8)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    conversation_id: str | None = Field(default=None, max_length=64)
    select_all_that_apply: bool = False

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("question must contain at least two non-whitespace characters")
        return value

@dataclass(slots=True)
class Runtime:
    settings: Settings
    catalog: Catalog
    database: Database
    embeddings: OllamaEmbeddingClient
    retriever: HybridRetriever
    history: HistoryStore
    providers: ProviderRouter
    service: QueryService


def create_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or Settings.from_env()
    catalog = Catalog.load(settings.catalog_path, settings.root)
    database = Database(settings.database_path)
    database.initialize(catalog)
    embeddings = OllamaEmbeddingClient(
        settings.ollama_base_url,
        settings.embedding_model,
        settings.embedding_dimension,
    )
    retriever = HybridRetriever(
        database,
        embeddings,
        semantic_candidates=settings.retrieval_semantic_candidates,
        fts_candidates=settings.retrieval_fts_candidates,
        final_chunks=settings.retrieval_final_chunks,
        min_semantic_score=settings.retrieval_min_semantic_score,
    )
    history = HistoryStore(database)
    providers = ProviderRouter(
        NvidiaProvider(settings.nvidia_base_url, settings.nvidia_model, settings.nvidia_api_key),
        OllamaProvider(settings.ollama_base_url, settings.ollama_generation_model),
    )
    service = QueryService(catalog, retriever, providers, history)
    return Runtime(settings, catalog, database, embeddings, retriever, history, providers, service)


def _api_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, object]:
        configured_source_ids = tuple(source.id for source in runtime.catalog.sources)
        placeholders = ",".join("?" for _ in configured_source_ids)
        with runtime.database.connect() as connection:
            source_count = len(configured_source_ids)
            ready_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM sources WHERE status='ready' AND id IN ({placeholders})",
                    configured_source_ids,
                ).fetchone()[0]
            )
            chunk_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM chunks c JOIN sources s ON s.id=c.source_id "
                    f"WHERE s.status='ready' AND s.id IN ({placeholders})",
                    configured_source_ids,
                ).fetchone()[0]
            )
            connection.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "app": {"name": "Textbook Desk", "version": "0.1.0"},
            "database": {"status": "ok"},
            "index": {
                "status": "ready" if ready_count == source_count and source_count else "incomplete",
                "ready_sources": ready_count,
                "configured_sources": source_count,
                "chunks": chunk_count,
            },
            "ollama": {
                "configured": True,
                "base_url": runtime.settings.ollama_base_url,
                "embedding_model": runtime.settings.embedding_model,
                "generation_model": runtime.settings.ollama_generation_model,
            },
            "nvidia": {
                "configured": bool(runtime.settings.nvidia_api_key),
                "model": runtime.settings.nvidia_model,
            },
        }

    @router.get("/sources")
    def sources() -> dict[str, object]:
        with runtime.database.connect() as connection:
            rows = {
                row["id"]: dict(row)
                for row in connection.execute(
                    "SELECT id, page_count, status, indexed_at FROM sources"
                ).fetchall()
            }
        return {
            "courses": [asdict(course) for course in runtime.catalog.courses],
            "sources": [
                {
                    "id": source.id,
                    "title": source.title,
                    "course_ids": source.course_ids,
                    "page_count": rows[source.id]["page_count"],
                    "index_status": rows[source.id]["status"],
                    "indexed_at": rows[source.id]["indexed_at"],
                }
                for source in runtime.catalog.sources
            ],
        }

    @router.post("/query")
    def query_textbooks(payload: QueryRequest) -> dict[str, object]:
        if len(payload.question) > runtime.settings.max_question_chars:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_input", "message": "question is too long"}},
            )
        result = runtime.service.query(
            payload.question,
            payload.provider,
            source_ids=tuple(dict.fromkeys(payload.source_ids)),
            course_ids=tuple(dict.fromkeys(payload.course_ids)),
            conversation_id=payload.conversation_id,
            select_all_that_apply=payload.select_all_that_apply,
        )
        return asdict(result)

    @router.get("/conversations")
    def list_conversations() -> dict[str, object]:
        return {"conversations": runtime.history.list()}

    @router.get("/conversations/{conversation_id}")
    def conversation_detail(conversation_id: str) -> dict[str, object]:
        return runtime.history.detail(conversation_id)

    @router.delete("/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str) -> Response:
        if not runtime.history.delete(conversation_id):
            raise HistoryNotFound(conversation_id)
        return Response(status_code=204)

    @router.delete("/conversations")
    def clear_conversations(confirm: bool = Query(default=False)) -> dict[str, object]:
        if not confirm:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "confirmation_required",
                        "message": "set confirm=true to delete all local conversation history",
                    }
                },
            )
        return {"deleted_conversations": runtime.history.clear()}

    @router.get("/sources/{source_id}/pdf")
    def source_pdf(source_id: str) -> FileResponse:
        try:
            source = runtime.catalog.source(source_id)
            path = runtime.catalog.file_for(source_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HistoryNotFound(source_id) from exc
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"{source.title}.pdf",
            content_disposition_type="inline",
        )

    return router


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or create_runtime()
    application = FastAPI(title="Textbook Desk API", version="0.1.0")
    application.state.runtime = runtime

    @application.exception_handler(HistoryNotFound)
    async def not_found_handler(_request: Request, _exc: HistoryNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "the requested local resource was not found"}},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_input",
                    "message": "request validation failed",
                    "details": exc.errors(),
                }
            },
        )

    @application.exception_handler(ScopeValidationError)
    async def scope_handler(_request: Request, exc: ScopeValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_input", "message": str(exc)}})

    @application.exception_handler(EmbeddingError)
    async def retrieval_handler(_request: Request, exc: EmbeddingError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "retrieval_unavailable", "message": str(exc)}},
        )

    @application.exception_handler(RuntimeError)
    async def runtime_handler(_request: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "retrieval_unavailable", "message": str(exc)}},
        )

    @application.exception_handler(ProviderFailure)
    async def provider_handler(_request: Request, exc: ProviderFailure) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "provider_unavailable",
                    "message": str(exc),
                    "provider": exc.provider,
                    "kind": exc.kind,
                    "fallback_used": exc.fallback_used,
                    "initial_failure_kind": exc.initial_failure_kind,
                }
            },
        )

    api = _api_router(runtime)
    application.include_router(api)
    application.include_router(api, prefix="/textbooks", include_in_schema=False)

    frontend_dist = runtime.settings.root / "frontend" / "dist"
    assets = frontend_dist / "assets"
    if assets.is_dir():
        application.mount("/textbooks/assets", StaticFiles(directory=assets), name="textbook-assets")

    if (frontend_dist / "index.html").is_file():
        @application.get("/textbooks", include_in_schema=False)
        @application.get("/textbooks/", include_in_schema=False)
        @application.get("/textbooks/{path:path}", include_in_schema=False)
        def frontend(path: str = "") -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return application


app = create_app()
