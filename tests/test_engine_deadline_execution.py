from __future__ import annotations

from fplagent_engine.deadline_execution import _central_route_matches


def test_central_route_requires_exact_ids_order_and_captaincy() -> None:
    canonical = {
        "candidate_id": "R-1",
        "starters": [{"element": element} for element in range(1, 12)],
        "bench": [{"element": element} for element in range(12, 16)],
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
    }
    route = {
        "route_id": "central",
        "route": {
            "squad_id": "R-1",
            "starter_elements": list(range(1, 12)),
            "bench_elements": list(range(12, 16)),
            "captain_element": 1,
            "vice_captain_element": 2,
        },
    }

    assert _central_route_matches(canonical, {"routes": [route]}) is True
    route["route"]["vice_captain_element"] = 3
    assert _central_route_matches(canonical, {"routes": [route]}) is False
