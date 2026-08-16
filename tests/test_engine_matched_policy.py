from fplagent_engine.matched_policy import matched_legal_policy_replay


def _rows() -> list[dict]:
    positions = ["GK"] * 10 + ["DEF"] * 35 + ["MID"] * 35 + ["FWD"] * 20
    rows = []
    for element, position in enumerate(positions, start=1):
        actual = 10.0 if element in {1, 11, 12, 13, 46, 47, 48, 81, 82, 83, 84} else 2.0
        rows.append(
            {
                "season": "2025-26",
                "event_number": 1,
                "element": element,
                "player_name": f"P{element}",
                "position": position,
                "team_id": (element - 1) % 20 + 1,
                "market_price": 45.0,
                "target_points": actual,
                "champion": 3.0,
                "challenger": actual,
            }
        )
    return rows


def test_matched_forecasts_use_the_same_legal_solver() -> None:
    result = matched_legal_policy_replay(
        _rows(), champion_field="champion", challenger_field="challenger"
    )
    assert result["matched_events"] == 1
    assert result["total_delta"] > 0
    assert result["contract"]["identical_budget"] is True
