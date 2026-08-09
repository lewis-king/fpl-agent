from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from .rules import SquadRules, validate_squad


def squad_key(elements: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(map(int, elements)))


def enumerate_legal_one_swaps(
    selected: Iterable[int],
    meta: dict[int, dict[str, Any]],
    rules: SquadRules,
) -> list[dict[str, Any]]:
    incumbent = squad_key(selected)
    if len(incumbent) != rules.squad_size or len(set(incumbent)) != len(incumbent):
        raise ValueError("One-swap enumeration requires one valid unique squad")
    validate_squad([meta[element] for element in incumbent], rules)
    selected_set = set(incumbent)
    cost = sum(float(meta[element]["market_price"]) for element in incumbent)
    clubs = Counter(int(meta[element]["team_id"]) for element in incumbent)
    eligible_by_position: dict[str, list[int]] = defaultdict(list)
    for element, row in meta.items():
        if not bool(row.get("can_select", True)) or bool(row.get("removed", False)):
            continue
        eligible_by_position[str(row["position"])].append(int(element))
    for values in eligible_by_position.values():
        values.sort()

    swaps: list[dict[str, Any]] = []
    for outgoing in incumbent:
        outgoing_row = meta[outgoing]
        old_club = int(outgoing_row["team_id"])
        old_price = float(outgoing_row["market_price"])
        position = str(outgoing_row["position"])
        for incoming in eligible_by_position[position]:
            if incoming in selected_set:
                continue
            incoming_row = meta[incoming]
            new_club = int(incoming_row["team_id"])
            if clubs[new_club] - int(new_club == old_club) >= rules.club_limit:
                continue
            new_cost = cost - old_price + float(incoming_row["market_price"])
            if new_cost > rules.budget + 1e-8:
                continue
            squad = squad_key((*selected_set.difference({outgoing}), incoming))
            swaps.append(
                {
                    "squad_id": f"SW-{outgoing}-{incoming}",
                    "selected": list(squad),
                    "outgoing": outgoing,
                    "incoming": incoming,
                    "position": position,
                    "budget_spent": new_cost / 10.0,
                    "bank": (rules.budget - new_cost) / 10.0,
                }
            )
    swaps.sort(key=lambda row: (row["outgoing"], row["incoming"]))
    return swaps
