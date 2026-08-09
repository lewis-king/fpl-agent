from __future__ import annotations

import copy
import hashlib
import json
import os
import random
from collections import Counter
from pathlib import Path
from typing import Any

from .app_corpus import (
    BOUNDARY_SCENARIOS,
    CAPABILITY_SCENARIOS,
    GENERAL_SCENARIOS,
    LEADS,
    SAFETY_SCENARIOS,
    SOCIAL_SCENARIOS,
    STRATEGY_SCENARIOS,
    TAILS,
    TOOL_LEADS,
    TOOL_TAILS,
    _assert_benchmark_separation,
    _display_path,
    _frame_question,
)
from .conversation_corpus import _concepts, _load_jsonl
from .dataset import SYSTEM_PROMPT, _tool_call_message, _write_jsonl, validate_sft_rows
from .paths import GENERATED

GENERATOR_VERSION = "fpl-app-precision-corpus-v9"
DEFAULT_BASE = GENERATED / "fpl_app_corpus_v6" / "combined_train.jsonl"
DEFAULT_OUTPUT = GENERATED / "fpl_app_precision_v9"
DEFAULT_SEED = 20_260_809
DIRECT_VARIANTS = 12
TOOL_VARIANTS = 100
MULTI_TURN_ROWS = 200
MULTILINGUAL_REPLAY_ROWS = 200
IMAGE_REPLAY_ROWS = 960


def _direct_scenarios() -> tuple[tuple[str, str, str], ...]:
    concepts = tuple(
        (
            f"In FPL, what does {term} mean and how should I use it?",
            definition,
            caveat,
        )
        for term, definition, caveat in _concepts()
    )
    return (
        CAPABILITY_SCENARIOS
        + SOCIAL_SCENARIOS
        + GENERAL_SCENARIOS
        + BOUNDARY_SCENARIOS
        + STRATEGY_SCENARIOS
        + SAFETY_SCENARIOS
        + concepts
    )


def _direct_rows(seed: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prompt_frames = [(lead, tail) for lead in LEADS for tail in TAILS]
    for scenario_index, (question, answer, detail) in enumerate(_direct_scenarios()):
        frames = list(prompt_frames)
        random.Random(seed + scenario_index).shuffle(frames)
        response = f"{answer} {detail}"
        for variant_index, (lead, tail) in enumerate(frames[:DIRECT_VARIANTS]):
            rows.append(
                {
                    "id": f"v9-direct-{scenario_index + 1:03d}-{variant_index + 1:02d}",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"{_frame_question(lead, question)} {tail}",
                        },
                        {"role": "assistant", "content": response},
                    ],
                    "metadata": {
                        "split": "train",
                        "family": "precision_direct",
                        "scenario_group": f"v9-direct-{scenario_index + 1:03d}",
                        "language": "en",
                        "synthetic": True,
                        "tool_expected": False,
                        "tool_context": "exact_app_runtime_v1",
                        "generator_version": GENERATOR_VERSION,
                    },
                }
            )
    return rows


def _multi_turn_rows(seed: int) -> list[dict[str, Any]]:
    scenarios = CAPABILITY_SCENARIOS + SOCIAL_SCENARIOS + STRATEGY_SCENARIOS
    rows: list[dict[str, Any]] = []
    combinations = [
        (scenario_index, lead_index, tail_index)
        for scenario_index in range(len(scenarios))
        for lead_index in range(len(LEADS))
        for tail_index in range(4)
    ]
    random.Random(seed).shuffle(combinations)
    follow_ups = (
        "Can you make that shorter?",
        "What is the one thing I should remember?",
        "Say that again without jargon.",
        "And what is the main caveat?",
    )
    for row_index, (scenario_index, lead_index, tail_index) in enumerate(
        combinations[:MULTI_TURN_ROWS], start=1
    ):
        question, answer, detail = scenarios[scenario_index]
        rows.append(
            {
                "id": f"v9-multi-{row_index:04d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "We're continuing a longer FPL chat. "
                            f"{_frame_question(LEADS[lead_index], question)} "
                            f"{TAILS[tail_index]}"
                        ),
                    },
                    {"role": "assistant", "content": f"{answer} {detail}"},
                    {
                        "role": "user",
                        "content": follow_ups[(row_index + scenario_index) % len(follow_ups)],
                    },
                    {"role": "assistant", "content": answer},
                ],
                "metadata": {
                    "split": "train",
                    "family": "precision_multi_turn",
                    "scenario_group": f"v9-multi-{row_index:04d}",
                    "language": "en",
                    "synthetic": True,
                    "tool_expected": False,
                    "tool_context": "exact_app_runtime_v1",
                    "generator_version": GENERATOR_VERSION,
                },
            }
        )
    return rows


