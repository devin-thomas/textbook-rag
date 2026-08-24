from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


class CatalogError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Course:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    title: str
    file_name: str
    course_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Catalog:
    root: Path
    courses: tuple[Course, ...]
    sources: tuple[Source, ...]

    @classmethod
    def load(cls, path: Path, root: Path) -> "Catalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        courses = tuple(Course(**item) for item in payload.get("courses", []))
        sources = tuple(
            Source(
                id=item["id"],
                title=item["title"],
                file_name=item["file_name"],
                course_ids=tuple(item["course_ids"]),
            )
            for item in payload.get("sources", [])
        )
        if not courses or not sources:
            raise CatalogError("catalog must include courses and sources")
        course_ids = {course.id for course in courses}
        if len(course_ids) != len(courses):
            raise CatalogError("course IDs must be unique")
        source_ids = {source.id for source in sources}
        if len(source_ids) != len(sources):
            raise CatalogError("source IDs must be unique")
        for source in sources:
            if not source.course_ids or not set(source.course_ids) <= course_ids:
                raise CatalogError(f"source {source.id!r} has unknown courses")
            cls._resolve_file(root, source.file_name)
        return cls(root=root.resolve(), courses=courses, sources=sources)

    @staticmethod
    def _resolve_file(root: Path, file_name: str) -> Path:
        if Path(file_name).name != file_name:
            raise CatalogError("catalog file_name must be a plain file name")
        candidate = (root / file_name).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise CatalogError("catalog file escapes project root") from exc
        return candidate

    def source(self, source_id: str) -> Source:
        try:
            return next(source for source in self.sources if source.id == source_id)
        except StopIteration as exc:
            raise KeyError(source_id) from exc

    def file_for(self, source_id: str, *, require_exists: bool = True) -> Path:
        source = self.source(source_id)
        path = self._resolve_file(self.root, source.file_name)
        if require_exists and not path.is_file():
            raise FileNotFoundError(path)
        return path
