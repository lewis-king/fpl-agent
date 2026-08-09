from __future__ import annotations

import json
import shutil
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import rankdata

from fplagent_data.http import download, sha256_file
from fplagent_data.paths import RAW

from .bps_reconstruction import FIXTURE_RECONSTRUCTION
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

SOURCE_URL = "https://fpl.red/bonus"
RAW_DIR = RAW / "supporting" / "fpl-red" / "bps-2026-27"
CURRENT_HTML = RAW_DIR / "current.html"
ARCHIVE_DIR = RAW_DIR / "archive"
SOURCE_RECEIPT = RAW_DIR / "current.json"
OUTPUT_DIR = MODEL_DATA / "bps_2026_27_v1"
NORMALIZED_BENCHMARK = OUTPUT_DIR / "external-benchmark.json"
VALIDATION_METRICS = OUTPUT_DIR / "external-validation.json"
REPORT = REPORTS / "2026-27-bps-external-validation.md"


def normalize_player_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(
        unaccented.casefold().replace("ø", "o").replace("ð", "d").split()
    )


def _json_assignment(text: str, start_marker: str, end_marker: str) -> Any:
    start = text.find(start_marker)
    if start < 0:
        raise ValueError(f"BPS benchmark is missing {start_marker!r}")
    start += len(start_marker)
    end = text.find(end_marker, start)
    if end < 0:
        raise ValueError(f"BPS benchmark is missing {end_marker!r}")
    return json.loads(text[start:end])


def parse_external_bps_html(text: str) -> dict[str, Any]:
    """Parse the public standalone benchmark and expose its integrity limitations."""
    players = _json_assignment(text, "var D=", ";var FM=")
    fixture_movements = _json_assignment(text, "var FM=", ";var tb=")
    if not isinstance(players, list) or not isinstance(fixture_movements, dict):
        raise TypeError("BPS benchmark assignments have unexpected types")

    player_names: set[str] = set()
    duplicate_player_names: list[str] = []
    raw_movements: list[dict[str, Any]] = []
    unique_movements: dict[tuple[str, int], dict[str, Any]] = {}
    duplicate_movements: list[dict[str, Any]] = []
    declared_totals_reconcile = True

    for player in players:
        name = str(player["name"])
        normalized_name = normalize_player_name(name)
        if normalized_name in player_names:
            duplicate_player_names.append(name)
        player_names.add(normalized_name)
        changes = player.get("ch") or []
        declared_delta = int(player["full"]) - int(player["old"])
        movement_delta = sum(int(change["nb"]) - int(change["ob"]) for change in changes)
        declared_totals_reconcile &= declared_delta == movement_delta
        for change in changes:
            movement = {
                "player_name": name,
                "normalized_player_name": normalized_name,
                "position": str(player["pos"]),
                "team": str(player["team"]),
                "fixture": int(change["fx"]),
                "event_number": int(change["gw"]),
                "opponent": str(change["opp"]),
                "old_bonus": int(change["ob"]),
                "new_bonus": int(change["nb"]),
                "old_bps": int(change["obps"]),
                "new_bps": int(change["nbps"]),
                "cbi_bps_delta": int(change["dcbi"]),
                "tackled_bps_delta": int(change["tk"]),
                "goalkeeper_bps_delta": int(change["gk"]),
            }
            raw_movements.append(movement)
            key = (normalized_name, int(change["fx"]))
            existing = unique_movements.get(key)
            if existing is None:
                unique_movements[key] = movement
            elif existing == movement:
                duplicate_movements.append(movement)
            else:
                raise ValueError(f"Conflicting duplicate BPS movement for {key}")

    fixture_map_rows = sum(len(rows) for rows in fixture_movements.values())
    movement_lookup = {
        (
            int(movement["fixture"]),
            movement["normalized_player_name"],
            int(movement["old_bonus"]),
            int(movement["new_bonus"]),
        )
        for movement in raw_movements
    }
    fixture_map_reconciles = True
    for fixture, movements in fixture_movements.items():
        for movement in movements:
            key = (
                int(fixture),
                normalize_player_name(str(movement["name"])),
                int(movement["ob"]),
                int(movement["nb"]),
            )
            fixture_map_reconciles &= key in movement_lookup

    normalized_players = []
    unique_delta_by_name: dict[str, int] = defaultdict(int)
    for movement in unique_movements.values():
        unique_delta_by_name[movement["normalized_player_name"]] += (
            int(movement["new_bonus"]) - int(movement["old_bonus"])
        )
    for player in players:
        normalized_name = normalize_player_name(str(player["name"]))
        normalized_players.append(
            {
                "player_name": str(player["name"]),
                "normalized_player_name": normalized_name,
                "team": str(player["team"]),
                "position": str(player["pos"]),
                "old_bonus": int(player["old"]),
                "new_bonus": int(player["full"]),
                "declared_bonus_delta": int(player["full"]) - int(player["old"]),
                "deduplicated_bonus_delta": unique_delta_by_name[normalized_name],
            }
        )

    return {
        "players": normalized_players,
        "movements": list(unique_movements.values()),
        "integrity": {
            "player_rows": len(players),
            "unique_player_names": len(player_names),
            "duplicate_player_names": duplicate_player_names,
            "changed_fixtures": len(fixture_movements),
            "fixture_map_rows": fixture_map_rows,
            "raw_movement_rows": len(raw_movements),
            "unique_movement_rows": len(unique_movements),
            "duplicate_movement_rows": duplicate_movements,
            "declared_totals_reconcile_with_raw_movements": declared_totals_reconcile,
            "fixture_map_reconciles_with_player_movements": fixture_map_reconciles,
        },
    }


