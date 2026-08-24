from __future__ import annotations

from textbook_rag.evaluate import evaluate_questions, markdown_report
from textbook_rag.retrieval import Evidence, RetrievalResult


class StubRetriever:
    def retrieve(self, question: str):
        if "unsupported" in question:
            return RetrievalResult("insufficient_evidence", (), .1)
        evidence = Evidence("c1", "book", "Book", 2, "ii", "text", 1, .8, 1.0, .03)
        return RetrievalResult("ok", (evidence,), .8)


def test_evaluator_checks_status_and_source_without_generation() -> None:
    payload = {
        "questions": [
            {
                "id": "answer",
                "question": "supported",
                "expected_status": "answer",
                "expected_source_ids": ["book"],
            },
            {
                "id": "no-answer",
                "question": "unsupported",
                "expected_status": "insufficient_evidence",
                "expected_source_ids": [],
            },
        ]
    }
    report = evaluate_questions(StubRetriever(), payload)
    assert report["passed"] == 2
    assert report["failed"] == 0
    assert "Passed: 2/2" in markdown_report(report)
