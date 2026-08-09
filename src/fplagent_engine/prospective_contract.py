from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import latest_official_snapshot

from .artifact_lineage import (
    load_json_artifact,
    require_current_forecast,
    require_recorded_file,
)
from .deadline_pipeline import WEEKLY_DECISION_ARCHIVE_ROOT
from .decision_synthesis import DECISION_JSON as SYNTHESIZED_DECISION
from .horizon_audit import RESULTS_JSON as HORIZON_RESULTS
from .models import CURRENT_FORECAST
from .robust_search import RESULTS_JSON as ROBUST_RESULTS
from .robust_search import SHORTLIST_JSON as ROBUST_SHORTLIST

VERSION = "prospective_decision_contract_v1"


class ProspectiveContractError(ValueError):
    """A current decision cannot be frozen into a trustworthy prospective contract."""


def _aware(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProspectiveContractError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ProspectiveContractError(f"{label} must include a timezone")
    return parsed


def build_gw1_prospective_contract(
    decision: dict[str, Any],
    shortlist: dict[str, Any],
    forecast_rows: list[dict[str, Any]],
    *,
    deadline_time: str,
    maximum_candidates: int = 32,
    source_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if maximum_candidates < 2:
        raise ProspectiveContractError("GW1 prospective contract needs at least two candidates")
    created_at = str(decision["created_at"])
    if _aware(created_at, "decision created_at") > _aware(deadline_time, "GW1 deadline"):
        raise ProspectiveContractError("GW1 decision was created after the deadline")
    selected_id = str(decision["decision"]["candidate_id"])
    ranking = decision.get("ranking")
    if not isinstance(ranking, list) or len(ranking) < 2:
        raise ProspectiveContractError("GW1 synthesis ranking needs at least two candidates")
    ranked_ids = [str(row["candidate_id"]) for row in ranking]
    if selected_id != ranked_ids[0]:
        raise ProspectiveContractError("GW1 selected candidate is not first in synthesis ranking")
    selected_ids = ranked_ids[:maximum_candidates]
    candidates_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in shortlist["candidates"]
    }
    missing = set(selected_ids) - set(candidates_by_id)
    if missing:
        raise ProspectiveContractError(
            f"GW1 prospective candidates are absent from the checksum-bound shortlist: {sorted(missing)}"
        )

    action_summaries = []
    relevant_players: set[int] = set()
    ranking_by_id = {str(row["candidate_id"]): row for row in ranking}
    for candidate_id in selected_ids:
        candidate = candidates_by_id[candidate_id]
        lineup = candidate["lineups"]["1"]
        starters = list(map(int, lineup["starters"]))
        bench = list(map(int, lineup["bench_order"]))
        if len({*starters, *bench}) != 15:
            raise ProspectiveContractError(f"GW1 candidate {candidate_id} is not a 15-player partition")
        relevant_players.update(starters)
        relevant_players.update(bench)
        action_summaries.append(
            {
                "action_id": candidate_id,
                "route_type": "preseason_squad",
                "incremental_points_cost": 0,
                "total_points_cost": 0,
                "starter_player_ids": starters,
                "bench_player_ids": bench,
                "captain_player_id": int(lineup["captain"]),
                "vice_captain_player_id": int(lineup["vice_captain"]),
                "predeadline_rank": int(ranking_by_id[candidate_id]["rank"]),
                "predeadline_synthesis_regret": float(
                    ranking_by_id[candidate_id]["synthesis_regret"]
                ),
                "event_lineups": [
                    {
                        "event": 1,
                        "formation": str(lineup["formation"]),
                        "projected_points": float(lineup["expected_points"]),
                        "starter_player_ids": starters,
                        "bench_player_ids": bench,
                        "captain_player_id": int(lineup["captain"]),
                        "vice_captain_player_id": int(lineup["vice_captain"]),
                    }
                ],
            }
        )
    event_rows = {
        int(row["element"]): row
        for row in forecast_rows
        if int(row["event_number"]) == 1
    }
    if not relevant_players <= set(event_rows):
        raise ProspectiveContractError("GW1 candidate player is missing from the frozen forecast")
    event_player_forecasts = {
        str(element): {
            "element": element,
            "player_name": str(event_rows[element].get("player_name") or f"#{element}"),
            "position": str(event_rows[element]["position"]),
            "team_id": int(event_rows[element]["team_id"]),
            "expected_points": float(event_rows[element]["expected_points"]),
            "robust_points": float(
                event_rows[element].get("robust_points", event_rows[element]["expected_points"])
            ),
            "p_play": float(event_rows[element].get("p_play", 1.0)),
            "expected_minutes": (
                float(event_rows[element]["expected_minutes"])
                if event_rows[element].get("expected_minutes") is not None
                else None
            ),
        }
        for element in sorted(relevant_players)
    }
    return {
        "version": VERSION,
        "decision_type": "preseason_squad",
        "created_at": created_at,
        "decision_event": 1,
        "selected_action_id": selected_id,
        "reference_action_id": selected_ids[1],
        "reference_label": "strongest pre-deadline rejected squad",
        "action_summaries": action_summaries,
        "event_player_forecasts": event_player_forecasts,
        "deadline_time": deadline_time,
        "source_artifacts": source_artifacts or {},
        "interpretation_rule": (
            "Score every frozen finalist after official GW1 finalisation, but do not promote a "
            "forecast or policy change from one realized Gameweek."
        ),
    }


def freeze_gw1_prospective_contract(
    *,
    maximum_candidates: int = 32,
    decision_path: Path = SYNTHESIZED_DECISION,
    shortlist_path: Path = ROBUST_SHORTLIST,
    forecast_path: Path = CURRENT_FORECAST,
    archive_root: Path = WEEKLY_DECISION_ARCHIVE_ROOT,
) -> dict[str, Any]:
    decision = load_json_artifact(decision_path, "synthesized GW1 decision")
    shortlist = load_json_artifact(shortlist_path, "global robust-search shortlist")
    require_recorded_file(
        decision,
        ("source_artifacts", "robust_shortlist_sha256"),
        shortlist_path,
        "synthesized decision shortlist",
    )
    robust = load_json_artifact(ROBUST_RESULTS, "global robust-search results")
    horizon = load_json_artifact(HORIZON_RESULTS, "horizon-audit results")
    forecast_sha = require_current_forecast(
        robust,
        forecast_path,
        "global robust-search results",
        fields=("artifacts", "forecast_sha256"),
    )
    require_current_forecast(
        horizon,
        forecast_path,
        "horizon-audit results",
        fields=("artifacts", "forecast_sha256"),
    )
    official_dir, official_manifest = latest_official_snapshot()
    bootstrap_path = official_dir / "bootstrap-static.json"
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    event_rows = [row for row in bootstrap["events"] if int(row["id"]) == 1]
    if len(event_rows) != 1:
        raise ProspectiveContractError("official bootstrap has no unique GW1 event")
    deadline_time = str(event_rows[0]["deadline_time"])
    source_artifacts = {
        "synthesized_decision": str(decision_path),
        "synthesized_decision_sha256": sha256_file(decision_path),
        "robust_shortlist": str(shortlist_path),
        "robust_shortlist_sha256": sha256_file(shortlist_path),
        "forecast": str(forecast_path),
        "forecast_sha256": forecast_sha,
        "official_bootstrap": str(bootstrap_path),
        "official_bootstrap_sha256": sha256_file(bootstrap_path),
        "official_snapshot_id": str(official_manifest["snapshot_id"]),
    }
    contract = build_gw1_prospective_contract(
        decision,
        shortlist,
        pq.read_table(forecast_path).to_pylist(),
        deadline_time=deadline_time,
        maximum_candidates=maximum_candidates,
        source_artifacts=source_artifacts,
    )
    identity = {
        "version": VERSION,
        "decision_sha256": source_artifacts["synthesized_decision_sha256"],
        "shortlist_sha256": source_artifacts["robust_shortlist_sha256"],
        "forecast_sha256": forecast_sha,
        "official_bootstrap_sha256": source_artifacts["official_bootstrap_sha256"],
        "maximum_candidates": maximum_candidates,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output_path = archive_root / "event-1" / f"{fingerprint}.json"
    contract["contract_identity"] = identity
    contract["contract_fingerprint"] = fingerprint
    contract["contract_path"] = str(output_path)
    rendered = json.dumps(contract, indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise ProspectiveContractError(f"immutable GW1 prospective contract collision: {output_path}")
    if not output_path.exists():
        temporary = output_path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(output_path)
    return contract
