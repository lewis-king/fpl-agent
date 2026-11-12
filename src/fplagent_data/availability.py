"""Interpret official availability for one named round, without crossing deadlines."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def official_availability(player: Mapping[str, Any], *, next_round: bool = True) -> int:
    """A null next-round value is not permission to reuse last round's chance."""
    if player.get("removed") is True or player.get("can_select") is False:
        return 0
    if player.get("status") == "u":
        return 0
    field = "chance_of_playing_next_round" if next_round else "chance_of_playing_this_round"
    value = player.get(field)
    if value is not None:
        chance = float(value)
        if not math.isfinite(chance) or not 0 <= chance <= 100:
            raise ValueError(f"Invalid official availability in {field}")
        return int(chance)
    if player.get("status") in {"a", None}:
        return 100
    if player.get("status") in {"i", "s", "n"}:
        return 0
    return 75
