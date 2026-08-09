from __future__ import annotations

import pyarrow as pa

from fplagent_engine.bps_external_validation import (
    evaluate_external_bps_benchmark,
    normalize_player_name,
    parse_external_bps_html,
)


def _html() -> str:
    players = """[
      {"name":"Júnior One","team":"A","pos":"FWD","old":0,"full":2,"ch":[
        {"gw":1,"opp":"B","ob":0,"nb":1,"obps":20,"nbps":21,"ro":4,"rn":3,
         "dcbi":0,"tk":1,"gk":0,"fx":"10"},
        {"gw":1,"opp":"B","ob":0,"nb":1,"obps":20,"nbps":21,"ro":4,"rn":3,
         "dcbi":0,"tk":1,"gk":0,"fx":"10"}
      ]},
      {"name":"Defender Two","team":"B","pos":"DEF","old":2,"full":1,"ch":[
        {"gw":1,"opp":"A","ob":2,"nb":1,"obps":29,"nbps":28,"ro":2,"rn":3,
         "dcbi":-1,"tk":0,"gk":0,"fx":"10"}
      ]}
    ]"""
    movements = """{"10":[
      {"name":"Júnior One","team":"A","pos":"FWD","ob":0,"nb":1},
      {"name":"Júnior One","team":"A","pos":"FWD","ob":0,"nb":1},
      {"name":"Defender Two","team":"B","pos":"DEF","ob":2,"nb":1}
    ]}"""
    return f"<script>var D={players};var FM={movements};var tb=1;</script>"


def test_parser_records_exact_duplicate_without_double_counting_normalized_delta() -> None:
    result = parse_external_bps_html(_html())

    assert result["integrity"]["raw_movement_rows"] == 3
    assert result["integrity"]["unique_movement_rows"] == 2
    assert len(result["integrity"]["duplicate_movement_rows"]) == 1
    assert result["integrity"]["declared_totals_reconcile_with_raw_movements"] is True
    junior = next(row for row in result["players"] if row["player_name"] == "Júnior One")
    assert junior["declared_bonus_delta"] == 2
    assert junior["deduplicated_bonus_delta"] == 1
    assert normalize_player_name("Júnior One") == "junior one"


def test_external_benchmark_evaluation_matches_names_and_fixtures() -> None:
    benchmark = parse_external_bps_html(_html())
    reconstruction = pa.Table.from_pylist(
        [
            {
                "player_name": "Junior One",
                "position": "FWD",
                "fixture": 10,
                "minutes": 90,
                "mean_bonus_delta": 1.5,
            },
            {
                "player_name": "Defender Two",
                "position": "DEF",
                "fixture": 10,
                "minutes": 90,
                "mean_bonus_delta": -0.8,
            },
        ]
    )

    result = evaluate_external_bps_benchmark(benchmark, reconstruction)

    assert result["unmatched_external_players"] == []
    assert result["unmatched_unique_movements"] == []
    assert result["by_position"]["FWD"]["external_declared_delta"] == 2
    assert result["by_position"]["FWD"]["external_deduplicated_delta"] == 1
    assert result["source_integrity_exact"] is False