def _full_manager_state(manager_id: int, as_of: str) -> dict[str, Any]:
    squad = [
        (1, "Donnarumma", "GK", "starter"),
        (2, "Tarkowski", "DEF", "starter"),
        (3, "Collins", "DEF", "starter"),
        (4, "Maguire", "DEF", "starter"),
        (5, "Senesi", "DEF", "starter"),
        (6, "Mukiele", "DEF", "starter"),
        (7, "Bruno Fernandes", "MID", "starter"),
        (8, "Mbeumo", "MID", "starter"),
        (9, "Gibbs-White", "MID", "starter"),
        (10, "Watkins", "FWD", "starter"),
        (11, "Thiago", "FWD", "starter"),
        (12, "Verbruggen", "GK", "bench"),
        (13, "Calvert-Lewin", "FWD", "bench"),
        (14, "Szoboszlai", "MID", "bench"),
        (15, "Tanaka", "MID", "bench"),
    ]
    return {
        "manager_id": manager_id,
        "as_of": as_of,
        "confirmed": True,
        "requires_refresh": False,
        "bank": 0.4,
        "free_transfers": 2,
        "squad_size": 15,
        "squad": [
            {
                "player_id": player_id,
                "name": name,
                "position": position,
                "role": role,
            }
            for player_id, name, position, role in squad
        ],
        "unavailable_fields": [],
    }


def _tool_result(name: str, index: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "name": name,
        "tool_call_id": f"call_{index:03d}",
        "content": json.dumps(result, sort_keys=True, separators=(",", ":")),
    }


def _tool_metadata(route: str, index: int) -> dict[str, Any]:
    return {
        "split": "train",
        "family": "precision_tool_routing",
        "scenario_group": f"v9-tool-{route}-{index + 1:03d}",
        "language": "en",
        "synthetic": True,
        "tool_expected": True,
        "tool_context": "exact_app_runtime_v1",
        "generator_version": GENERATOR_VERSION,
    }


def _tool_prompt(lead: str, question: str, tail: str) -> str:
    return f"{_frame_question(lead, question)} {tail}"


