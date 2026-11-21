from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .rules import SquadRules, validate_lineup, validate_squad

HIT_COST = 4
FIRST_HALF_END = 19
LAST_EVENT = 38


class ChipType(StrEnum):
    WILDCARD = "wildcard"
    FREE_HIT = "free_hit"
    BENCH_BOOST = "bench_boost"
    TRIPLE_CAPTAIN = "triple_captain"


class ChipStatus(StrEnum):
    LOCKED = "locked"
    AVAILABLE = "available"
    PLAYED = "played"
    EXPIRED = "expired"


class EventStatus(StrEnum):
    DEADLINE_OPEN = "deadline_open"
    LOCKED = "locked"
    LIVE = "live"
    PROVISIONAL = "provisional"
    FINAL = "final"


@dataclass(frozen=True)
class MarketPlayer:
    player_id: int
    position: str
    team_id: int
    current_price: int

    def as_holding(self) -> PlayerHolding:
        return PlayerHolding(
            player_id=self.player_id,
            position=self.position,
            team_id=self.team_id,
            purchase_price=self.current_price,
            current_price=self.current_price,
            selling_price=self.current_price,
        )


@dataclass(frozen=True)
class PlayerHolding:
    player_id: int
    position: str
    team_id: int
    purchase_price: int
    current_price: int
    selling_price: int

    def with_current_price(self, current_price: int) -> PlayerHolding:
        return replace(
            self,
            current_price=current_price,
            selling_price=calculated_selling_price(self.purchase_price, current_price),
        )


@dataclass(frozen=True)
class Lineup:
    starters: tuple[int, ...]
    bench_order: tuple[int, ...]
    captain: int
    vice_captain: int


@dataclass(frozen=True)
class ChipSlot:
    chip: ChipType
    half: int
    status: ChipStatus
    played_event: int | None = None


@dataclass(frozen=True)
class ManagerState:
    season: str
    event: int
    event_status: EventStatus
    squad: tuple[PlayerHolding, ...]
    bank: int
    free_transfers: int
    chips: tuple[ChipSlot, ...]
    lineup: Lineup
    previous_chip: ChipType | None = None
    previous_chip_event: int | None = None
    committed_points_cost: int = 0
    # Only authenticated held squads / observed real-club transitions can set
    # this. Any actual fantasy transfer must restore the ordinary club limit.
    club_overflow_allowed: bool = False
    # A Wildcard already activated for this Gameweek. It cannot be cancelled,
    # so every plan for the week plays it; its slot stays AVAILABLE until then.
    active_chip: ChipType | None = None


@dataclass(frozen=True)
class Transfer:
    outgoing_player_id: int
    incoming: MarketPlayer


@dataclass(frozen=True)
class ActionBundle:
    event: int
    lineup: Lineup
    transfers: tuple[Transfer, ...] = ()
    chip: ChipType | None = None


@dataclass(frozen=True)
class GameweekState:
    season: str
    event: int
    status: EventStatus
    squad: tuple[PlayerHolding, ...]
    bank: int
    lineup: Lineup
    chip: ChipType | None
    transfers: tuple[Transfer, ...]
    free_transfers_before: int
    incremental_points_cost: int
    points_cost: int


@dataclass(frozen=True)
class ActionOutcome:
    gameweek: GameweekState
    next_manager: ManagerState | None


def calculated_selling_price(purchase_price: int, current_price: int) -> int:
    if purchase_price <= 0 or current_price <= 0:
        raise ValueError("Player prices must be positive integer tenths")
    if current_price <= purchase_price:
        return current_price
    return purchase_price + (current_price - purchase_price) // 2


def default_chip_inventory() -> tuple[ChipSlot, ...]:
    return tuple(
        ChipSlot(
            chip=chip,
            half=half,
            status=ChipStatus.AVAILABLE if half == 1 else ChipStatus.LOCKED,
        )
        for half in (1, 2)
        for chip in ChipType
    )


def _squad_rows(squad: tuple[PlayerHolding, ...]) -> list[dict]:
    return [
        {
            "element": player.player_id,
            "position": player.position,
            "team_id": player.team_id,
            "market_price": player.current_price,
        }
        for player in squad
    ]


