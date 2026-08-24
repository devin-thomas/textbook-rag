from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_dotenv_value(path: Path, name: str) -> str | None:
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'") or None
    return None


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    catalog_path: Path
    database_path: Path
    report_path: Path
    ollama_base_url: str
    embedding_model: str
    embedding_dimension: int
    ollama_generation_model: str
    nvidia_base_url: str
    nvidia_model: str
    nvidia_api_key: str | None
    retrieval_semantic_candidates: int
    retrieval_fts_candidates: int
    retrieval_final_chunks: int
    retrieval_min_semantic_score: float
    max_question_chars: int

    @classmethod
    def from_env(cls, root: Path | None = None) -> "Settings":
        resolved_root = (root or project_root()).resolve()
        nvidia_env_path = Path(
            os.getenv(
                "NVIDIA_DOTENV_PATH",
                r"C:\dev\experiments\free-nvidia-ai\nv.env",
            )
        )
        nvidia_key = os.getenv("NVIDIA_API_KEY") or _read_dotenv_value(
            nvidia_env_path, "NVIDIA_API_KEY"
        )
        return cls(
            root=resolved_root,
            catalog_path=Path(
                os.getenv("TEXTBOOK_CATALOG", resolved_root / "config" / "sources.json")
            ).resolve(),
            database_path=Path(
                os.getenv(
                    "TEXTBOOK_DATABASE",
                    resolved_root / "data" / "textbook-desk.sqlite3",
                )
            ).resolve(),
            report_path=Path(
                os.getenv(
                    "TEXTBOOK_INGESTION_REPORT",
                    resolved_root / "reports" / "ingestion.json",
                )
            ).resolve(),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11435").rstrip("/"),
            embedding_model=os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b"),
            embedding_dimension=int(os.getenv("OLLAMA_EMBEDDING_DIMENSION", "2560")),
            ollama_generation_model=os.getenv("OLLAMA_GENERATION_MODEL", "qwen3.5:9b"),
            nvidia_base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ).rstrip("/"),
            nvidia_model=os.getenv(
                "NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"
            ),
            nvidia_api_key=nvidia_key,
            retrieval_semantic_candidates=int(
                os.getenv("RETRIEVAL_SEMANTIC_CANDIDATES", "24")
            ),
            retrieval_fts_candidates=int(os.getenv("RETRIEVAL_FTS_CANDIDATES", "24")),
            retrieval_final_chunks=int(os.getenv("RETRIEVAL_FINAL_CHUNKS", "8")),
            retrieval_min_semantic_score=float(
                os.getenv("RETRIEVAL_MIN_SEMANTIC_SCORE", "0.35")
            ),
            max_question_chars=int(os.getenv("MAX_QUESTION_CHARS", "4000")),
        )