def _tool_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(TOOL_VARIANTS):
        manager_id = 2_000 + index
        event = index % 8 + 1
        as_of = f"2026-08-{index % 20 + 1:02d}T{index % 12 + 8:02d}:00:00+00:00"
        lead = TOOL_LEADS[(index // len(TOOL_TAILS)) % len(TOOL_LEADS)]
        tail = TOOL_TAILS[index % len(TOOL_TAILS)]
        manager = _full_manager_state(manager_id, as_of)
        manager_call = _tool_call_message(
            "get_manager_state", {"manager_id": manager_id, "as_of": as_of}, 0
        )
        manager_result = _tool_result("get_manager_state", 0, manager)

        manager_questions = (
            "Give me a concise overview of all fifteen players in my current squad.",
            "Review my current squad and identify its biggest structural weakness.",
            "Check whether anyone on my bench is stronger than a current starter.",
        )
        manager_answers = (
            "Your current 15-player squad is confirmed. It has two goalkeepers, five defenders, five midfielders and three forwards, with £0.4m in the bank and two free transfers.",
            "Your current squad is legal, but its five-defender starting shape leaves stronger midfield cover on the bench than the structure normally needs. Compare the bench with every starter before locking the XI.",
            "The bench must be compared with the starters rather than treated as fixed. Szoboszlai is the strongest outfield bench option in this snapshot, so test whether he improves the legal starting XI.",
        )
        manager_variant = index % len(manager_questions)
        rows.append(
            {
                "id": f"v9-tool-manager-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead, manager_questions[manager_variant], tail
                        ),
                    },
                    manager_call,
                    manager_result,
                    {
                        "role": "assistant",
                        "content": manager_answers[manager_variant],
                    },
                ],
                "metadata": _tool_metadata("manager", index),
            }
        )

        captain = {
            "as_of": as_of,
            "event": event,
            "risk_policy": "robust",
            "captain": {"player_id": 7, "name": "Bruno Fernandes", "robust_points": 6.1},
            "vice_captain": {"player_id": 8, "name": "Mbeumo", "robust_points": 5.5},
            "recommended_lineup": {"promotions": [], "demotions": []},
            "receipt_id": f"v9-captain-{index:03d}",
            "requires_refresh": False,
        }
        compare_arguments = {
            "manager_id": manager_id,
            "event": event,
            "candidate_player_ids": [],
            "risk_policy": "robust",
            "as_of": as_of,
        }
        rows.append(
            {
                "id": f"v9-tool-captain-open-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead,
                            f"Choose the captain and vice-captain for my GW{event} team.",
                            tail,
                        ),
                    },
                    copy.deepcopy(manager_call),
                    copy.deepcopy(manager_result),
                    _tool_call_message("compare_captains", compare_arguments, 1),
                    _tool_result("compare_captains", 1, captain),
                    {
                        "role": "assistant",
                        "content": (
                            f"Captain Bruno Fernandes for GW{event}, with Mbeumo as vice-captain. "
                            "Bruno leads the robust comparison 6.1 to 5.5; those are modelled points, not guaranteed returns."
                        ),
                    },
                ],
                "metadata": _tool_metadata("captain-open", index),
            }
        )

        pair_arguments = {**compare_arguments, "candidate_player_ids": [7, 8]}
        pair_result = {
            **captain,
            "requested_comparison": {
                "candidates": [
                    {"player_id": 7, "name": "Bruno Fernandes", "robust_points": 6.1},
                    {"player_id": 8, "name": "Mbeumo", "robust_points": 5.5},
                ],
                "winner": "Bruno Fernandes",
            },
        }
        rows.append(
            {
                "id": f"v9-tool-captain-pair-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead,
                            "Compare Bruno Fernandes and Mbeumo as captain options for my team.",
                            tail,
                        ),
                    },
                    copy.deepcopy(manager_call),
                    copy.deepcopy(manager_result),
                    _tool_call_message("compare_captains", pair_arguments, 1),
                    _tool_result("compare_captains", 1, pair_result),
                    {
                        "role": "assistant",
                        "content": (
                            "Bruno Fernandes is the stronger captain in the requested comparison, "
                            "with Mbeumo second. The robust scores are 6.1 and 5.5 respectively."
                        ),
                    },
                ],
                "metadata": _tool_metadata("captain-pair", index),
            }
        )

        locked_constraints = {
            "risk_profile": "safer",
            "legal_squad_only": True,
            "locked_player_ids": [7],
        }
        locked_optimize = {
            "manager_id": manager_id,
            "start_event": event,
            "horizon": 5,
            "constraints": locked_constraints,
            "as_of": as_of,
        }
        locked_result = {
            "as_of": as_of,
            "legal": True,
            "applied_constraints": locked_constraints,
            "formation": "3-4-3",
            "roster": [player["name"] for player in manager["squad"]],
        }
        rows.append(
            {
                "id": f"v9-tool-lock-current-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead,
                            "Make my current draft safer but keep Bruno Fernandes.",
                            tail,
                        ),
                    },
                    copy.deepcopy(manager_call),
                    copy.deepcopy(manager_result),
                    _tool_call_message("optimize_squad", locked_optimize, 1),
                    _tool_result("optimize_squad", 1, locked_result),
                    {
                        "role": "assistant",
                        "content": (
                            "The safer squad is legal and keeps Bruno Fernandes locked as requested. "
                            "The applied constraints and complete 15-player roster match the returned proposal."
                        ),
                    },
                ],
                "metadata": _tool_metadata("lock-current", index),
            }
        )

        club = ("LIV", "ARS", "MCI", "CHE")[index % 4]
        club_constraints = {
            "risk_profile": "balanced",
            "legal_squad_only": True,
            "club_minimums": [{"team_short_name": club, "count": 3}],
        }
        club_optimize = {
            "manager_id": manager_id,
            "start_event": event,
            "horizon": 5,
            "constraints": club_constraints,
            "as_of": as_of,
        }
        club_result = {
            "as_of": as_of,
            "legal": True,
            "applied_constraints": club_constraints,
            "formation": "3-4-3",
            "roster": [player["name"] for player in manager["squad"]],
            "club_minimum_satisfied": club,
        }
        rows.append(
            {
                "id": f"v9-tool-club-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead,
                            f"Rebuild my GW{event} squad with at least three {club} players.",
                            tail,
                        ),
                    },
                    copy.deepcopy(manager_call),
                    copy.deepcopy(manager_result),
                    _tool_call_message("optimize_squad", club_optimize, 1),
                    _tool_result("optimize_squad", 1, club_result),
                    {
                        "role": "assistant",
                        "content": (
                            f"The rebuilt squad is legal and satisfies the minimum of three {club} players. "
                            "It uses the balanced profile and preserves the complete returned roster."
                        ),
                    },
                ],
                "metadata": _tool_metadata("club", index),
            }
        )

        haaland_id = 201
        player_constraints = {
            "risk_profile": "safer",
            "legal_squad_only": True,
            "locked_player_ids": [haaland_id],
        }
        player_optimize = {
            "manager_id": manager_id,
            "start_event": event,
            "horizon": 5,
            "constraints": player_constraints,
            "as_of": as_of,
        }
        player_result = {
            "as_of": as_of,
            "legal": True,
            "applied_constraints": player_constraints,
            "formation": "3-4-3",
            "roster": ["Haaland"] + [
                player["name"] for player in manager["squad"] if player["player_id"] != 11
            ],
        }
        rows.append(
            {
                "id": f"v9-tool-new-player-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead, "Bring Haaland into my draft and build around him.", tail
                        ),
                    },
                    copy.deepcopy(manager_call),
                    copy.deepcopy(manager_result),
                    _tool_call_message(
                        "search_players", {"query": "Haaland", "season": "2026-27"}, 1
                    ),
                    _tool_result(
                        "search_players",
                        1,
                        {
                            "candidates": [
                                {"player_id": haaland_id, "name": "Haaland", "confidence": 1.0}
                            ]
                        },
                    ),
                    _tool_call_message("optimize_squad", player_optimize, 2),
                    _tool_result("optimize_squad", 2, player_result),
                    {
                        "role": "assistant",
                        "content": (
                            "The rebuilt squad is legal and keeps Haaland locked. The applied safer "
                            "constraints and full 15-player roster come directly from the optimiser."
                        ),
                    },
                ],
                "metadata": _tool_metadata("new-player", index),
            }
        )

        current_player_constraints = {
            **locked_constraints,
            "locked_player_ids": [8],
        }
        no_search_result = {
            **locked_result,
            "applied_constraints": current_player_constraints,
            "formation": "3-5-2",
        }
        rows.append(
            {
                "id": f"v9-tool-current-player-{index + 1:03d}",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _tool_prompt(
                            lead,
                            "Rebuild around Mbeumo from my current squad without dropping him.",
                            tail,
                        ),
                    },
                    copy.deepcopy(manager_call),
                    copy.deepcopy(manager_result),
                    _tool_call_message(
                        "optimize_squad",
                        {
                            **locked_optimize,
                            "constraints": current_player_constraints,
                        },
                        1,
                    ),
                    _tool_result("optimize_squad", 1, no_search_result),
                    {
                        "role": "assistant",
                        "content": (
                            "The rebuilt legal squad keeps Mbeumo using his existing manager-state ID; "
                            "no player search was needed. Review the complete returned roster before applying it."
                        ),
                    },
                ],
                "metadata": _tool_metadata("current-player", index),
            }
        )
    return rows


