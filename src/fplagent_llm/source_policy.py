from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import CONFIG

VALID_DECISIONS = frozenset({"allow", "review", "deny"})
DEFAULT_REGISTRY = CONFIG / "source_registry_v1.json"


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    source_type: str
    locator: str
    rights: str
    decisions: dict[str, str]
    notes: str
    terms_url: str | None = None

    def decision_for(self, use: str, default: str) -> str:
        return self.decisions.get(use, default)


@dataclass(frozen=True)
class SourceRegistry:
    schema_version: str
    reviewed_at: str
    default_decision: str
    uses: tuple[str, ...]
    sources: tuple[SourcePolicy, ...]

    def by_id(self) -> dict[str, SourcePolicy]:
        return {source.source_id: source for source in self.sources}

    def decision_for(self, source_id: str, use: str) -> str:
        if use not in self.uses:
            raise ValueError(f"unknown source-policy use: {use!r}")
        source = self.by_id().get(source_id)
        if source is None:
            return self.default_decision
        return source.decision_for(use, self.default_decision)

    def require_allowed(self, source_id: str, use: str) -> None:
        decision = self.decision_for(source_id, use)
        if decision != "allow":
            raise ValueError(
                f"source {source_id!r} is {decision!r}, not allowed for {use!r}"
            )

    def summary(self) -> dict[str, Any]:
        counts = {
            use: {decision: 0 for decision in sorted(VALID_DECISIONS)} for use in self.uses
        }
        for source in self.sources:
            for use in self.uses:
                counts[use][source.decision_for(use, self.default_decision)] += 1
        return {
            "schema_version": self.schema_version,
            "reviewed_at": self.reviewed_at,
            "default_decision": self.default_decision,
            "sources": len(self.sources),
            "decisions_by_use": counts,
        }


def load_source_registry(path: Path = DEFAULT_REGISTRY) -> SourceRegistry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "source-policy-v1":
        raise ValueError("unsupported source-policy schema")
    default = str(payload.get("default_decision", ""))
    if default not in VALID_DECISIONS:
        raise ValueError(f"invalid default source decision: {default!r}")
    uses = tuple(str(use) for use in payload.get("uses", []))
    if not uses or len(uses) != len(set(uses)):
        raise ValueError("source-policy uses must be present and unique")

    sources = []
    identifiers: set[str] = set()
    for row in payload.get("sources", []):
        source_id = str(row.get("source_id", ""))
        if not source_id or source_id in identifiers:
            raise ValueError(f"missing or duplicate source ID: {source_id!r}")
        identifiers.add(source_id)
        decisions = {str(use): str(decision) for use, decision in row["decisions"].items()}
        unknown_uses = set(decisions) - set(uses)
        if unknown_uses:
            raise ValueError(f"unknown uses for {source_id}: {sorted(unknown_uses)}")
        invalid = set(decisions.values()) - VALID_DECISIONS
        if invalid:
            raise ValueError(f"invalid decisions for {source_id}: {sorted(invalid)}")
        sources.append(
            SourcePolicy(
                source_id=source_id,
                source_type=str(row["source_type"]),
                locator=str(row["locator"]),
                rights=str(row["rights"]),
                decisions=decisions,
                notes=str(row["notes"]),
                terms_url=(str(row["terms_url"]) if row.get("terms_url") else None),
            )
        )

    if not sources:
        raise ValueError("source-policy registry must contain at least one source")
    return SourceRegistry(
        schema_version=str(payload["schema_version"]),
        reviewed_at=str(payload["reviewed_at"]),
        default_decision=default,
        uses=uses,
        sources=tuple(sources),
    )
