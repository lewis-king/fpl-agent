from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file

from .paths import MODEL_DATA, REPORTS
from .prospective_dashboard import RESULTS as PROSPECTIVE_SCOREBOARD

VERSION = "forecast_challenger_registry_v1"
OUTPUT_ROOT = MODEL_DATA / VERSION
RESULTS = OUTPUT_ROOT / "registry.json"
REPORT = REPORTS / "forecast-challenger-registry.md"


@dataclass(frozen=True)
class ChallengerSpec:
    key: str
    label: str
    scope: str
    artifact: Path
    gate_path: tuple[str, ...]
    prospective_key: str | None


SPECS = (
    ChallengerSpec(
        "appearance_calibration",
        "Appearance calibration",
        "participation",
        MODEL_DATA / "appearance_challenger_v2" / "policy-replay.json",
        ("gate", "passed"),
        None,
    ),
    ChallengerSpec(
        "preseason_role_appearance",
        "Longer-horizon role appearance",
        "participation",
        MODEL_DATA / "appearance_role_v1" / "policy-replay.json",
        ("promotion_ready",),
        None,
    ),
    ChallengerSpec(
        "market_goal_rates",
        "Pre-closing market goal rates",
        "team scoring rates",
        MODEL_DATA / "market_transfer_policy_v1" / "results.json",
        ("gate", "passed"),
        "market_goal_rates",
    ),
    ChallengerSpec(
        "return_distribution",
        "Distribution-aware player returns",
        "player returns",
        MODEL_DATA / "return_distribution_v1" / "results.json",
        ("gate", "passed"),
        None,
    ),
    ChallengerSpec(
        "form_reversion",
        "Process-confirmed mean reversion",
        "player returns and transfer timing",
        MODEL_DATA / "form_reversion_v1" / "results.json",
        ("sequential_replay", "gate", "passed"),
        "form_reversion",
    ),
)


def _nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _prospective_rows(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not path.is_file():
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != "prospective_scoreboard_v1":
        raise ValueError("prospective scoreboard has an unsupported contract")
    return dict(payload.get("challenger_summaries", {})), {
        "path": str(path),
        "sha256": sha256_file(path),
    }


def _promotion_checks(
    *, historical_passed: bool, prospective: dict[str, Any] | None, paired: bool
) -> dict[str, bool]:
    events = int(prospective.get("events", 0)) if prospective else 0
    mean = float(prospective.get("mean_delta_to_champion", -math.inf)) if prospective else -math.inf
    lower = prospective.get("ci95_low") if prospective else None
    return {
        "historical_gate_passed": historical_passed,
        "paired_live_policy_is_frozen": paired,
        "at_least_ten_prospective_events": events >= 10,
        "positive_prospective_mean": mean > 0.0,
        "prospective_lower_bound_above_minus_point_two_five": (
            lower is not None and float(lower) > -0.25
        ),
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Forecast challenger registry",
        "",
        f"Generated: {result['created_at']}",
        "",
        (
            "The direct expected-points forecast remains champion. This registry is the only "
            "promotion board; experiment point estimates elsewhere have no production authority."
        ),
        "",
        "| Challenger | Scope | Historical | Prospective | Registry status |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in result["challengers"]:
        lines.append(
            f"| {row['label']} | {row['scope']} | "
            f"{'pass' if row['historical_gate_passed'] else 'fail'} | "
            f"{row['prospective_evidence']['events']} | {row['registry_status']} |"
        )
    lines.extend(
        [
            "",
            "Promotion is always manual and scheduled even after every check passes.",
            "",
        ]
    )
    return "\n".join(lines)


def build_challenger_registry(
    *,
    specs: tuple[ChallengerSpec, ...] = SPECS,
    prospective_scoreboard: Path = PROSPECTIVE_SCOREBOARD,
    output_path: Path = RESULTS,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    input_identity = {
        "challengers": [
            {
                "key": spec.key,
                "path": str(spec.artifact),
                "sha256": sha256_file(spec.artifact) if spec.artifact.is_file() else None,
            }
            for spec in specs
        ],
        "prospective_scoreboard": {
            "path": str(prospective_scoreboard),
            "sha256": (
                sha256_file(prospective_scoreboard)
                if prospective_scoreboard.is_file()
                else None
            ),
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(input_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if output_path.is_file():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if (
            existing.get("version") == VERSION
            and existing.get("input_fingerprint") == fingerprint
        ):
            return {
                **existing,
                "receipt_path": str(output_path),
                "receipt_sha256": sha256_file(output_path),
                "reused": True,
            }
    prospective, scoreboard_lineage = _prospective_rows(prospective_scoreboard)
    rows = []
    artifacts = {}
    for spec in specs:
        if not spec.artifact.is_file():
            rows.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "scope": spec.scope,
                    "registry_status": "missing_historical_artifact",
                    "historical_gate_passed": False,
                    "prospective_evidence": {"events": 0},
                    "promotion_gate": {"passed": False, "checks": {}},
                    "decision_authority": False,
                }
            )
            continue
        payload = json.loads(spec.artifact.read_text(encoding="utf-8"))
        historical_passed = _nested(payload, spec.gate_path) is True
        prospective_row = (
            dict(prospective.get(spec.prospective_key, {}))
            if spec.prospective_key
            else {}
        )
        paired = spec.prospective_key is not None
        checks = _promotion_checks(
            historical_passed=historical_passed,
            prospective=prospective_row,
            paired=paired,
        )
        gate_passed = all(checks.values())
        status = (
            "eligible_for_scheduled_review"
            if gate_passed
            else "historical_reject"
            if not historical_passed
            else "awaiting_prospective_evidence"
        )
        artifact_key = f"{spec.key}_artifact"
        artifacts[artifact_key] = str(spec.artifact)
        artifacts[f"{artifact_key}_sha256"] = sha256_file(spec.artifact)
        rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "scope": spec.scope,
                "registry_status": status,
                "historical_gate_passed": historical_passed,
                "historical_verdict": payload.get("verdict") or payload.get("status"),
                "prospective_policy_key": spec.prospective_key,
                "prospective_evidence": {"events": 0, **prospective_row},
                "promotion_gate": {
                    "passed": gate_passed,
                    "checks": checks,
                    "automatic_promotion": False,
                },
                "decision_authority": False,
            }
        )
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "input_fingerprint": fingerprint,
        "status": "ready",
        "production_champion": "direct_expected_points",
        "production_changed": False,
        "automatic_promotion": False,
        "challengers": rows,
        "summary": {
            "challengers": len(rows),
            "historical_passes": sum(row["historical_gate_passed"] for row in rows),
            "eligible_for_scheduled_review": sum(
                row["promotion_gate"]["passed"] for row in rows
            ),
        },
        "artifacts": artifacts,
        "prospective_scoreboard": scoreboard_lineage,
        "policy": (
            "A challenger must pass its frozen historical gate and ten paired prospective events "
            "with a positive mean and declared downside bound. Passing opens a scheduled review; "
            "it never mutates production automatically."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(_render(result), encoding="utf-8")
    temporary_report.replace(report_path)
    return {
        **result,
        "receipt_path": str(output_path),
        "receipt_sha256": sha256_file(output_path),
        "reused": False,
    }