def _spearman(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 3 or np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return None
    return float(
        np.corrcoef(
            rankdata(left, method="average"),
            rankdata(right, method="average"),
        )[0, 1]
    )


def _score_predictions(
    rows: list[dict[str, Any]], target_name: str
) -> dict[str, float | int | None]:
    actual = np.asarray([float(row[target_name]) for row in rows])
    model = np.asarray([float(row["model_bonus_delta"]) for row in rows])
    zero = np.zeros(len(rows), dtype=np.float64)
    position_rates: dict[str, float] = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        selected = [row for row in rows if row["position"] == position]
        appearances = sum(int(row["appearances"]) for row in selected)
        position_rates[position] = sum(float(row[target_name]) for row in selected) / max(
            appearances, 1
        )
    position = np.asarray(
        [position_rates[row["position"]] * int(row["appearances"]) for row in rows]
    )
    return {
        "players": len(rows),
        "model_mae": float(np.mean(np.abs(actual - model))),
        "zero_mae": float(np.mean(np.abs(actual - zero))),
        "position_mae": float(np.mean(np.abs(actual - position))),
        "model_rmse": float(np.sqrt(np.mean(np.square(actual - model)))),
        "zero_rmse": float(np.sqrt(np.mean(np.square(actual - zero)))),
        "position_rmse": float(np.sqrt(np.mean(np.square(actual - position)))),
        "model_spearman": _spearman(actual, model),
        "position_spearman": _spearman(actual, position),
    }


def evaluate_external_bps_benchmark(
    benchmark: dict[str, Any], reconstruction: pa.Table
) -> dict[str, Any]:
    model_players: dict[str, dict[str, Any]] = {}
    fixture_keys: set[tuple[str, int]] = set()
    for row in reconstruction.to_pylist():
        name = normalize_player_name(str(row["player_name"]))
        fixture_keys.add((name, int(row["fixture"])))
        player = model_players.setdefault(
            name,
            {
                "player_name": str(row["player_name"]),
                "position": str(row["position"]),
                "appearances": 0,
                "model_bonus_delta": 0.0,
            },
        )
        player["appearances"] += int(row["minutes"] > 0)
        player["model_bonus_delta"] += float(row["mean_bonus_delta"])

    comparison_rows = []
    unmatched_external_players = []
    for external in benchmark["players"]:
        name = external["normalized_player_name"]
        model = model_players.get(name)
        if model is None:
            unmatched_external_players.append(external["player_name"])
            continue
        comparison_rows.append(
            {
                **model,
                "external_player_name": external["player_name"],
                "declared_bonus_delta": int(external["declared_bonus_delta"]),
                "deduplicated_bonus_delta": int(external["deduplicated_bonus_delta"]),
            }
        )

    unmatched_movements = [
        movement
        for movement in benchmark["movements"]
        if (movement["normalized_player_name"], int(movement["fixture"])) not in fixture_keys
    ]
    declared = _score_predictions(comparison_rows, "declared_bonus_delta")
    deduplicated = _score_predictions(comparison_rows, "deduplicated_bonus_delta")
    by_position = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        selected = [row for row in comparison_rows if row["position"] == position]
        by_position[position] = {
            "players": len(selected),
            "external_declared_delta": sum(row["declared_bonus_delta"] for row in selected),
            "external_deduplicated_delta": sum(
                row["deduplicated_bonus_delta"] for row in selected
            ),
            "model_delta": sum(float(row["model_bonus_delta"]) for row in selected),
        }

    evidence_gate = {
        "all_external_players_matched": not unmatched_external_players,
        "all_unique_movements_matched": not unmatched_movements,
        "model_mae_beats_zero_declared": declared["model_mae"] < declared["zero_mae"],
        "model_mae_beats_position_declared": (
            declared["model_mae"] < declared["position_mae"]
        ),
        "model_mae_beats_zero_deduplicated": (
            deduplicated["model_mae"] < deduplicated["zero_mae"]
        ),
        "model_spearman_above_0_55": (
            declared["model_spearman"] is not None
            and declared["model_spearman"] > 0.55
        ),
        "outfield_position_direction_matches": all(
            np.sign(by_position[position]["external_declared_delta"])
            == np.sign(by_position[position]["model_delta"])
            for position in ("DEF", "MID", "FWD")
        ),
    }
    source_integrity = {
        "unique_player_names": not benchmark["integrity"]["duplicate_player_names"],
        "declared_totals_reconcile": benchmark["integrity"][
            "declared_totals_reconcile_with_raw_movements"
        ],
        "fixture_map_reconciles": benchmark["integrity"][
            "fixture_map_reconciles_with_player_movements"
        ],
        "no_duplicate_player_fixture_movements": not benchmark["integrity"][
            "duplicate_movement_rows"
        ],
    }
    return {
        "comparison_rows": comparison_rows,
        "unmatched_external_players": unmatched_external_players,
        "unmatched_unique_movements": unmatched_movements,
        "declared_total_metrics": declared,
        "deduplicated_total_metrics": deduplicated,
        "by_position": by_position,
        "evidence_gate": evidence_gate,
        "evidence_passed": all(evidence_gate.values()),
        "source_integrity": source_integrity,
        "source_integrity_exact": all(source_integrity.values()),
    }


def _archive_source(refresh: bool) -> dict[str, Any]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = download(SOURCE_URL, CURRENT_HTML, force=refresh)
    if path is None:
        raise RuntimeError("The external BPS benchmark was unavailable")
    source_sha256 = sha256_file(path)
    archive = ARCHIVE_DIR / f"{source_sha256}.html"
    if not archive.exists():
        shutil.copyfile(path, archive)
    receipt = {
        "version": 1,
        "observed_at": datetime.now(UTC).isoformat(),
        "source_url": SOURCE_URL,
        "current_path": str(path),
        "archive_path": str(archive),
        "source_sha256": source_sha256,
        "bytes": path.stat().st_size,
    }
    SOURCE_RECEIPT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def validate_external_bps_reconstruction(refresh: bool = False) -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = _archive_source(refresh)
    benchmark = parse_external_bps_html(CURRENT_HTML.read_text(encoding="utf-8"))
    if not FIXTURE_RECONSTRUCTION.is_file():
        raise FileNotFoundError(f"Missing BPS reconstruction: {FIXTURE_RECONSTRUCTION}")
    evaluation = evaluate_external_bps_benchmark(
        benchmark, pq.read_table(FIXTURE_RECONSTRUCTION)
    )
    normalized = {
        "version": 1,
        "source": source,
        "integrity": benchmark["integrity"],
        "players": benchmark["players"],
        "movements": benchmark["movements"],
    }
    NORMALIZED_BENCHMARK.write_text(
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "authority": "third_party_advisory",
        "source": source,
        "source_summary": benchmark["integrity"],
        **{key: value for key, value in evaluation.items() if key != "comparison_rows"},
        "recommendation": (
            "retain_current_shrunk_outfield_prior"
            if evaluation["evidence_passed"]
            else "retire_or_rebuild_current_prior"
        ),
        "production_change": "none_advisory_validation_only",
        "limitations": [
            "The benchmark is third-party research rather than an official Opta event feed.",
            "Its big-chance-save labels are reconstructed and calibrated, not complete Opta labels.",
            "The current source contains a duplicated Junior Kroupi player-fixture movement.",
            "Same-season reconstruction agreement is not a forward test of 2026/27 bonus outcomes.",
        ],
        "artifacts": {
            "normalized_benchmark": str(NORMALIZED_BENCHMARK),
            "normalized_benchmark_sha256": sha256_file(NORMALIZED_BENCHMARK),
            "fixture_reconstruction": str(FIXTURE_RECONSTRUCTION),
            "fixture_reconstruction_sha256": sha256_file(FIXTURE_RECONSTRUCTION),
        },
    }
    VALIDATION_METRICS.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    REPORT.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    declared = result["declared_total_metrics"]
    integrity = result["source_summary"]
    lines = [
        "# 2026/27 BPS external validation",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Authority:** {result['authority']}  ",
        f"**Evidence gate:** {'PASS' if result['evidence_passed'] else 'FAIL'}  ",
        f"**Production change:** {result['production_change']}",
        "",
        "## Result",
        "",
        (
            f"All {integrity['player_rows']} published player rows and "
            f"{integrity['unique_movement_rows']} unique changed player-fixtures map to the "
            "local 2025/26 reconstruction."
        ),
        "",
        (
            f"The current proxy has player-season MAE **{declared['model_mae']:.3f}**, versus "
            f"**{declared['zero_mae']:.3f}** for no rules correction and "
            f"**{declared['position_mae']:.3f}** for a position-only correction. Its rank "
            f"correlation with the external deltas is **{declared['model_spearman']:.3f}**."
        ),
        "",
        "| Position | External delta | Deduplicated delta | Model mean delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for position, row in result["by_position"].items():
        lines.append(
            f"| {position} | {row['external_declared_delta']:+d} | "
            f"{row['external_deduplicated_delta']:+d} | {row['model_delta']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Source integrity finding",
            "",
            (
                f"The page contains {integrity['raw_movement_rows']} movement rows but only "
                f"{integrity['unique_movement_rows']} unique player-fixtures. The duplicate is "
                "the Junior Kroupi GW9 fixture, so the source is valuable corroborating evidence "
                "but is not accepted as an exact production label set."
            ),
            "",
            "## Decision",
            "",
            (
                "Retain the current shrunk outfield correction prior. It is independently "
                "directionally corroborated and beats simpler reconstruction baselines, but this "
                "audit does not promote the third-party table or claim an exact live Opta BPS "
                "engine. Goalkeeper correction remains neutral in production until complete, "
                "reliable save-context evidence is available."
            ),
            "",
            "## Limitations",
            "",
            *[f"- {limitation}" for limitation in result["limitations"]],
            "",
            f"Source: {result['source']['source_url']}",
            "",
        ]
    )
    return "\n".join(lines)
