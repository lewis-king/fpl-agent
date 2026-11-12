"""Fixed grid, frozen GW2/GW3 selector-only outcome audit. Never publishes.

Two known events cannot select a season-optimal risk coefficient. The grid was
specified before scoring in this experiment; these season outcomes were already
inspected elsewhere, so this is not an untouched holdout.
"""

import argparse
import json
from pathlib import Path

from replay_weekly_selection import replay

from fplagent_engine.prospective_scoring import score_weekly_event

RECEIPTS = (
    Path(
        "data/decisions/weekly/event-2/5c47b2094a9482325c1634fd232a17ea05d5288da3b9f530f9ea826512de5511.json"
    ),
    Path(
        "data/decisions/weekly/event-3/e7f0a2a5617e0c7e96c870238f6729a57b7797d4f17ae8c17b474001bbe54889.json"
    ),
)


def run(output: Path):
    if output.exists():
        raise FileExistsError("Do not overwrite a research receipt")
    output.mkdir(parents=True)
    rows = []
    for source in RECEIPTS:
        event = json.loads(source.read_text())["decision_event"]
        score = score_weekly_event(
            event,
            decision_path=source,
            result_root=output / "scores",
            report_root=output / "reports",
        )
        actual = {r["action_id"]: r for r in score["actions"]}
        for weight in (0.0, 0.10, 0.25, 0.50):
            selection = replay(source, worst_case_weight=weight)
            selection["realized_net_points"] = actual[selection["new_action"]][
                "realized_decision_net_points"
            ]
            rows.append(selection)
    result = {
        "version": "frozen_risk_weight_replay_v1",
        "decision_authority": False,
        "rows": rows,
        "aggregate_net_points": {
            str(w): sum(r["realized_net_points"] for r in rows if r["worst_case_weight"] == w)
            for w in (0.0, 0.10, 0.25, 0.50)
        },
        "scope": "Frozen candidates and simulation metrics with exact legal state reconstruction and checked official outcomes. No new historical forecasts, roles, candidates or future transfer paths.",
        "promotion_gate": {
            "passed": False,
            "reason": "Two already-inspected events are insufficient to select risk weights; prospective full-pool tests are now frozen.",
        },
    }
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    print(
        json.dumps(
            {
                "aggregate_net_points": result["aggregate_net_points"],
                "promotion_gate": result["promotion_gate"],
            },
            indent=2,
        )
    )
