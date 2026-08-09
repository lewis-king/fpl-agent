from __future__ import annotations

import json

from fplagent_llm.benchmarks import load_screenshot_benchmark
from fplagent_llm.cli import main
from fplagent_llm.evaluation import score_screenshot_extraction
from fplagent_llm.paths import BENCHMARKS, ROOT
from fplagent_llm.screenshot_import import load_current_catalog


def test_expected_visible_extraction_scores_exactly() -> None:
    case = load_screenshot_benchmark(BENCHMARKS / "screenshotbench_v1.jsonl")[0]
    extraction = {
        "season": case.expected.season,
        "event": case.expected.event,
        "deadline": case.expected.deadline.isoformat(),
        "formation": case.expected.formation,
        "players": [
            {
                "source_text": player.source_text,
                "position": player.position,
                "squad_role": player.squad_role,
                "order": player.order,
                "is_captain": player.player_id == case.expected.captain_player_id,
                "is_vice_captain": player.player_id
                == case.expected.vice_captain_player_id,
            }
            for player in case.expected.players
        ],
        "chips": dict(case.expected.chips),
        "unresolved": [],
    }
    result = score_screenshot_extraction(
        extraction,
        case,
        load_current_catalog(ROOT / "data" / "fpl_history.duckdb"),
    )
    assert result["core_team_exact"] is True
    assert result["team_valid"] is True
    assert result["player_slot_accuracy"] == 1.0
    assert result["chip_accuracy"] == 1.0


def test_malformed_player_row_is_counted_not_trusted() -> None:
    case = load_screenshot_benchmark(BENCHMARKS / "screenshotbench_v1.jsonl")[0]
    result = score_screenshot_extraction(
        {"players": [{"source_text": "Watkins", "squad_role": "reserve"}]},
        case,
        load_current_catalog(ROOT / "data" / "fpl_history.duckdb"),
    )
    assert result["parsed_player_rows"] == 0
    assert result["team_valid"] is False
    assert result["parse_issues"] == ["invalid player row 1"]


def test_complete_roster_normalizes_model_formation_from_resolved_positions() -> None:
    case = load_screenshot_benchmark(BENCHMARKS / "screenshotbench_v1.jsonl")[0]
    extraction = {
        "formation": "3-5-2",
        "players": [
            {
                "source_text": player.source_text,
                "position": player.position,
                "squad_role": player.squad_role,
                "order": player.order,
                "is_captain": player.player_id == case.expected.captain_player_id,
                "is_vice_captain": player.player_id
                == case.expected.vice_captain_player_id,
            }
            for player in case.expected.players
        ],
        "chips": dict(case.expected.chips),
    }
    result = score_screenshot_extraction(
        extraction,
        case,
        load_current_catalog(ROOT / "data/fpl_history.duckdb"),
    )

    assert result["formation_exact"] is False
    assert result["raw_extracted_formation"] == "3-5-2"
    assert result["derived_formation"] == "5-3-2"
    assert result["formation_normalized"] is True
    assert result["resolved_proposal"]["formation"] == "5-3-2"
    assert result["team_valid"] is True


def test_score_command_accepts_wrapped_model_output(
    tmp_path, monkeypatch, capsys
) -> None:
    path = tmp_path / "output.json"
    path.write_text(json.dumps({"extraction": {"players": []}}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "fplagent-llm",
            "score-screenshot",
            "--extraction",
            str(path),
            "--case-id",
            "fpl-team-001",
        ],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["case_id"] == "fpl-team-001"
    assert result["raw_player_rows"] == 0


def test_synthetic_score_command_accepts_generated_truth(
    tmp_path, monkeypatch, capsys
) -> None:
    case = load_screenshot_benchmark(BENCHMARKS / "screenshotbench_v1.jsonl")[0]
    extraction = {
        "players": [
            {
                "source_text": player.source_text,
                "position": player.position,
                "squad_role": player.squad_role,
                "order": player.order,
                "is_captain": player.player_id == case.expected.captain_player_id,
                "is_vice_captain": player.player_id
                == case.expected.vice_captain_player_id,
            }
            for player in case.expected.players
        ],
        "formation": case.expected.formation,
        "event": case.expected.event,
        "deadline": case.expected.deadline.isoformat(),
        "chips": dict(case.expected.chips),
    }
    extraction_path = tmp_path / "extraction.json"
    truth_path = tmp_path / "truth.json"
    extraction_path.write_text(json.dumps({"extraction": extraction}), encoding="utf-8")
    truth_path.write_text(
        json.dumps(
            {
                "case_id": case.case_id,
                "resolved_proposal": case.expected.to_dict(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fplagent-llm",
            "score-synthetic-screenshot",
            "--extraction",
            str(extraction_path),
            "--truth",
            str(truth_path),
        ],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["core_team_exact"] is True
    assert result["team_valid"] is True