def validate_manager_state(state: ManagerState, rules: SquadRules) -> None:
    if not isinstance(state.club_overflow_allowed, bool):
        raise ValueError("Club-overflow provenance flag must be boolean")  # noqa: TRY004 -- state contract validators use ValueError
    if not 1 <= state.event <= LAST_EVENT:
        raise ValueError("Manager event must be in [1, 38]")
    if state.event_status != EventStatus.DEADLINE_OPEN:
        raise ValueError("Manager state must describe an open decision deadline")
    if state.bank < 0:
        raise ValueError("Manager bank cannot be negative")
    if not 0 <= state.free_transfers <= rules.max_free_transfers:
        raise ValueError("Free-transfer bank is outside the live rule bounds")
    if state.committed_points_cost < 0 or state.committed_points_cost % HIT_COST:
        raise ValueError("Committed transfer cost must be a non-negative multiple of four")
    if len(state.chips) != 8 or len({(slot.half, slot.chip) for slot in state.chips}) != 8:
        raise ValueError("Manager state must contain one of each chip in each half")
    if (state.previous_chip is None) != (state.previous_chip_event is None):
        raise ValueError("Previous chip and event must either both be set or both be absent")
    for player in state.squad:
        expected_sell = calculated_selling_price(player.purchase_price, player.current_price)
        if player.selling_price != expected_sell:
            raise ValueError(
                f"Selling price for player {player.player_id} is {player.selling_price}; "
                f"expected {expected_sell}"
            )
    rows = _squad_rows(state.squad)
    # A held squad may appreciate above the initial budget. Transfer affordability is
    # enforced from bank plus exact selling proceeds when an action is applied.
    held_rules = (
        replace(rules, club_limit=rules.squad_size) if state.club_overflow_allowed else rules
    )
    validate_squad(rows, held_rules, enforce_budget=False)
    validate_lineup(
        rows,
        state.lineup.starters,
        state.lineup.bench_order,
        state.lineup.captain,
        state.lineup.vice_captain,
        rules,
    )


def _consume_chip(
    chips: tuple[ChipSlot, ...], chip: ChipType | None, event: int
) -> tuple[ChipSlot, ...]:
    if chip is None:
        return chips
    half = 1 if event <= FIRST_HALF_END else 2
    matching = [slot for slot in chips if slot.half == half and slot.chip == chip]
    if len(matching) != 1 or matching[0].status != ChipStatus.AVAILABLE:
        raise ValueError(f"{chip.value} is not available in event {event}")
    return tuple(
        replace(slot, status=ChipStatus.PLAYED, played_event=event) if slot == matching[0] else slot
        for slot in chips
    )


def _chips_for_next_event(chips: tuple[ChipSlot, ...], next_event: int) -> tuple[ChipSlot, ...]:
    if next_event != FIRST_HALF_END + 1:
        return chips
    return tuple(
        replace(slot, status=ChipStatus.EXPIRED)
        if slot.half == 1 and slot.status == ChipStatus.AVAILABLE
        else replace(slot, status=ChipStatus.AVAILABLE)
        if slot.half == 2 and slot.status == ChipStatus.LOCKED
        else slot
        for slot in chips
    )


def _validate_chip_action(state: ManagerState, chip: ChipType | None) -> None:
    if chip in {ChipType.WILDCARD, ChipType.FREE_HIT} and state.event == 1:
        raise ValueError(f"{chip.value} cannot be played in Gameweek 1")
    if (
        chip == ChipType.FREE_HIT
        and state.previous_chip == ChipType.FREE_HIT
        and state.previous_chip_event == state.event - 1
    ):
        raise ValueError("Free Hit cannot be played in consecutive Gameweeks")


