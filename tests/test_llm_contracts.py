from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fplagent_llm.benchmarks import (
    TEXT_CATEGORIES,
    load_screenshot_benchmark,
    load_text_benchmark,
)
from fplagent_llm.contracts import ImportedPlayer, validate_resolved_team
from fplagent_llm.paths import BENCHMARKS, ROOT
from fplagent_llm.screenshot_import import (
    load_current_catalog,
    normalize_player_name,
    resolve_player,
    resolve_proposal,
)
from fplagent_llm.tool_contracts import TOOL_CONTRACTS, openai_tools


def _catalog():
    return load_current_catalog(ROOT / "data" / "fpl_history.duckdb")


def test_tool_contracts_are_unique_and_openai_serializable() -> None:
    assert len({tool.name for tool in TOOL_CONTRACTS}) == len(TOOL_CONTRACTS)
    rendered = openai_tools()
    assert len(rendered) == len(TOOL_CONTRACTS)
    assert all(tool["type"] == "function" for tool in rendered)
    assert all(
        tool["function"]["parameters"]["additionalProperties"] is False
        for tool in rendered
    )


def test_locked_text_benchmark_has_all_declared_categories() -> None:
    cases = load_text_benchmark(BENCHMARKS / "fplbench_v1.jsonl")
    assert len(cases) >= 30
    assert {case.category for case in cases} == TEXT_CATEGORIES
    assert any(case.requires_fresh_data for case in cases)
    assert any(case.requires_citation for case in cases)


def test_app_chat_benchmark_prioritises_direct_conversation() -> None:
    cases = load_text_benchmark(BENCHMARKS / "appchatbench_v1.jsonl")
    assert len(cases) >= 50
    assert sum(not case.expected_tools for case in cases) >= 50
    assert {tool for case in cases for tool in case.expected_tools} == {
        "get_manager_state",
        "compare_captains",
        "search_players",
        "optimize_squad",
    }
    assert any("system" in case.prompt.casefold() for case in cases)


def test_first_screenshot_fixture_matches_the_current_catalog() -> None:
    case = load_screenshot_benchmark(
        BENCHMARKS / "screenshotbench_v1.jsonl"
    )[0]
    catalog = {player.player_id: player for player in _catalog()}
    result = validate_resolved_team(case.expected, catalog)
    assert result.valid, result.issues
    assert result.inferred_formation == "5-3-2"
    assert result.resolved_player_ids == (
        384,
        84,
        229,
        418,
        498,
        533,
        426,
        427,
        480,
        55,
        106,
        109,
        346,
        368,
        345,
    )


def test_user_supplied_screenshot_checksum_is_locked() -> None:
    case = load_screenshot_benchmark(
        BENCHMARKS / "screenshotbench_v1.jsonl"
    )[0]
    available, detail = case.verify_image(Path("/home/lewis/Downloads"))
    assert available, detail


def test_truncated_screenshot_names_resolve_without_guessing_ids() -> None:
    catalog = _catalog()
    donnarumma, keeper_score = resolve_player("Donnarum...", catalog, "GK")
    calvert_lewin, forward_score = resolve_player("Calvert-Le...", catalog, "FWD")
    assert donnarumma is not None and donnarumma.player_id == 384
    assert calvert_lewin is not None and calvert_lewin.player_id == 346
    assert keeper_score >= 0.95
    assert forward_score >= 0.95


def test_visible_fixture_suffix_is_not_treated_as_part_of_the_player_name() -> None:
    assert normalize_player_name("Donnarumma\nBOU (H)") == "donnarumma"
    assert normalize_player_name("Calvert-\nLewin\nNFO (A)") == "calvertlewin"


def test_unresolved_visual_proposal_can_be_resolved_then_validated() -> None:
    case = load_screenshot_benchmark(
        BENCHMARKS / "screenshotbench_v1.jsonl"
    )[0]
    unresolved_players = tuple(
        replace(player, player_id=None, confidence=0.0) for player in case.expected.players
    )
    unresolved = replace(
        case.expected,
        players=unresolved_players,
        unresolved=tuple(player.source_text for player in unresolved_players),
    )
    resolved = resolve_proposal(unresolved, _catalog())
    catalog = {player.player_id: player for player in _catalog()}
    result = validate_resolved_team(resolved, catalog)
    assert result.valid, result.issues


def test_invalid_screenshot_team_never_passes_validation() -> None:
    case = load_screenshot_benchmark(
        BENCHMARKS / "screenshotbench_v1.jsonl"
    )[0]
    broken_players = list(case.expected.players)
    broken_players[-1] = ImportedPlayer(
        source_text="Unknown",
        player_id=None,
        position="MID",
        squad_role="bench",
        order=4,
        confidence=0.2,
    )
    broken = replace(case.expected, players=tuple(broken_players), unresolved=("Unknown",))
    catalog = {player.player_id: player for player in _catalog()}
    result = validate_resolved_team(broken, catalog)
    assert not result.valid
    assert any("unresolved" in issue for issue in result.issues)
