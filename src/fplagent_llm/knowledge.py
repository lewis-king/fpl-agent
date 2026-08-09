from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    namespace: str
    title: str
    heading: str
    text: str
    source_path: str
    source_sha256: str
    effective_at: str
    observed_at: str
    expires_at: str | None
    authority: str
    rights: str

    def to_dict(self) -> dict[str, str | None]:
        return self.__dict__.copy()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _windows(words: list[str], target_words: int, overlap_words: int) -> Iterable[str]:
    if not words:
        return
    step = target_words - overlap_words
    for start in range(0, len(words), step):
        window = words[start : start + target_words]
        if not window:
            break
        yield " ".join(window)
        if start + target_words >= len(words):
            break


def chunk_markdown(
    path: Path,
    root: Path,
    namespace: str = "methodology",
    target_words: int = 420,
    overlap_words: int = 60,
) -> tuple[KnowledgeChunk, ...]:
    """Create deterministic, heading-aware chunks from an owned Markdown document."""
    if target_words <= overlap_words:
        raise ValueError("target_words must exceed overlap_words")
    text = path.read_text(encoding="utf-8")
    checksum = _sha256(path)
    relative = path.relative_to(root).as_posix()
    document_id = hashlib.sha256(relative.encode()).hexdigest()[:16]
    observed = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    title = path.stem.replace("-", " ").title()

    sections: list[tuple[str, list[str]]] = []
    heading = title
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if body:
                sections.append((heading, body))
            heading = line.lstrip("#").strip() or title
            body = []
        else:
            body.append(line)
    if body:
        sections.append((heading, body))

    chunks: list[KnowledgeChunk] = []
    for section_index, (section_heading, lines) in enumerate(sections):
        cleaned = "\n".join(lines).strip()
        for window_index, window in enumerate(
            _windows(_words(cleaned), target_words, overlap_words)
        ):
            chunk_key = f"{relative}:{section_index}:{window_index}:{checksum}"
            chunks.append(
                KnowledgeChunk(
                    chunk_id=hashlib.sha256(chunk_key.encode()).hexdigest()[:24],
                    document_id=document_id,
                    namespace=namespace,
                    title=title,
                    heading=section_heading,
                    text=window,
                    source_path=relative,
                    source_sha256=checksum,
                    effective_at=observed,
                    observed_at=observed,
                    expires_at=None,
                    authority="fplagent-internal",
                    rights="owned",
                )
            )
    return tuple(chunks)
