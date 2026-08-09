from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

POSITIONS = ("GK", "DEF", "MID", "FWD")
POSITION_LIMITS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
ROLES = ("starter", "bench")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"datetime must include a timezone: {value!r}")
    return parsed


@dataclass(frozen=True)
class CatalogPlayer:
    player_id: int
    web_name: str
    first_name: str
    second_name: str
    known_name: str | None
    position: str
    team_id: int
    price_tenths: int
    can_select: bool = True

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("player_id must be positive")
        if self.position not in POSITIONS:
            raise ValueError(f"invalid position: {self.position!r}")
        if self.team_id <= 0:
            raise ValueError("team_id must be positive")


@dataclass(frozen=True)
class ImportedPlayer:
    source_text: str
    squad_role: str
    order: int
    player_id: int | None = None
    position: str | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.source_text.strip():
            raise ValueError("source_text must not be blank")
        if self.squad_role not in ROLES:
            raise ValueError(f"invalid squad role: {self.squad_role!r}")
        if self.order < 1:
            raise ValueError("order must be positive")
        if self.player_id is not None and self.player_id <= 0:
            raise ValueError("player_id must be positive when present")
        if self.position is not None and self.position not in POSITIONS:
            raise ValueError(f"invalid position: {self.position!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ImportedPlayer:
        return cls(
            source_text=str(value["source_text"]),
            squad_role=str(value["squad_role"]),
            order=int(value["order"]),
            player_id=(int(value["player_id"]) if value.get("player_id") else None),
            position=(str(value["position"]) if value.get("position") else None),
            confidence=float(value.get("confidence", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "squad_role": self.squad_role,
            "order": self.order,
            "player_id": self.player_id,
            "position": self.position,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ScreenshotTeamProposal:
    schema_version: str
    source_image_id: str
    season: str
    players: tuple[ImportedPlayer, ...]
    captain_player_id: int | None
    vice_captain_player_id: int | None
    bench_order: tuple[int, ...]
    formation: str | None = None
    event: int | None = None
    deadline: datetime | None = None
    chips: Mapping[str, str] = field(default_factory=dict)
    unresolved: tuple[str, ...] = ()
    requires_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != "screenshot-team-v1":
            raise ValueError(f"unsupported screenshot schema: {self.schema_version!r}")
        if not self.source_image_id.strip():
            raise ValueError("source_image_id must not be blank")
        if not self.season.strip():
            raise ValueError("season must not be blank")
        if self.event is not None and self.event < 1:
            raise ValueError("event must be positive")
        orders = [(player.squad_role, player.order) for player in self.players]
        if len(orders) != len(set(orders)):
            raise ValueError("player role/order pairs must be unique")
        if not self.requires_confirmation:
            raise ValueError("screenshot imports must require explicit confirmation")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ScreenshotTeamProposal:
        return cls(
            schema_version=str(value["schema_version"]),
            source_image_id=str(value["source_image_id"]),
            season=str(value["season"]),
            event=(int(value["event"]) if value.get("event") is not None else None),
            deadline=_parse_datetime(value.get("deadline")),
            formation=(str(value["formation"]) if value.get("formation") else None),
            players=tuple(ImportedPlayer.from_dict(row) for row in value["players"]),
            captain_player_id=(
                int(value["captain_player_id"])
                if value.get("captain_player_id") is not None
                else None
            ),
            vice_captain_player_id=(
                int(value["vice_captain_player_id"])
                if value.get("vice_captain_player_id") is not None
                else None
            ),
            bench_order=tuple(int(item) for item in value.get("bench_order", [])),
            chips=dict(value.get("chips", {})),
            unresolved=tuple(str(item) for item in value.get("unresolved", [])),
            requires_confirmation=bool(value.get("requires_confirmation", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_image_id": self.source_image_id,
            "season": self.season,
            "event": self.event,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "formation": self.formation,
            "players": [player.to_dict() for player in self.players],
            "captain_player_id": self.captain_player_id,
            "vice_captain_player_id": self.vice_captain_player_id,
            "bench_order": list(self.bench_order),
            "chips": dict(self.chips),
            "unresolved": list(self.unresolved),
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class TeamValidationResult:
    valid: bool
    issues: tuple[str, ...]
    inferred_formation: str | None
    resolved_player_ids: tuple[int, ...]


def _formation(players: tuple[ImportedPlayer, ...]) -> str | None:
    counts = Counter(player.position for player in players if player.squad_role == "starter")
    if counts.get("GK") != 1:
        return None
    return f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"


def validate_resolved_team(
    proposal: ScreenshotTeamProposal,
    catalog: Mapping[int, CatalogPlayer],
) -> TeamValidationResult:
    """Validate a screenshot proposal without trusting model-provided player attributes."""
    issues: list[str] = []
    if len(proposal.players) != 15:
        issues.append(f"expected 15 players, found {len(proposal.players)}")

    resolved_ids = tuple(
        player.player_id for player in proposal.players if player.player_id is not None
    )
    if len(resolved_ids) != len(proposal.players):
        issues.append("one or more player names remain unresolved")
    if len(resolved_ids) != len(set(resolved_ids)):
        issues.append("the proposed squad contains duplicate player IDs")

    trusted_players: list[ImportedPlayer] = []
    team_counts: Counter[int] = Counter()
    for player in proposal.players:
        if player.player_id is None:
            continue
        trusted = catalog.get(player.player_id)
        if trusted is None:
            issues.append(f"player {player.player_id} is absent from the selected-season catalog")
            continue
        if not trusted.can_select:
            issues.append(f"player {player.player_id} cannot currently be selected")
        if player.position is not None and player.position != trusted.position:
            issues.append(
                f"player {player.player_id} position mismatch: "
                f"image={player.position}, catalog={trusted.position}"
            )
        trusted_players.append(
            ImportedPlayer(
                source_text=player.source_text,
                squad_role=player.squad_role,
                order=player.order,
                player_id=player.player_id,
                position=trusted.position,
                confidence=player.confidence,
            )
        )
        team_counts[trusted.team_id] += 1

    position_counts = Counter(player.position for player in trusted_players)
    if position_counts != Counter(POSITION_LIMITS):
        issues.append(
            "position counts must be 2 GK, 5 DEF, 5 MID and 3 FWD; "
            f"found {dict(position_counts)}"
        )
    starters = tuple(player for player in trusted_players if player.squad_role == "starter")
    bench = tuple(player for player in trusted_players if player.squad_role == "bench")
    if len(starters) != 11:
        issues.append(f"expected 11 starters, found {len(starters)}")
    if len(bench) != 4:
        issues.append(f"expected four bench players, found {len(bench)}")
    if any(count > 3 for count in team_counts.values()):
        offenders = sorted(team_id for team_id, count in team_counts.items() if count > 3)
        issues.append(f"more than three players selected from club IDs {offenders}")

    inferred = _formation(tuple(trusted_players))
    if inferred is not None:
        defenders, midfielders, forwards = (int(part) for part in inferred.split("-"))
        if defenders < 3 or midfielders < 2 or forwards < 1:
            issues.append(f"illegal starting formation: {inferred}")
    if proposal.formation and inferred and proposal.formation != inferred:
        issues.append(
            f"formation mismatch: image={proposal.formation}, inferred={inferred}"
        )

    starter_ids = {player.player_id for player in starters}
    if proposal.captain_player_id not in starter_ids:
        issues.append("captain must be a resolved starter")
    if proposal.vice_captain_player_id not in starter_ids:
        issues.append("vice-captain must be a resolved starter")
    if proposal.captain_player_id == proposal.vice_captain_player_id:
        issues.append("captain and vice-captain must differ")

    expected_bench = tuple(
        player.player_id for player in sorted(bench, key=lambda item: item.order)
    )
    if tuple(proposal.bench_order) != expected_bench:
        issues.append(
            f"bench order mismatch: supplied={proposal.bench_order}, "
            f"expected={expected_bench}"
        )
    if proposal.unresolved:
        issues.append("proposal contains explicitly unresolved image regions")

    return TeamValidationResult(
        valid=not issues,
        issues=tuple(issues),
        inferred_formation=inferred,
        resolved_player_ids=resolved_ids,
    )
