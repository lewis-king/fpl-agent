from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from .arrow import json_text, write_rows
from .catalog import sources
from .http import download
from .paths import PROCESSED, RAW

RAW_DIR = RAW / "fpl_genius" / "2025-26"
OUT_DIR = PROCESSED / "fpl_genius"


def _url(procedure: str, payload: dict) -> str:
    base = sources()["fpl_genius"]["trpc"]
    query = urllib.parse.urlencode({"input": json.dumps({"json": payload}, separators=(",", ":"))})
    return f"{base}/score.{procedure}?{query}"


def _top100_ids() -> list[str]:
    path = RAW / "solio" / "2025-26" / "leaderboards.json"
    if not path.exists():
        raise FileNotFoundError("Fetch Solio before FPL Genius; top-100 IDs come from Solio")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    board = next(item for item in payload["all"] if item["key"] == "real")
    return [str(item["id"]) for item in board["entries"]]


def _trpc_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if "error" in payload:
        raise ValueError(f"FPL Genius returned an error for {path}: {payload['error']}")
    return payload["result"]["data"]["json"]


def fetch(force: bool = False, throttle_seconds: float = 0.5) -> None:
    config = sources()["fpl_genius"]
    common = {"season": config["season"], "modelVersion": config["model_version"]}
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    hall_url = _url("getHallOfGenius", {"modelVersion": config["model_version"]})
    download(hall_url, RAW_DIR / "hall.json", force=force)

    ids = _top100_ids()
    for index in range(0, len(ids), 20):
        batch = ids[index : index + 20]
        payload = {"fplIds": batch, **common}
        destination = RAW_DIR / "summaries" / f"batch-{index // 20:02d}.json"
        download(_url("getScoredSummaries", payload), destination, force=force)
        response = _trpc_json(destination)
        if response.get("pending"):
            raise ValueError(f"Top-100 managers unexpectedly pending: {response['pending']}")

    for number, manager_id in enumerate(ids, 1):
        destination = RAW_DIR / "managers" / f"{manager_id}.json"
        if not destination.exists() or force:
            download(
                _url("getManagerScore", {"fplId": manager_id, **common}),
                destination,
                force=force,
                throttle_seconds=throttle_seconds,
            )
        payload = _trpc_json(destination)
        returned_id = str(payload.get("manager", {}).get("fplId"))
        if returned_id != manager_id:
            raise ValueError(f"Requested manager {manager_id}, received {returned_id}")
        if number % 10 == 0 or number == len(ids):
            print(f"fpl_genius: fetched {number}/{len(ids)} top managers")


def _score_fields(score: dict | None) -> dict:
    score = score or {}
    return {
        "foresight": score.get("foresight"),
        "payoff": score.get("payoff"),
        "discipline": score.get("discipline"),
        "originality": score.get("originality"),
        "contribution": score.get("contribution"),
    }


def preprocess() -> dict:
    managers = []
    transfers = []
    captaincy = []
    decisions = []
    receipts = []
    weekly_scores = []

    files = sorted((RAW_DIR / "managers").glob("*.json"), key=lambda item: int(item.stem))
    if not files:
        raise FileNotFoundError("No FPL Genius manager payloads found; run fetch first")

    for path in files:
        payload = _trpc_json(path)
        manager = payload["manager"]
        manager_id = int(manager["fplId"])
        contract = payload.get("publicContract") or {}
        moments = contract.get("moments") or {}
        managers.append(
            {
                "season": "2025-26",
                "manager_id": manager_id,
                "manager_name": manager.get("managerName"),
                "team_name": manager.get("teamName"),
                "started_event": manager.get("startedEvent"),
                "points": manager.get("summaryOverallPoints"),
                "overall_rank": manager.get("summaryOverallRank"),
                "genius_score": payload.get("totalScore"),
                "classification_label": (payload.get("classification") or {}).get("label"),
                "classification_json": json_text(payload.get("classification")),
                "score_profile_json": json_text(payload.get("scoreProfile")),
                "evidence_confidence": payload.get("evidenceConfidence"),
                "generated_at": payload.get("generatedAt"),
                "score_version": payload.get("scoreVersion"),
            }
        )

        for item in moments.get("transferMoments") or []:
            alpha = item.get("forwardAlpha") or {}
            transfers.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "event": item.get("event"),
                    "player_in": item.get("playerInName"),
                    "player_out": item.get("playerOutName"),
                    "transfer_cost": item.get("cost"),
                    "model_edge": item.get("edge"),
                    "realised_points": item.get("realisedPoints"),
                    "baseline_points": item.get("baselinePoints"),
                    "forward_alpha_1gw": alpha.get("oneWeek"),
                    "forward_alpha_3gw": alpha.get("threeWeek"),
                    "forward_alpha_5gw": alpha.get("fiveWeek"),
                    "flags_json": json_text(item.get("flags")),
                }
            )

        for item in moments.get("captaincyArc") or []:
            captaincy.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "event": item.get("event"),
                    "captain": item.get("yourCaptain"),
                    "comparison_captain": item.get("obviousCaptain"),
                    "comparison_captain_ownership": item.get("obviousCaptainOwnership"),
                    "realised_edge": item.get("edge"),
                    "was_differential": item.get("wasDifferential"),
                }
            )

        for sequence, item in enumerate(payload.get("decisionScores") or [], 1):
            components = item.get("components") or {}
            decisions.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "sequence": sequence,
                    "event": item.get("event"),
                    "decision_type": item.get("decisionType"),
                    "score_value": item.get("scoreValue"),
                    "realised_alpha": item.get("realisedAlpha"),
                    "expected_points": item.get("expectedPoints"),
                    "baseline_points": item.get("baselinePoints"),
                    "rarity_weight": item.get("rarityWeight"),
                    "evidence_confidence": item.get("evidenceConfidence"),
                    "foresight": components.get("foresight"),
                    "payoff": components.get("payoff"),
                    "discipline": components.get("discipline"),
                    "originality": components.get("originality"),
                    "reason_codes_json": json_text(item.get("reasonCodes")),
                }
            )

        for sequence, item in enumerate(contract.get("decisionReceipts") or [], 1):
            receipts.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "sequence": sequence,
                    "event": item.get("event"),
                    "decision_type": item.get("decisionType"),
                    "action_label": item.get("actionLabel"),
                    "baseline_label": item.get("baselineLabel"),
                    "data_status": item.get("dataStatus"),
                    "evidence_confidence": item.get("evidenceConfidence"),
                    **_score_fields(item.get("score")),
                    "expected_json": json_text(item.get("expected")),
                    "realised_json": json_text(item.get("realised")),
                    "reason_codes_json": json_text(item.get("reasonCodes")),
                    "record_json": json_text(item),
                }
            )

        for item in contract.get("weeklyArc") or payload.get("history") or []:
            weekly_scores.append(
                {
                    "season": "2025-26",
                    "manager_id": manager_id,
                    "event": item.get("event"),
                    "decision_score": item.get("score"),
                }
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "managers": write_rows(managers, OUT_DIR / "managers.parquet"),
        "transfers": write_rows(transfers, OUT_DIR / "transfers.parquet"),
        "captaincy": write_rows(captaincy, OUT_DIR / "captaincy.parquet"),
        "decisions": write_rows(decisions, OUT_DIR / "decisions.parquet"),
        "receipts": write_rows(receipts, OUT_DIR / "receipts.parquet"),
        "weekly_scores": write_rows(weekly_scores, OUT_DIR / "weekly_scores.parquet"),
    }
    return result

