from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .rules import SquadRules
from .season_state import (
    FIRST_HALF_END,
    ChipSlot,
    ChipStatus,
    ChipType,
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    default_chip_inventory,
    validate_manager_state,
)

CHIP_NAMES = {
    "wildcard": ChipType.WILDCARD,
    "freehit": ChipType.FREE_HIT,
    "free_hit": ChipType.FREE_HIT,
    "bboost": ChipType.BENCH_BOOST,
    "bench_boost": ChipType.BENCH_BOOST,
    "3xc": ChipType.TRIPLE_CAPTAIN,
    "triple_captain": ChipType.TRIPLE_CAPTAIN,
}


class ManagerStateInputError(ValueError):
    """The authenticated snapshot cannot yet produce an exact weekly state."""


def _required_int(snapshot: Mapping[str, Any], field: str) -> int:
    value = snapshot.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManagerStateInputError(f"manager snapshot requires integer {field}")
    return value


def _chip_status(value: Any) -> ChipStatus:
    normalized = str(value or "").casefold().replace("-", "_").replace(" ", "_")
    mapping = {
        "available": ChipStatus.AVAILABLE,
        "played": ChipStatus.PLAYED,
        "unavailable": ChipStatus.LOCKED,
        "locked": ChipStatus.LOCKED,
        "expired": ChipStatus.EXPIRED,
    }
    if normalized not in mapping:
        raise ManagerStateInputError(f"unsupported manager chip status {value!r}")
    return mapping[normalized]


def _chip_inventory(raw_chips: Any, event: int) -> tuple[ChipSlot, ...]:
    if not isinstance(raw_chips, list):
        raise ManagerStateInputError("manager snapshot chips must be a list")
    half = 1 if event <= FIRST_HALF_END else 2
    slots = default_chip_inventory()
    if half == 2:
        slots = tuple(
            replace(slot, status=ChipStatus.EXPIRED)
            if slot.half == 1
            else replace(slot, status=ChipStatus.AVAILABLE)
            for slot in slots
        )

    observed: dict[ChipType, tuple[ChipStatus, int | None]] = {}
    for raw in raw_chips:
        if not isinstance(raw, Mapping):
            raise ManagerStateInputError("manager chip entries must be objects")
        raw_name = str(raw.get("name") or raw.get("chip") or "").casefold()
        chip = CHIP_NAMES.get(raw_name)
        if chip is None:
            raise ManagerStateInputError(f"unsupported manager chip name {raw_name!r}")
        start_event = raw.get("start_event")
        raw_half = 2 if isinstance(start_event, int) and start_event >= 20 else half
        if raw_half != half:
            continue
        status = _chip_status(raw.get("status_for_entry") or raw.get("status"))
        played_event = raw.get("played_event")
        observed[chip] = (
            status,
            played_event if isinstance(played_event, int) else None,
        )

    required = {ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN} if event == 1 else set(ChipType)
    missing = required - set(observed)
    if missing:
        labels = ", ".join(sorted(chip.value for chip in missing))
        raise ManagerStateInputError(
            f"manager snapshot is missing current-half chip states: {labels}"
        )
    return tuple(
        replace(slot, status=observed[slot.chip][0], played_event=observed[slot.chip][1])
        if slot.half == half and slot.chip in observed
        else slot
        for slot in slots
    )


