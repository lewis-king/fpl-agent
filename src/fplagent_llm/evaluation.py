from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .benchmarks import ScreenshotBenchmarkCase
from .contracts import ImportedPlayer, ScreenshotTeamProposal, validate_resolved_team
from .screenshot_import import derive_formation, resolve_proposal


def _normalise_state(value: object) -> str:
    if value is None:
        return "not_visible"
    return str(value).strip().lower().replace(" ", "_")


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_deadline(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _players(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def score_screenshot_extraction(
    extraction: Mapping[str, Any],
    benchmark: ScreenshotBenchmarkCase,
    catalog: Sequence,
) -> dict[str, Any]:
    """Resolve and score an untrusted VLM extraction against a locked case."""
    raw_players = _players(extraction.get("players"))
    imported: list[ImportedPlayer] = []
    captain_slots: list[tuple[str, int]] = []
    vice_slots: list[tuple[str, int]] = []
    parse_issues: list[str] = []
    seen_slots: set[tuple[str, int]] = set()

    for index, row in enumerate(raw_players, start=1):
        role = str(row.get("squad_role", "")).strip().lower()
        source_text = str(row.get("source_text", "")).strip()
        order = _optional_int(row.get("order"))
        position_value = str(row.get("position", "")).strip().upper()
        position = position_value or None
        if not source_text or role not in {"starter", "bench"} or order is None:
            parse_issues.append(f"invalid player row {index}")
            continue
        slot = (role, order)
        if slot in seen_slots:
            parse_issues.append(f"duplicate player slot {role}:{order}")
            continue
        seen_slots.add(slot)
        try:
            imported.append(
                ImportedPlayer(
                    source_text=source_text,
                    squad_role=role,
                    order=order,
                    position=position,
                )
            )
        except ValueError as exc:
            parse_issues.append(f"invalid player row {index}: {exc}")
            continue
        if bool(row.get("is_captain", False)):
            captain_slots.append(slot)
        if bool(row.get("is_vice_captain", False)):
            vice_slots.append(slot)

    unresolved = extraction.get("unresolved", [])
    if not isinstance(unresolved, Sequence) or isinstance(unresolved, (str, bytes)):
        unresolved = []
    proposal = ScreenshotTeamProposal(
        schema_version="screenshot-team-v1",
        source_image_id=benchmark.case_id,
        season=str(extraction.get("season") or benchmark.expected.season),
        event=_optional_int(extraction.get("event")),
        deadline=_parse_deadline(extraction.get("deadline")),
        formation=(str(extraction["formation"]) if extraction.get("formation") else None),
        players=tuple(imported),
        captain_player_id=None,
        vice_captain_player_id=None,
        bench_order=(),
        chips=(extraction.get("chips") if isinstance(extraction.get("chips"), Mapping) else {}),
        unresolved=tuple(str(item) for item in unresolved),
    )
    resolved = resolve_proposal(proposal, catalog)
    by_slot = {
        (player.squad_role, player.order): player.player_id for player in resolved.players
    }
    captain_id = by_slot.get(captain_slots[0]) if len(captain_slots) == 1 else None
    vice_id = by_slot.get(vice_slots[0]) if len(vice_slots) == 1 else None
    bench_ids = tuple(
        player.player_id
        for player in sorted(
            (player for player in resolved.players if player.squad_role == "bench"),
            key=lambda player: player.order,
        )
        if player.player_id is not None
    )
    raw_formation = resolved.formation
    derived_formation = derive_formation(resolved.players)
    resolved = ScreenshotTeamProposal(
        schema_version=resolved.schema_version,
        source_image_id=resolved.source_image_id,
        season=resolved.season,
        event=resolved.event,
        deadline=resolved.deadline,
        formation=derived_formation or raw_formation,
        players=resolved.players,
        captain_player_id=captain_id,
        vice_captain_player_id=vice_id,
        bench_order=bench_ids,
        chips=resolved.chips,
        unresolved=resolved.unresolved,
    )

    expected_slots = {
        (player.squad_role, player.order): player.player_id
        for player in benchmark.expected.players
    }
    expected_role_by_id = {
        player.player_id: player.squad_role for player in benchmark.expected.players
    }
    resolved_ids = {
        player.player_id for player in resolved.players if player.player_id is not None
    }
    identity_matches = len(resolved_ids & set(expected_role_by_id))
    role_matches = sum(
        expected_role_by_id.get(player.player_id) == player.squad_role
        for player in resolved.players
        if player.player_id is not None
    )
    correct_slots = sum(
        by_slot.get(slot) == player_id for slot, player_id in expected_slots.items()
    )
    expected_chips = benchmark.expected.chips
    extracted_chips = resolved.chips
    chip_items_correct = sum(
        key in extracted_chips
        and _normalise_state(extracted_chips.get(key)) == _normalise_state(value)
        for key, value in expected_chips.items()
    )
    validation = validate_resolved_team(
        resolved, {player.player_id: player for player in catalog}
    )
    deadline_exact = resolved.deadline == benchmark.expected.deadline
    formation_exact = raw_formation == benchmark.expected.formation
    captain_exact = captain_id == benchmark.expected.captain_player_id
    vice_exact = vice_id == benchmark.expected.vice_captain_player_id
    bench_exact = bench_ids == benchmark.expected.bench_order
    all_core_exact = (
        correct_slots == len(expected_slots)
        and captain_exact
        and vice_exact
        and bench_exact
    )
    return {
        "case_id": benchmark.case_id,
        "raw_player_rows": len(raw_players),
        "parsed_player_rows": len(imported),
        "resolved_player_rows": sum(
            player.player_id is not None for player in resolved.players
        ),
        "correct_player_identities": identity_matches,
        "player_identity_accuracy": identity_matches / len(expected_role_by_id),
        "correct_player_roles": role_matches,
        "player_role_accuracy": role_matches / len(expected_role_by_id),
        "correct_player_slots": correct_slots,
        "player_slot_accuracy": correct_slots / len(expected_slots),
        "captain_exact": captain_exact,
        "vice_captain_exact": vice_exact,
        "bench_order_exact": bench_exact,
        "formation_exact": formation_exact,
        "raw_extracted_formation": raw_formation,
        "derived_formation": derived_formation,
        "formation_normalized": bool(
            derived_formation is not None and derived_formation != raw_formation
        ),
        "event_exact": resolved.event == benchmark.expected.event,
        "deadline_exact": deadline_exact,
        "chip_items_correct": chip_items_correct,
        "chip_accuracy": (
            chip_items_correct / len(expected_chips) if expected_chips else 1.0
        ),
        "chips_exact": (
            chip_items_correct == len(expected_chips)
            and set(extracted_chips) == set(expected_chips)
        ),
        "core_team_exact": all_core_exact,
        "team_valid": validation.valid,
        "validation_issues": list(validation.issues),
        "parse_issues": parse_issues,
        "unresolved": list(resolved.unresolved),
        "resolved_proposal": resolved.to_dict(),
    }