def _select_replay(
    source_rows: list[dict[str, Any]], family: str, count: int, seed: int
) -> list[dict[str, Any]]:
    candidates = [
        copy.deepcopy(row)
        for row in source_rows
        if row.get("metadata", {}).get("family") == family
        and not any(message.get("tool_calls") for message in row["messages"])
    ]
    random.Random(seed).shuffle(candidates)
    if len(candidates) < count:
        raise ValueError(f"{family} has {len(candidates)} replay rows, needs {count}")
    selected = candidates[:count]
    for index, row in enumerate(selected, start=1):
        row["id"] = f"v9-replay-{family}-{index:04d}"
        row["metadata"]["family"] = f"precision_{family}"
        row["metadata"]["generator_version"] = GENERATOR_VERSION
        row["metadata"]["tool_context"] = (
            "none_for_screenshot"
            if any(isinstance(message.get("content"), list) for message in row["messages"])
            else "exact_app_runtime_v1"
        )
    return selected


def _rebase_images(row: dict[str, Any], source_dir: Path, output_dir: Path) -> None:
    for message in row["messages"]:
        if not isinstance(message.get("content"), list):
            continue
        for part in message["content"]:
            if not isinstance(part, dict) or part.get("type") != "image":
                continue
            source_path = (source_dir / str(part["path"])).resolve()
            if not source_path.exists():
                raise FileNotFoundError(source_path)
            part["path"] = Path(os.path.relpath(source_path, output_dir)).as_posix()