def manager_state_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    event: int,
    player_catalog: Mapping[int, Mapping[str, Any]],
    rules: SquadRules,
    season: str = "2026-27",
    previous_chip: ChipType | None = None,
    previous_chip_event: int | None = None,
) -> ManagerState:
    if snapshot.get("status") != "connected":
        raise ManagerStateInputError("manager snapshot is not authenticated")
    bank = _required_int(snapshot, "bank")
    free_transfers = _required_int(snapshot, "free_transfers")
    raw_transfer_cost = _required_int(snapshot, "transfer_cost")
    accounting_version = snapshot.get("transfer_accounting_version")
    if accounting_version is None:
        # MCP snapshots captured before transfer-accounting-v2 exposed FPL's
        # ``transfers.cost`` tariff through this field. It was not a manager's
        # already-committed hit cost. A positive remaining FT balance proves no
        # paid transfer has yet been needed; a zero balance is ambiguous and
        # must be refreshed through the v2 contract rather than guessed.
        if raw_transfer_cost and free_transfers == 0:
            raise ManagerStateInputError(
                "legacy manager snapshot cannot distinguish the transfer tariff from "
                "committed hit points; reconnect FPL with transfer-accounting-v2"
            )
        committed_points_cost = 0
    elif int(accounting_version) == 2:
        transfer_limit = _required_int(snapshot, "transfer_limit")
        transfers_made = _required_int(snapshot, "transfers_made")
        transfer_tariff = _required_int(snapshot, "transfer_cost_per_additional")
        expected_free = max(0, transfer_limit - transfers_made)
        expected_committed = max(0, transfers_made - transfer_limit) * transfer_tariff
        if free_transfers != expected_free:
            raise ManagerStateInputError(
                "manager transfer accounting is incoherent: remaining free transfers do not "
                "match limit minus transfers made"
            )
        if raw_transfer_cost != expected_committed:
            raise ManagerStateInputError(
                "manager transfer accounting is incoherent: committed hit points do not match "
                "the paid-transfer tariff"
            )
        committed_points_cost = raw_transfer_cost
    else:
        raise ManagerStateInputError("unsupported manager transfer accounting version")
    raw_picks = snapshot.get("picks")
    if not isinstance(raw_picks, list) or len(raw_picks) != rules.squad_size:
        raise ManagerStateInputError("manager snapshot must contain exactly 15 picks")

    picks: list[tuple[int, Mapping[str, Any]]] = []
    holdings: list[PlayerHolding] = []
    for raw_pick in raw_picks:
        if not isinstance(raw_pick, Mapping):
            raise ManagerStateInputError("manager pick entries must be objects")
        element = _required_int(raw_pick, "element")
        pick_position = _required_int(raw_pick, "position")
        purchase_price = _required_int(raw_pick, "purchase_price")
        selling_price = _required_int(raw_pick, "selling_price")
        player = player_catalog.get(element)
        if player is None:
            raise ManagerStateInputError(f"player {element} is absent from the current catalog")
        try:
            holding = PlayerHolding(
                player_id=element,
                position=str(player["position"]),
                team_id=int(player["team_id"]),
                purchase_price=purchase_price,
                current_price=round(float(player["market_price"])),
                selling_price=selling_price,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManagerStateInputError(
                f"current catalog row for player {element} is incomplete"
            ) from exc
        picks.append((pick_position, raw_pick))
        holdings.append(holding)

    picks.sort(key=lambda item: item[0])
    if [position for position, _ in picks] != list(range(1, rules.squad_size + 1)):
        raise ManagerStateInputError("manager pick positions must be exactly 1 through 15")
    starters = tuple(_required_int(pick, "element") for _, pick in picks[: rules.starting_size])
    bench = tuple(_required_int(pick, "element") for _, pick in picks[rules.starting_size :])
    captains = [_required_int(pick, "element") for _, pick in picks if bool(pick.get("is_captain"))]
    vice_captains = [
        _required_int(pick, "element") for _, pick in picks if bool(pick.get("is_vice_captain"))
    ]
    if len(captains) != 1 or len(vice_captains) != 1:
        raise ManagerStateInputError("manager snapshot requires one captain and vice-captain")

    state = ManagerState(
        season=season,
        event=event,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=tuple(holdings),
        bank=bank,
        free_transfers=free_transfers,
        chips=_chip_inventory(snapshot.get("chips"), event),
        lineup=Lineup(starters, bench, captains[0], vice_captains[0]),
        previous_chip=previous_chip,
        previous_chip_event=previous_chip_event,
        committed_points_cost=committed_points_cost,
        club_overflow_allowed=any(
            sum(h.team_id == candidate.team_id for h in holdings) > rules.club_limit
            for candidate in holdings
        ),
    )
    try:
        validate_manager_state(state, rules)
    except ValueError as exc:
        raise ManagerStateInputError(str(exc)) from exc
    return state


def player_catalog_from_rows(
    rows: Sequence[Mapping[str, Any]], *, event: int
) -> dict[int, Mapping[str, Any]]:
    catalog = {
        int(row["element"]): row for row in rows if int(row.get("event_number", -1)) == event
    }
    if not catalog:
        raise ManagerStateInputError(f"current player catalog has no rows for event {event}")
    return catalog