def _apply_transfers(
    state: ManagerState, transfers: tuple[Transfer, ...], rules: SquadRules
) -> tuple[tuple[PlayerHolding, ...], int]:
    outgoing = [transfer.outgoing_player_id for transfer in transfers]
    incoming = [transfer.incoming.player_id for transfer in transfers]
    if len(set(outgoing)) != len(outgoing) or len(set(incoming)) != len(incoming):
        raise ValueError("Transfer bundle contains duplicate incoming or outgoing players")
    by_id = {player.player_id: player for player in state.squad}
    if not set(outgoing) <= set(by_id):
        raise ValueError("Transfer bundle sells a player outside the current squad")
    retained = set(by_id) - set(outgoing)
    if retained & set(incoming):
        raise ValueError("Transfer bundle buys a player already retained in the squad")
    bank = state.bank + sum(by_id[player].selling_price for player in outgoing)
    bank -= sum(transfer.incoming.current_price for transfer in transfers)
    if bank < 0:
        raise ValueError("Transfer bundle exceeds available funds")
    transferred = [player for player in state.squad if player.player_id not in set(outgoing)]
    transferred.extend(transfer.incoming.as_holding() for transfer in transfers)
    output = tuple(transferred)
    held_rules = (
        replace(rules, club_limit=rules.squad_size)
        if not transfers and state.club_overflow_allowed
        else rules
    )
    validate_squad(_squad_rows(output), held_rules, enforce_budget=False)
    return output, bank


def apply_action(state: ManagerState, action: ActionBundle, rules: SquadRules) -> ActionOutcome:
    validate_manager_state(state, rules)
    if action.event != state.event:
        raise ValueError("Action event does not match manager state")
    _validate_chip_action(state, action.chip)
    chips = _consume_chip(state.chips, action.chip, state.event)
    gameweek_squad, gameweek_bank = _apply_transfers(state, action.transfers, rules)
    gameweek_rows = _squad_rows(gameweek_squad)
    validate_lineup(
        gameweek_rows,
        action.lineup.starters,
        action.lineup.bench_order,
        action.lineup.captain,
        action.lineup.vice_captain,
        rules,
    )
    unlimited = action.chip in {ChipType.WILDCARD, ChipType.FREE_HIT}
    paid_transfers = 0 if unlimited else max(0, len(action.transfers) - state.free_transfers)
    incremental_points_cost = paid_transfers * HIT_COST
    points_cost = state.committed_points_cost + incremental_points_cost
    next_free_transfers = (
        state.free_transfers
        if unlimited
        else min(
            rules.max_free_transfers,
            max(0, state.free_transfers - len(action.transfers)) + 1,
        )
    )
    gameweek = GameweekState(
        season=state.season,
        event=state.event,
        status=EventStatus.LOCKED,
        squad=gameweek_squad,
        bank=gameweek_bank,
        lineup=action.lineup,
        chip=action.chip,
        transfers=action.transfers,
        free_transfers_before=state.free_transfers,
        incremental_points_cost=incremental_points_cost,
        points_cost=points_cost,
    )
    if state.event == LAST_EVENT:
        return ActionOutcome(gameweek=gameweek, next_manager=None)

    free_hit = action.chip == ChipType.FREE_HIT
    next_event = state.event + 1
    next_state = ManagerState(
        season=state.season,
        event=next_event,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=state.squad if free_hit else gameweek_squad,
        bank=state.bank if free_hit else gameweek_bank,
        free_transfers=next_free_transfers,
        chips=_chips_for_next_event(chips, next_event),
        lineup=state.lineup if free_hit else action.lineup,
        previous_chip=action.chip,
        previous_chip_event=state.event if action.chip is not None else None,
        committed_points_cost=0,
        club_overflow_allowed=state.club_overflow_allowed
        if free_hit or not action.transfers
        else False,
    )
    validate_manager_state(next_state, rules)
    return ActionOutcome(gameweek=gameweek, next_manager=next_state)


def advance_gameweek_status(state: GameweekState, status: EventStatus) -> GameweekState:
    order = (
        EventStatus.LOCKED,
        EventStatus.LIVE,
        EventStatus.PROVISIONAL,
        EventStatus.FINAL,
    )
    if state.status not in order or status not in order:
        raise ValueError("Gameweek outcomes cannot move to an open-deadline status")
    if order.index(status) != order.index(state.status) + 1:
        raise ValueError("Gameweek status must advance exactly one finality stage")
    return replace(state, status=status)
