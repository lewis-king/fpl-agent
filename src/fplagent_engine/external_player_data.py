from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS

from .paths import MODEL_DATA, REPORTS

VERSION = "external_player_data_v2"
OUTPUT_DIR = MODEL_DATA / "external_player_data_v1"
RECEIPT = OUTPUT_DIR / "receipt.json"
REPORT = REPORTS / "independent-player-event-data.md"
UNDERSTAT_RESULTS = MODEL_DATA / "understat_preseason_v1" / "results.json"
SOFASCORE_RECEIPT = MANIFESTS / "sofascore-player-events-current.json"
SOFASCORE_POLICY = MODEL_DATA / "sofascore_event_policy_v1" / "results.json"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def build_external_player_data_receipt(
    *,
    understat_results_path: Path = UNDERSTAT_RESULTS,
    sofascore_receipt_path: Path = SOFASCORE_RECEIPT,
    sofascore_policy_path: Path = SOFASCORE_POLICY,
    output_path: Path = RECEIPT,
    report_path: Path = REPORT,
) -> dict[str, Any]:
    understat = _load(understat_results_path)
    sofascore = _load(sofascore_receipt_path)
    sofa_policy = _load(sofascore_policy_path)
    providers = []
    if understat:
        providers.append("Understat")
    if sofascore:
        providers.append("SofaScore")
    understat_gate = bool((understat or {}).get("gate", {}).get("passed"))
    sofa_gate = bool((sofa_policy or {}).get("gate", {}).get("passed"))
    current_sofa_mapping = dict((sofascore or {}).get("mapping") or {})
    frozen_mapping_coverage = (sofa_policy or {}).get("frozen_test", {}).get("mapping_coverage")
    sofa_mapping = {
        "current": current_sofa_mapping,
        "historical_frozen_rate": frozen_mapping_coverage,
        "fail_closed": bool(current_sofa_mapping.get("fail_closed")),
        "current_has_no_finished_events": int((sofascore or {}).get("finished_events") or 0) == 0,
    }
    mapping_ok = bool(
        sofascore
        and sofa_mapping["fail_closed"]
        and frozen_mapping_coverage is not None
        and float(frozen_mapping_coverage) >= 0.80
    )
    time_forward_ok = bool(
        understat and sofa_policy and (sofa_policy.get("point_in_time") or {}).get("passed")
    )
    legal_lift = understat_gate and sofa_gate
    checks = {
        "two_independent_live_sources": len(providers) >= 2,
        "stable_fail_closed_player_mapping": mapping_ok,
        "point_in_time_folds_for_both_sources": time_forward_ok,
        "legal_policy_lift_for_both_sources": legal_lift,
    }
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "providers": providers,
        "current": bool(understat and sofascore),
        "historical_time_forward_backtest": time_forward_ok,
        "legal_policy_lift": legal_lift,
        "passed": all(checks.values()),
        "checks": checks,
        "decision_authority": False,
        "provider_evidence": {
            "Understat": {
                "available": understat is not None,
                "legal_policy_gate": understat_gate,
                "path": str(understat_results_path),
                "sha256": sha256_file(understat_results_path) if understat else None,
            },
            "SofaScore": {
                "available": sofascore is not None,
                "mapping": sofa_mapping,
                "legal_policy_gate": sofa_gate,
                "receipt_path": str(sofascore_receipt_path),
                "receipt_sha256": sha256_file(sofascore_receipt_path) if sofascore else None,
                "policy_path": str(sofascore_policy_path),
                "policy_sha256": sha256_file(sofascore_policy_path) if sofa_policy else None,
            },
        },
        "promotion_contract": (
            "Each source must independently improve an identical timestamp-safe legal-policy "
            "replay. Two available feeds alone are not permission to change production."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    lines = [
        "# Independent player-event data gate",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Verdict:** {'PASS' if result['passed'] else 'HOLD SHADOW'}  ",
        "**Production authority:** none",
        "",
        "| Check | State |",
        "|---|---|",
        *[
            f"| {name.replace('_', ' ')} | {'PASS' if passed else 'WAIT'} |"
            for name, passed in checks.items()
        ],
        "",
        result["promotion_contract"],
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return result
