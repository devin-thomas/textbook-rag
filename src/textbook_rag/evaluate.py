from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .db import Database
from .embeddings import OllamaEmbeddingClient
from .retrieval import HybridRetriever
from .settings import Settings


def evaluate_questions(retriever: HybridRetriever, payload: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in payload.get("questions", []):
        retrieval = retriever.retrieve(case["question"])
        actual_status = "answer" if retrieval.status == "ok" else "insufficient_evidence"
        expected_sources = set(case.get("expected_source_ids", []))
        retrieved_sources = {item.source_id for item in retrieval.evidence}
        source_pass = (
            not expected_sources and not retrieval.evidence
        ) or bool(expected_sources & retrieved_sources)
        status_pass = actual_status == case["expected_status"]
        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_status": case["expected_status"],
                "actual_status": actual_status,
                "expected_source_ids": sorted(expected_sources),
                "retrieved_source_ids": sorted(retrieved_sources),
                "top_semantic_score": retrieval.top_semantic_score,
                "top_pages": [
                    {
                        "source_id": item.source_id,
                        "physical_page": item.physical_page,
                        "page_label": item.page_label,
                        "fusion_score": item.fusion_score,
                    }
                    for item in retrieval.evidence[:3]
                ],
                "passed": status_pass and source_pass,
            }
        )
    passed = sum(bool(result["passed"]) for result in results)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "results": results,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Retrieval Evaluation",
        "",
        f"Passed: {report['passed']}/{report['total']} ({report['pass_rate']:.1%})",
        "",
        "| Case | Expected | Actual | Sources | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in report["results"]:
        sources = ", ".join(result["retrieved_source_ids"]) or "none"
        lines.append(
            f"| {result['id']} | {result['expected_status']} | {result['actual_status']} | "
            f"{sources} | {'PASS' if result['passed'] else 'FAIL'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval without invoking generation")
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.json"))
    parser.add_argument("--json", type=Path, default=Path("reports/retrieval-evaluation.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/retrieval-evaluation.md"))
    args = parser.parse_args()
    settings = Settings.from_env()
    catalog = Catalog.load(settings.catalog_path, settings.root)
    database = Database(settings.database_path)
    database.initialize(catalog)
    embeddings = OllamaEmbeddingClient(
        settings.ollama_base_url, settings.embedding_model, settings.embedding_dimension
    )
    retriever = HybridRetriever(
        database,
        embeddings,
        semantic_candidates=settings.retrieval_semantic_candidates,
        fts_candidates=settings.retrieval_fts_candidates,
        final_chunks=settings.retrieval_final_chunks,
        min_semantic_score=settings.retrieval_min_semantic_score,
    )
    payload = json.loads(args.questions.read_text(encoding="utf-8"))
    report = evaluate_questions(retriever, payload)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("total", "passed", "failed", "pass_rate")}, indent=2))
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