def build_precision_corpus(
    base_path: Path = DEFAULT_BASE,
    output_dir: Path = DEFAULT_OUTPUT,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    source_rows = _load_jsonl(base_path)
    direct = _direct_rows(seed)
    multi_turn = _multi_turn_rows(seed + 1)
    tools = _tool_rows()
    replay = _select_replay(
        source_rows, "replay_multilingual", MULTILINGUAL_REPLAY_ROWS, seed + 2
    ) + _select_replay(source_rows, "replay_multimodal", IMAGE_REPLAY_ROWS, seed + 3)
    combined = direct + multi_turn + tools + replay
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in replay:
        _rebase_images(row, base_path.parent, output_dir)
    random.Random(seed).shuffle(combined)
    validation = validate_sft_rows(combined)
    near_eval = _assert_benchmark_separation(combined)
    tool_rows = sum(
        any(message.get("tool_calls") for message in row["messages"])
        for row in combined
    )
    output_path = output_dir / "combined_train.jsonl"
    row_count, checksum = _write_jsonl(output_path, combined)
    summary = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "base_path": _display_path(base_path),
        "base_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "output_path": _display_path(output_path),
        "output_sha256": checksum,
        "rows": row_count,
        "direct_text_rows": len(direct) + len(multi_turn) + MULTILINGUAL_REPLAY_ROWS,
        "tool_rows": tool_rows,
        "image_rows": validation["image_rows"],
        "multi_turn_rows": len(multi_turn),
        "quality_scenarios": len(_direct_scenarios()),
        "variants_per_scenario": DIRECT_VARIANTS,
        "near_eval_max_similarity": round(near_eval, 4),
        "families": dict(
            sorted(Counter(str(row["metadata"]["family"]) for row in combined).items())
        ),
        "training_context": (
            "Every text row is formatted with the exact production system policy and four app "
            "tool schemas. Screenshot rows retain their tool-free vision context."
        ),
        **validation,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
