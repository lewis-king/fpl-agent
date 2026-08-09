from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ScreenshotTeamProposal
from .tool_contracts import TOOL_BY_NAME

TEXT_CATEGORIES = {
    "ambiguity",
    "decision",
    "entity_resolution",
    "grounding",
    "language",
    "manager_state",
    "multilingual",
    "prompt_injection",
    "rules",
    "staleness",
    "tool_routing",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: each row must be an object")
            rows.append(value)
    return rows


@dataclass(frozen=True)
class TextBenchmarkCase:
    case_id: str
    category: str
    prompt: str
    expected_tools: tuple[str, ...]
    response_must_contain: tuple[str, ...]
    response_must_not_contain: tuple[str, ...]
    requires_fresh_data: bool
    requires_citation: bool
    notes: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TextBenchmarkCase:
        case = cls(
            case_id=str(value["case_id"]),
            category=str(value["category"]),
            prompt=str(value["prompt"]),
            expected_tools=tuple(str(item) for item in value.get("expected_tools", [])),
            response_must_contain=tuple(
                str(item) for item in value.get("response_must_contain", [])
            ),
            response_must_not_contain=tuple(
                str(item) for item in value.get("response_must_not_contain", [])
            ),
            requires_fresh_data=bool(value.get("requires_fresh_data", False)),
            requires_citation=bool(value.get("requires_citation", False)),
            notes=str(value.get("notes", "")),
        )
        case.validate()
        return case

    def validate(self) -> None:
        if not self.case_id or not self.prompt.strip():
            raise ValueError("benchmark case ID and prompt must not be blank")
        if self.category not in TEXT_CATEGORIES:
            raise ValueError(f"unknown benchmark category: {self.category!r}")
        unknown = set(self.expected_tools) - set(TOOL_BY_NAME)
        if unknown:
            raise ValueError(f"unknown expected tools for {self.case_id}: {unknown}")
        if self.requires_fresh_data and not self.expected_tools:
            raise ValueError(
                f"fresh-data case {self.case_id} must require at least one authoritative tool"
            )


@dataclass(frozen=True)
class ScreenshotBenchmarkCase:
    case_id: str
    image_filename: str
    image_sha256: str
    width: int
    height: int
    expected: ScreenshotTeamProposal
    notes: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ScreenshotBenchmarkCase:
        case = cls(
            case_id=str(value["case_id"]),
            image_filename=str(value["image_filename"]),
            image_sha256=str(value["image_sha256"]),
            width=int(value["width"]),
            height=int(value["height"]),
            expected=ScreenshotTeamProposal.from_dict(value["expected"]),
            notes=str(value.get("notes", "")),
        )
        case.validate()
        return case

    def validate(self) -> None:
        if not self.case_id or not self.image_filename:
            raise ValueError("screenshot benchmark ID and filename must not be blank")
        if len(self.image_sha256) != 64:
            raise ValueError(f"invalid SHA-256 for {self.case_id}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"invalid image dimensions for {self.case_id}")
        if self.expected.source_image_id != self.case_id:
            raise ValueError(
                f"source image ID mismatch for {self.case_id}: "
                f"{self.expected.source_image_id}"
            )

    def verify_image(self, image_root: Path) -> tuple[bool, str]:
        path = image_root / self.image_filename
        if not path.exists():
            return False, f"missing image: {path}"
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != self.image_sha256:
            return False, f"checksum mismatch for {path}"
        return True, str(path)


def load_text_benchmark(path: Path) -> tuple[TextBenchmarkCase, ...]:
    cases = tuple(TextBenchmarkCase.from_dict(value) for value in _read_jsonl(path))
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate text benchmark IDs in {path}")
    prompts = [hashlib.sha256(case.prompt.strip().lower().encode()).hexdigest() for case in cases]
    if len(prompts) != len(set(prompts)):
        raise ValueError(f"duplicate text benchmark prompts in {path}")
    return cases


def load_screenshot_benchmark(path: Path) -> tuple[ScreenshotBenchmarkCase, ...]:
    cases = tuple(ScreenshotBenchmarkCase.from_dict(value) for value in _read_jsonl(path))
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate screenshot benchmark IDs in {path}")
    return cases
