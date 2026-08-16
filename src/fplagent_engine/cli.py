from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplagent_data.database import build_catalog

from .adaptive_preseason import run_adaptive_preseason_stress
from .appearance_audit import audit_appearance_reliability
from .appearance_challenger import run_appearance_challenger
from .appearance_policy_replay import (
    retire_failed_appearance_calibration,
    run_appearance_policy_replay,
)
from .appearance_role_challenger import (
    run_role_appearance_challenger,
    run_role_appearance_policy_replay,
)
from .attacking_chance_challenger import run_attacking_chance_challenger
from .audit import audit_features
from .availability_watch import audit_availability_watch
from .bench_allocation_audit import run_bench_allocation_audit
from .bench_audit import run_bench_audit
from .bench_history import run_historical_bench_depth_audit
from .betfair_calibration import run_betfair_exchange_calibration
from .bps_external_validation import validate_external_bps_reconstruction
from .bps_reconstruction import reconstruct_2026_27_bps
from .captain_return_challenger import run_captain_return_replay
from .challenger_registry import build_challenger_registry
from .chip_schedule_history import build_historical_chip_schedule_opportunities
from .component_backtest import run_component_player_backtest
from .component_candidates import generate_component_candidates
from .component_models import forecast_components, train_component_models
from .component_simulator import run_component_tournament, train_goal_model
from .current_squad_audit import run_current_squad_audit
from .deadline_evidence import audit_deadline_evidence
from .deadline_pack import build_deadline_pack
from .deadline_pipeline import run_weekly_deadline_pipeline
from .decision_synthesis import run_decision_synthesis
from .distribution_calibration import build_distribution_scoreboard
from .external_player_data import build_external_player_data_receipt
from .features import build as build_features
from .fixture_ablation import run_fixture_ablation
from .form_reversion import run_form_reversion_challenger
from .horizon_audit import run_horizon_audit
from .horizon_decay_replay import run_horizon_decay_replay
from .lead_time_challenger import run_lead_time_challenger
from .market_feature_challenger import run_market_feature_challenger
from .market_odds import (
    build_current_market_goal_rates,
    build_historical_market_goal_rates,
    current_season_source_available,
)
from .market_policy_replay import run_market_goal_policy_replay
from .market_transfer_replay import run_market_transfer_replay
from .mini_league import run_mini_league_shadow
from .models import forecast, require_cuda, train
from .one_swap_audit import run_one_swap_audit
from .openfpl_benchmark import run_openfpl_matched_benchmark
from .optimizer import select_initial_squad
from .participation_scoreboard import build_participation_scoreboard
from .picker_backtest import evaluate_picker
from .preseason_pipeline import run_gw1_deadline_pipeline
from .preseason_role_scenario import run_preseason_role_scenario_audit
from .preseason_role_threshold import run_preseason_role_threshold_audit
from .price_liquidity import run_price_liquidity_calibration
from .promotion import promote_gw1_squad
from .prospective_2026 import build_2026_prospective_scoreboard
from .prospective_contract import freeze_gw1_prospective_contract
from .prospective_dashboard import build_prospective_scoreboard
from .prospective_scoring import score_weekly_event
from .return_distribution import run_return_distribution_challenger
from .robust_search import run_robust_search
from .role_residual_challenger import run_role_residual_challenger
from .rules_audit import audit_2026_27_rules
from .schedule_rearrangement import build_rearrangement_model
from .schedule_scenarios import build_schedule_receipt
from .sofascore_event_challenger import run_sofascore_event_policy_replay
from .sota_readiness import build_sota_readiness_audit
from .squad_chip_replay import run_squad_chip_retention_replay
from .structure_stress import run_structure_stress
from .synthesis_selector_replay import run_synthesis_selector_replay
from .team_chip_replay import run_team_chip_retention_replay
from .tournament import run_tournament
from .transfer_value import run_transfer_value_calibration
from .understat_challenger import run_understat_challenger
from .weekly_rehearsal import run_weekly_rehearsal
from .whitepaper import build_algorithm_whitepaper


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="fplagent")
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--horizon", type=int, default=8)
    audit = commands.add_parser("audit")
    audit.add_argument("--horizon", type=int, default=8)
    commands.add_parser("gpu-check")
    commands.add_parser("train")
    commands.add_parser("forecast")
    commands.add_parser("backtest-picker")
    commands.add_parser("fixture-ablation")
    market = commands.add_parser("audit-market-goals")
    market.add_argument("--refresh", action="store_true")
    current_market = commands.add_parser("collect-current-market-goals")
    current_market.add_argument("--event", type=int)
    current_market.add_argument("--horizon", type=int, default=5)
    commands.add_parser("replay-market-goals")
    commands.add_parser("replay-market-transfers")
    commands.add_parser("calibrate-betfair-exchange")
    commands.add_parser("backtest-market-features")
    commands.add_parser("backtest-attacking-chance")
    commands.add_parser("backtest-understat")
    commands.add_parser("backtest-sofascore-events")
    commands.add_parser("backtest-return-distribution")
    commands.add_parser("replay-captain-returns")
    commands.add_parser("replay-form-reversion")
    commands.add_parser("calibrate-horizon-decay")
    commands.add_parser("calibrate-synthesis-selector")
    commands.add_parser("audit-structure-stress")
    commands.add_parser("build-deadline-pack")
    commands.add_parser("audit-sota-readiness")
    commands.add_parser("audit-external-player-data")
    openfpl = commands.add_parser("benchmark-openfpl")
    openfpl.add_argument("--rebuild", action="store_true")
    openfpl.add_argument("--top-models", type=int, default=10)
    commands.add_parser("prospective-2026-scoreboard")
    commands.add_parser("distribution-scoreboard")
    commands.add_parser("calibrate-price-liquidity")
    commands.add_parser("build-algorithm-whitepaper")
    commands.add_parser("backtest-role-residual")
    commands.add_parser("backtest-lead-time")
    commands.add_parser("stress-adaptive-preseason")
    squad = commands.add_parser("squad")
    squad.add_argument("--stability-samples", type=int, default=20)
    tournament = commands.add_parser("tournament")
    tournament.add_argument("--candidates", type=int, default=128)
    tournament.add_argument("--selection-simulations", type=int, default=5_000)
    tournament.add_argument("--holdout-simulations", type=int, default=25_000)
    tournament.add_argument("--seed", type=int, default=20260802)
    component_train = commands.add_parser("train-components")
    component_train.add_argument("--force", action="store_true")
    component_train.add_argument("--seed", type=int, default=20260802)
    event_components = commands.add_parser("train-component-events")
    event_components.add_argument("--force-targets", action="store_true")
    event_components.add_argument("--seed", type=int, default=20260802)
    commands.add_parser("forecast-components")
    commands.add_parser("component-candidates")
    component_backtest = commands.add_parser("backtest-components")
    component_backtest.add_argument("--seed", type=int, default=20260802)
    component = commands.add_parser("component-tournament")
    component.add_argument("--simulations", type=int, default=25_000)
    component.add_argument("--seed", type=int, default=20260802)
    component.add_argument("--force-goal-model", action="store_true")
    bench_audit = commands.add_parser("bench-audit")
    bench_audit.add_argument("--simulations", type=int, default=25_000)
    bench_audit.add_argument("--seed", type=int, default=20260803)
    bench_allocation = commands.add_parser("audit-bench-allocation")
    bench_allocation.add_argument("--simulations", type=int, default=25_000)
    bench_allocation.add_argument("--five-week-seed", type=int, default=20260818)
    bench_allocation.add_argument("--eight-week-seed", type=int, default=20260820)
    bench_allocation.add_argument("--top-historical-band", type=int, default=24)
    bench_history = commands.add_parser("audit-bench-history")
    bench_history.add_argument("--refresh-forecasts", action="store_true")
    current_squad_audit = commands.add_parser("audit-current-squad")
    current_squad_audit.add_argument("--selection-simulations", type=int, default=5_000)
    current_squad_audit.add_argument("--holdout-simulations", type=int, default=25_000)
    current_squad_audit.add_argument("--finalists", type=int, default=64)
    current_squad_audit.add_argument("--selection-seed", type=int, default=20260810)
    current_squad_audit.add_argument("--holdout-seed", type=int, default=20260811)
    preseason_role = commands.add_parser("audit-preseason-role")
    preseason_role.add_argument("--selection-simulations", type=int, default=5_000)
    preseason_role.add_argument("--holdout-simulations", type=int, default=25_000)
    preseason_role.add_argument("--finalists", type=int, default=64)
    preseason_role.add_argument("--selection-seed", type=int, default=20260812)
    preseason_role.add_argument("--holdout-seed", type=int, default=20260813)
    preseason_role.add_argument("--maximum-candidates", type=int)
    preseason_threshold = commands.add_parser("audit-preseason-threshold")
    preseason_threshold.add_argument("--selection-simulations", type=int, default=5_000)
    preseason_threshold.add_argument("--holdout-simulations", type=int, default=25_000)
    preseason_threshold.add_argument("--selection-seed", type=int, default=20260814)
    preseason_threshold.add_argument("--holdout-seed", type=int, default=20260815)
    one_swap = commands.add_parser("audit-one-swaps")
    one_swap.add_argument("--proxy-squads", type=int, default=512)
    one_swap.add_argument("--selection-simulations", type=int, default=5_000)
    one_swap.add_argument("--holdout-simulations", type=int, default=25_000)
    one_swap.add_argument("--finalists", type=int, default=64)
    one_swap.add_argument("--selection-seed", type=int, default=20260816)
    one_swap.add_argument("--holdout-seed", type=int, default=20260817)
    commands.add_parser("rules-audit")
    commands.add_parser("schedule-status")
    commands.add_parser("build-chip-schedule-history")
    commands.add_parser("build-rearrangement-model")
    commands.add_parser("replay-squad-chips")
    commands.add_parser("replay-team-chips")
    bps = commands.add_parser("reconstruct-bps")
    bps.add_argument("--simulations", type=int, default=400)
    bps.add_argument("--seed", type=int, default=20260803)
    validate_bps = commands.add_parser("validate-bps")
    validate_bps.add_argument("--refresh", action="store_true")
    commands.add_parser("audit-appearances")
    commands.add_parser("audit-appearance-challenger")
    commands.add_parser("audit-role-appearance")
    commands.add_parser("replay-role-appearance")
    appearance_replay = commands.add_parser("replay-appearance-policy")
    appearance_replay.add_argument("--position", choices=("GK", "DEF", "MID", "FWD"), default="FWD")
    appearance_retire = commands.add_parser("retire-appearance-calibration")
    appearance_retire.add_argument("--position", choices=("GK", "DEF", "MID", "FWD"), required=True)
    commands.add_parser("promote-gw1")
    robust = commands.add_parser("robust-search")
    robust.add_argument("--discovery-candidates", type=int, default=10_000)
    robust.add_argument("--screen-simulations", type=int, default=2_000)
    robust.add_argument("--shortlist", type=int, default=512)
    robust.add_argument("--selection-simulations", type=int, default=5_000)
    robust.add_argument("--finalists", type=int, default=64)
    robust.add_argument("--holdout-simulations", type=int, default=25_000)
    robust.add_argument("--discovery-seed", type=int, default=20260804)
    robust.add_argument("--selection-seed", type=int, default=20260805)
    robust.add_argument("--holdout-seed", type=int, default=20260806)
    robust.add_argument("--stress-goal-multiplier", type=float, default=1.15)
    robust.add_argument("--global-restarts", type=int, default=256)
    robust.add_argument("--evolution-population", type=int, default=256)
    robust.add_argument("--evolution-generations", type=int, default=10)
    robust.add_argument("--evolution-offspring", type=int, default=2_048)
    robust.add_argument("--minimum-seed-distance", type=int, default=3)
    horizon_audit = commands.add_parser("horizon-audit")
    horizon_audit.add_argument("--horizon-candidates", type=int, default=128)
    horizon_audit.add_argument("--horizon-neighbours", type=int, default=32)
    horizon_audit.add_argument("--horizon-neighbour-seeds", type=int, default=8)
    horizon_audit.add_argument("--selection-simulations", type=int, default=5_000)
    horizon_audit.add_argument("--finalists", type=int, default=48)
    horizon_audit.add_argument("--holdout-simulations", type=int, default=25_000)
    horizon_audit.add_argument("--candidate-seed", type=int, default=20260807)
    horizon_audit.add_argument("--selection-seed", type=int, default=20260808)
    horizon_audit.add_argument("--holdout-seed", type=int, default=20260809)
    synthesis = commands.add_parser("synthesize-gw1")
    synthesis.add_argument("--horizon-family-weight", type=float, default=0.50)
    synthesis.add_argument("--family-worst-weight", type=float, default=0.20)
    build = commands.add_parser("build-gw1")
    build.add_argument("--horizon", type=int, default=8)
    build.add_argument("--stability-samples", type=int, default=20)
    deadline_status = commands.add_parser("deadline-status")
    deadline_status.add_argument("--manager-entry-id", type=int)
    deadline_status.add_argument("--as-of")
    availability_status = commands.add_parser("availability-status")
    availability_status.add_argument("--as-of")
    deadline_run = commands.add_parser("deadline-run")
    deadline_run.add_argument("--manager-entry-id", type=int, required=True)
    deadline_run.add_argument("--horizon", type=int, default=5)
    deadline_run.add_argument("--as-of")
    deadline_run.add_argument("--reuse-latest-official", action="store_true")
    deadline_run.add_argument("--alternatives-per-transfer-count", type=int, default=4)
    deadline_run.add_argument("--max-total-transfers", type=int, default=5)
    deadline_run.add_argument("--max-paid-transfers", type=int, default=2)
    deadline_run.add_argument("--residual-simulations", type=int, default=10_000)
    deadline_run.add_argument("--component-simulations", type=int, default=25_000)
    weekly_rehearsal = commands.add_parser("rehearse-weekly-decision")
    weekly_rehearsal.add_argument("--event", type=int, default=2)
    weekly_rehearsal.add_argument("--horizon", type=int, default=5)
    weekly_rehearsal.add_argument("--observed-at")
    weekly_rehearsal.add_argument("--alternatives-per-transfer-count", type=int, default=4)
    weekly_rehearsal.add_argument("--max-total-transfers", type=int, default=5)
    weekly_rehearsal.add_argument("--max-paid-transfers", type=int, default=2)
    weekly_rehearsal.add_argument("--residual-simulations", type=int, default=10_000)
    weekly_rehearsal.add_argument("--component-simulations", type=int, default=25_000)
    gw1_deadline_run = commands.add_parser("gw1-deadline-run")
    gw1_deadline_run.add_argument("--as-of")
    gw1_deadline_run.add_argument("--reuse-latest-official", action="store_true")
    gw1_deadline_run.add_argument("--stability-samples", type=int, default=20)
    transfer_value = commands.add_parser("calibrate-transfer-value")
    transfer_value.add_argument("--event-stride", type=int, default=3)
    score_event = commands.add_parser("score-weekly-event")
    score_event.add_argument("--event", type=int, required=True)
    score_event.add_argument("--decision", type=Path)
    commands.add_parser("prospective-scoreboard")
    commands.add_parser("participation-scoreboard")
    commands.add_parser("challenger-registry")
    mini_league = commands.add_parser("mini-league-shadow")
    mini_league.add_argument("--decision", type=Path, required=True)
    mini_league.add_argument("--context", type=Path, required=True)
    freeze_gw1 = commands.add_parser("freeze-gw1-prospective")
    freeze_gw1.add_argument("--maximum-candidates", type=int, default=32)
    return root


def _print(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        catalog = build_catalog()
        features = build_features(args.horizon)
        _print(
            {
                "catalog": catalog,
                "features": features,
                "data_quality": audit_features(args.horizon),
            }
        )
    elif args.command == "audit":
        _print(audit_features(args.horizon))
    elif args.command == "gpu-check":
        _print(require_cuda())
    elif args.command == "train":
        _print(train())
    elif args.command == "forecast":
        _print(forecast())
    elif args.command == "backtest-picker":
        _print(evaluate_picker())
    elif args.command == "fixture-ablation":
        result = run_fixture_ablation()
        _print(
            {
                "report": "reports/fixture-context-ablation.md",
                "metrics": "data/model/artifacts/fixture_ablation_v1/metrics.json",
                "champion_challenger": result["champion_challenger"],
            }
        )
    elif args.command == "audit-market-goals":
        result = build_historical_market_goal_rates(refresh=args.refresh)
        _print(
            {
                "report": "reports/market-goal-rate-challenger.md",
                "receipt": "data/model/normalized/historical_market_goal_rates_receipt.json",
                "verdict": result["verdict"],
                "frozen_test": result["frozen_test"],
                "current_source": current_season_source_available(),
            }
        )
    elif args.command == "collect-current-market-goals":
        _print(
            build_current_market_goal_rates(
                event=args.event,
                horizon=args.horizon,
            )
        )
    elif args.command == "replay-market-goals":
        result = run_market_goal_policy_replay()
        _print(
            {
                "report": "reports/market-goal-policy-replay.md",
                "results": "data/model/market_goal_policy_v1/results.json",
                "verdict": result["verdict"],
                "policy_gate": result["policy_gate"],
                "by_season": result["by_season"],
            }
        )
    elif args.command == "replay-market-transfers":
        result = run_market_transfer_replay()
        _print(
            {
                "report": "reports/market-goal-sequential-transfer-replay.md",
                "results": "data/model/market_transfer_policy_v1/results.json",
                "verdict": result["verdict"],
                "gate": result["gate"],
                "path_summaries": {
                    key: {
                        field: value[field]
                        for field in (
                            "gross_points",
                            "points_cost",
                            "net_points",
                            "transfers",
                            "hits",
                            "rolls",
                        )
                    }
                    for key, value in result["paths"].items()
                },
            }
        )
    elif args.command == "calibrate-betfair-exchange":
        result = run_betfair_exchange_calibration()
        _print(
            {
                "report": "reports/betfair-exchange-calibration.md",
                "results": "data/model/betfair_exchange_policy_v1/results.json",
                "verdict": result["verdict"],
                "selected_weight": result["selected_weight"],
                "production_weight": result["production_weight"],
                "policy_gate": result["policy_gate"],
            }
        )
    elif args.command == "backtest-market-features":
        result = run_market_feature_challenger()
        _print(
            {
                "report": "reports/market-feature-player-policy.md",
                "results": "data/model/market_feature_v1/results.json",
                "verdict": result["verdict"],
                "production_policy": result["production_policy"],
                "unbounded_independent_test_gate": result["independent_policy"]["test_gate"],
                "bounded_deployment_independent": {
                    key: result["deployment_independent"][key]
                    for key in ("weight", "total_delta", "gate")
                },
                "sequential_gate": {
                    key: result["sequential_policy"][key]
                    for key in (
                        "passed",
                        "selected_weight",
                        "checks",
                        "validation_total_delta",
                        "test_total_delta",
                        "test_mean_delta",
                        "interval",
                    )
                },
            }
        )
    elif args.command == "backtest-attacking-chance":
        result = run_attacking_chance_challenger()
        _print(
            {
                "report": "reports/attacking-chance-quality-challenger.md",
                "results": "data/model/attacking_chance_v1/results.json",
                "verdict": result["verdict"],
                "selected_weight": result["sequential_policy"]["selected_weight"],
                "gate": result["gate"],
                "production_policy": result["production_policy"],
            }
        )
    elif args.command == "backtest-understat":
        result = run_understat_challenger()
        _print(
            {
                "report": "reports/understat-preseason-feature-challenger.md",
                "results": "data/model/understat_preseason_v1/results.json",
                "verdict": result["verdict"],
                "selected_weight": result["sequential_policy"]["selected_weight"],
                "gate": result["gate"],
                "production_policy": result["production_policy"],
            }
        )
    elif args.command == "backtest-sofascore-events":
        result = run_sofascore_event_policy_replay(
            progress=lambda message: print(message, flush=True)
        )
        _print(
            {
                "passed": result["gate"]["passed"],
                "checks": result["gate"]["checks"],
                "selected_weight": result["selected_weight"],
                "frozen_test": {
                    "mapping_coverage": result["frozen_test"]["mapping_coverage"],
                    "player_deadline_feature_coverage": result["frozen_test"][
                        "player_deadline_feature_coverage"
                    ],
                    "champion_mae": result["frozen_test"]["champion_mae"],
                    "challenger_mae": result["frozen_test"]["challenger_mae"],
                    "legal_policy_delta": result["frozen_test"]["legal_policy"]["total_delta"],
                },
                "results": "data/model/sofascore_event_policy_v1/results.json",
                "report": "reports/sofascore-player-event-challenger.md",
            }
        )
    elif args.command == "backtest-return-distribution":
        result = run_return_distribution_challenger()
        _print(
            {
                "report": "reports/return-distribution-challenger.md",
                "results": "data/model/return_distribution_v1/results.json",
                "verdict": result["verdict"],
                "selected_challenger_weight": result["selected_challenger_weight"],
                "gate": result["gate"],
            }
        )
    elif args.command == "replay-captain-returns":
        result = run_captain_return_replay()
        _print(
            {
                "report": "reports/captain-return-policy-replay.md",
                "results": "data/model/captain_return_policy_v1/results.json",
                "verdict": result["verdict"],
                "selected_weight": result["selected_weight"],
                "gate": result["gate"],
            }
        )
    elif args.command == "replay-form-reversion":
        result = run_form_reversion_challenger()
        replay = result["sequential_replay"]
        _print(
            {
                "report": "reports/form-reversion-policy-replay.md",
                "results": "data/model/form_reversion_v1/results.json",
                "verdict": result["verdict"],
                "reused": result.get("reused", False),
                "historical_classification": result["historical_audit"]["classification"],
                "selected_score_field": replay["selected_score_field"],
                "selected_correction_weight": replay["selected_correction_weight"],
                "gate": replay["gate"],
            }
        )
    elif args.command == "calibrate-horizon-decay":
        result = run_horizon_decay_replay()
        _print(
            {
                "report": "reports/horizon-decay-policy-replay.md",
                "results": "data/model/horizon_decay_replay_v1/results.json",
                "verdict": result["verdict"],
                "selected_configuration": result["selected_configuration"],
                "production_configuration": result["production_configuration"],
                "promotion_gate": result["promotion_gate"],
            }
        )
    elif args.command == "backtest-role-residual":
        result = run_role_residual_challenger()
        _print(
            {
                "report": "reports/role-residual-policy-replay.md",
                "results": "data/model/role_residual_v1/results.json",
                "verdict": result["verdict"],
                "eligible_positions": result["eligible_positions"],
                "policy_replay": {
                    key: result["policy_replay"][key]
                    for key in (
                        "selection_total_delta",
                        "frozen_test_total_delta",
                        "passed",
                    )
                },
            }
        )
    elif args.command == "backtest-lead-time":
        result = run_lead_time_challenger()
        _print(
            {
                "report": "reports/lead-time-forecast-policy-replay.md",
                "results": "data/model/lead_time_v1/results.json",
                "verdict": result["verdict"],
                "eligible_positions": result["eligible_positions"],
                "adaptive_replay": {
                    key: result["adaptive_replay"][key]
                    for key in (
                        "selection_total_delta",
                        "frozen_test_total_delta",
                        "passed",
                    )
                },
            }
        )
    elif args.command == "stress-adaptive-preseason":
        result = run_adaptive_preseason_stress()
        tournament = result["tournament"]
        _print(
            {
                "report": "reports/adaptive-preseason-lead-stress.md",
                "results": "data/model/adaptive_preseason_v1/results.json",
                "verdict": result["verdict"],
                "production_changed": result["production_changed"],
                "leader": tournament["leader"]["candidate_id"],
                "incumbent": tournament["incumbent"]["candidate_id"],
                "full_pipeline_request_gate": tournament["full_pipeline_request_gate"],
            }
        )
    elif args.command == "squad":
        receipt = select_initial_squad(args.stability_samples)
        _print(
            {
                "receipt": "data/decisions/2026-27-gw1-initial-squad.json",
                "report": "reports/gw1-initial-squad.md",
                "budget_spent": receipt["budget_spent"],
                "bank": receipt["bank"],
                "gw1_expected_points": receipt["gameweeks"]["1"]["expected_points"],
            }
        )
    elif args.command == "tournament":
        result = run_tournament(
            candidate_count=args.candidates,
            selection_simulations=args.selection_simulations,
            holdout_simulations=args.holdout_simulations,
            seed=args.seed,
        )
        leader = max(result["holdout_metrics"], key=lambda row: row["base_mean_points"])
        policy_leader = max(
            result["policy_finalist_metrics"],
            key=lambda row: row["base_mean_points"],
        )
        _print(
            {
                "report": "reports/gw1-squad-tournament.md",
                "results": "data/model/tournament_v1/gw1-5-results.json",
                "leader": leader["candidate_id"],
                "leader_mean_points": leader["base_mean_points"],
                "policy_leader": policy_leader["candidate_id"],
                "policy_leader_mean_points": policy_leader["base_mean_points"],
                "selection_holdout_rank_correlation": result["selection_holdout_rank_correlation"],
            }
        )
    elif args.command == "train-components":
        _print(train_goal_model(force=args.force, seed=args.seed))
    elif args.command == "train-component-events":
        _print(
            train_component_models(
                force_targets=args.force_targets,
                seed=args.seed,
            )
        )
    elif args.command == "calibrate-synthesis-selector":
        result = run_synthesis_selector_replay()
        print(
            json.dumps(
                {
                    "verdict": result["verdict"],
                    "production_configuration": result["production_configuration"],
                    "report": "reports/synthesis-selector-policy-replay.md",
                },
                indent=2,
            )
        )
    elif args.command == "audit-structure-stress":
        result = run_structure_stress()
        print(
            json.dumps(
                {
                    "verdict": result["verdict"],
                    "published_candidate_id": result["published_candidate_id"],
                    "stress_leader_id": result["stress_leader_id"],
                    "report": "reports/gw1-scoring-formation-autosub-stress.md",
                },
                indent=2,
            )
        )
    elif args.command == "build-deadline-pack":
        result = build_deadline_pack()
        print(
            json.dumps(
                {
                    "verdict": result["verdict"],
                    "candidate_id": result["decision"]["candidate_id"],
                    "report": "reports/gw1-deadline-pack.md",
                    "receipt": "data/manifests/gw1-deadline-pack.json",
                },
                indent=2,
            )
        )
    elif args.command == "audit-sota-readiness":
        _print(build_sota_readiness_audit())
    elif args.command == "audit-external-player-data":
        _print(build_external_player_data_receipt())
    elif args.command == "benchmark-openfpl":
        result = run_openfpl_matched_benchmark(
            rebuild=args.rebuild,
            top_models=args.top_models,
            progress=lambda message: print(message, flush=True),
        )
        _print(
            {
                "passed": result["passed"],
                "summary": result["summary"],
                "checks": result["checks"],
                "matched_events": result["legal_policy"]["matched_events"],
                "legal_policy_total_delta": result["legal_policy"]["total_delta"],
                "results": "data/model/external_forecast_benchmark_v1/results.json",
                "report": "reports/openfpl-matched-benchmark.md",
            }
        )
    elif args.command == "prospective-2026-scoreboard":
        _print(build_2026_prospective_scoreboard())
    elif args.command == "distribution-scoreboard":
        _print(build_distribution_scoreboard())
    elif args.command == "calibrate-price-liquidity":
        _print(run_price_liquidity_calibration())
    elif args.command == "build-algorithm-whitepaper":
        _print(build_algorithm_whitepaper())
    elif args.command == "forecast-components":
        _print(forecast_components())
    elif args.command == "component-candidates":
        result = generate_component_candidates()
        _print(
            {
                "path": "data/decisions/2026-27-gw1-component-candidates.json",
                "candidate_count": result["candidate_count"],
                "selection_simulations": result["selection_simulations"],
                "selection_seed": result["selection_seed"],
            }
        )
    elif args.command == "backtest-components":
        result = run_component_player_backtest(seed=args.seed)
        _print(
            {
                "report": "reports/component-player-backtest.md",
                "metrics": "data/model/component_backtest_v1/metrics.json",
                "gate": result["gate"],
                "blend_selection": result["blend_selection"],
                "market_challenger": result["market_challenger"],
            }
        )
    elif args.command == "component-tournament":
        result = run_component_tournament(
            simulations=args.simulations,
            seed=args.seed,
            force_goal_model=args.force_goal_model,
        )
        _print(
            {
                "report": "reports/gw1-component-tournament.md",
                "results": "data/model/tournament_v2/component-gw1-5-results.json",
                "promotion_gate": result["promotion_gate"],
                "leaders": result["leaders"],
                "residual_component_fixed_rank_correlation": result[
                    "residual_component_fixed_rank_correlation"
                ],
            }
        )
    elif args.command == "bench-audit":
        result = run_bench_audit(simulations=args.simulations, seed=args.seed)
        _print(
            {
                "report": "reports/bench-and-formation-adversarial-review.md",
                "results": "data/model/bench_audit_v1/results.json",
                "verdict": result["verdict"],
            }
        )
    elif args.command == "audit-bench-allocation":
        result = run_bench_allocation_audit(
            simulations=args.simulations,
            five_week_seed=args.five_week_seed,
            eight_week_seed=args.eight_week_seed,
            top_historical_band=args.top_historical_band,
        )
        _print(
            {
                "report": "reports/current-season-bench-allocation-audit.md",
                "results": "data/model/bench_allocation_audit_v2/results.json",
                "verdict": result["verdict"],
                "active": result["current"]["candidate_id"],
                "targeted_winner": result["targeted_winner"]["candidate_id"],
                "best_historical_band": result["best_historical_band_challenger"]["candidate_id"],
            }
        )
    elif args.command == "audit-bench-history":
        result = run_historical_bench_depth_audit(refresh_forecasts=args.refresh_forecasts)
        _print(
            {
                "report": "reports/historical-bench-depth-audit.md",
                "results": "data/model/bench_history_v1/results.json",
                "verdict": result["verdict"],
                "opening_windows": {
                    key: value
                    for key, value in result["opening_windows"].items()
                    if key != "by_season"
                },
                "paired_vs_lean": result["rolling_windows"]["paired_vs_lean"],
            }
        )
    elif args.command == "audit-current-squad":
        result = run_current_squad_audit(
            selection_simulations=args.selection_simulations,
            holdout_simulations=args.holdout_simulations,
            finalists=args.finalists,
            selection_seed=args.selection_seed,
            holdout_seed=args.holdout_seed,
        )
        _print(
            {
                "report": "reports/current-squad-xi-captain-bench-audit.md",
                "results": "data/model/current_squad_adversarial_v1/results.json",
                "verdict": result["verdict"],
                "published": result["published"],
                "selection_champion": result["selection_champion"],
            }
        )
    elif args.command == "audit-preseason-role":
        result = run_preseason_role_scenario_audit(
            selection_simulations=args.selection_simulations,
            holdout_simulations=args.holdout_simulations,
            finalists=args.finalists,
            selection_seed=args.selection_seed,
            holdout_seed=args.holdout_seed,
            maximum_candidates=args.maximum_candidates,
        )
        _print(
            {
                "report": "reports/preseason-role-scenario-audit.md",
                "results": "data/model/preseason_role_scenario_v1/results.json",
                "verdict": result["verdict"],
                "production_changed": result["production_changed"],
                "supported_configuration_scenarios": result["supported_configuration_scenarios"],
                "supported_squad_screen_scenarios": result["supported_squad_screen_scenarios"],
                "supported_deep_squad_scenarios": result["supported_deep_squad_scenarios"],
            }
        )
    elif args.command == "audit-preseason-threshold":
        result = run_preseason_role_threshold_audit(
            selection_simulations=args.selection_simulations,
            holdout_simulations=args.holdout_simulations,
            selection_seed=args.selection_seed,
            holdout_seed=args.holdout_seed,
        )
        _print(
            {
                "report": "reports/preseason-role-threshold-audit.md",
                "results": "data/model/preseason_role_threshold_v1/results.json",
                "verdict": result["verdict"],
                "production_changed": result["production_changed"],
                "boundary": result["boundary"],
            }
        )
    elif args.command == "audit-one-swaps":
        result = run_one_swap_audit(
            proxy_squads=args.proxy_squads,
            selection_simulations=args.selection_simulations,
            holdout_simulations=args.holdout_simulations,
            finalists=args.finalists,
            selection_seed=args.selection_seed,
            holdout_seed=args.holdout_seed,
        )
        _print(
            {
                "report": "reports/gw1-one-swap-adversarial-audit.md",
                "results": "data/model/one_swap_audit_v1/results.json",
                "verdict": result["verdict"],
                "production_changed": result["production_changed"],
                "selection_champion": result["selection_champion"],
                "search": result["search"],
            }
        )
    elif args.command == "rules-audit":
        result = audit_2026_27_rules()
        _print(
            {
                "report": "reports/2026-27-rules-audit.md",
                "results": "data/model/rules_audit_v1/2026-27.json",
                "status_counts": result["status_counts"],
                "blocking_before_weekly_agent": result["blocking_before_weekly_agent"],
            }
        )
    elif args.command == "schedule-status":
        result = build_schedule_receipt()
        _print(
            {
                "current_path": result["current_path"],
                "archive_path": result["archive_path"],
                "schedule_fingerprint": result["schedule_fingerprint"],
                "snapshot_at": result["snapshot_at"],
                "summary": result["summary"],
                "comparison": result["comparison"],
            }
        )
    elif args.command == "build-chip-schedule-history":
        result = build_historical_chip_schedule_opportunities()
        _print(result)
    elif args.command == "build-rearrangement-model":
        result = build_rearrangement_model()
        _print(result)
    elif args.command == "replay-squad-chips":
        result = run_squad_chip_retention_replay()
        _print(
            {
                "verdict": result["verdict"],
                "historical_gate": result["historical_gate"],
                "promotion_gate": result["promotion_gate"],
                "results": "data/model/squad_chip_replay_v1/results.json",
                "report": "reports/squad-chip-retention-replay.md",
            }
        )
    elif args.command == "replay-team-chips":
        result = run_team_chip_retention_replay()
        _print(
            {
                "verdict": result["verdict"],
                "historical_gate": result["historical_gate"],
                "promotion_gate": result["promotion_gate"],
                "results": "data/model/team_chip_replay_v1/results.json",
                "report": "reports/team-chip-retention-replay.md",
            }
        )
    elif args.command == "reconstruct-bps":
        result = reconstruct_2026_27_bps(
            simulations=args.simulations,
            seed=args.seed,
        )
        _print(
            {
                "report": "reports/2026-27-bps-reconstruction.md",
                "metrics": "data/model/bps_2026_27_v1/metrics.json",
                "promoted": result["promoted"],
                "gate": result["gate"],
            }
        )
    elif args.command == "validate-bps":
        result = validate_external_bps_reconstruction(refresh=args.refresh)
        _print(
            {
                "report": "reports/2026-27-bps-external-validation.md",
                "metrics": "data/model/bps_2026_27_v1/external-validation.json",
                "evidence_passed": result["evidence_passed"],
                "source_integrity_exact": result["source_integrity_exact"],
                "recommendation": result["recommendation"],
                "production_change": result["production_change"],
            }
        )
    elif args.command == "audit-appearances":
        result = audit_appearance_reliability()
        _print(
            {
                "report": "reports/appearance-reliability-audit.md",
                "metrics": "data/model/appearance_audit_v1/metrics.json",
                "promoted_positions": result["promoted_positions"],
                "gate": result["gate"],
            }
        )
    elif args.command == "audit-appearance-challenger":
        result = run_appearance_challenger()
        _print(
            {
                "report": "reports/appearance-challenger-v2.md",
                "artifact": "data/model/appearance_challenger_v2/candidate.json",
                "production_calibration_changed": result["production_calibration_changed"],
                "positions_pending_policy_replay": result[
                    "promoted_positions_pending_policy_replay"
                ],
                "position_gate": result["position_gate"],
            }
        )
    elif args.command == "audit-role-appearance":
        result = run_role_appearance_challenger()
        _print(
            {
                "report": "reports/appearance-role-challenger.md",
                "metrics": "data/model/appearance_role_v1/metrics.json",
                "positions_pending_policy_replay": result["positions_pending_policy_replay"],
                "production_changed": result["production_changed"],
            }
        )
    elif args.command == "replay-role-appearance":
        result = run_role_appearance_policy_replay()
        _print(
            {
                "report": "reports/appearance-role-policy-replay.md",
                "results": "data/model/appearance_role_v1/policy-replay.json",
                "statistical_positions": result["statistical_positions"],
                "selected_subset": result["selected_subset"],
                "promotion_ready": result["promotion_ready"],
                "production_changed": result["production_changed"],
            }
        )
    elif args.command == "replay-appearance-policy":
        result = run_appearance_policy_replay(position=args.position)
        _print(
            {
                "report": "reports/appearance-policy-replay.md",
                "artifact": "data/model/appearance_challenger_v2/policy-replay.json",
                "position": result["position"],
                "gate": result["gate"],
                "exact_squad_rate": result["exact_squad_rate"],
                "same_captain_rate": result["same_captain_rate"],
            }
        )
    elif args.command == "retire-appearance-calibration":
        _print(retire_failed_appearance_calibration(position=args.position))
    elif args.command == "promote-gw1":
        result = promote_gw1_squad()
        _print(
            {
                "candidate_id": result["candidate_id"],
                "status": result["status"],
                "formation": result["gw1"]["formation"],
                "receipt": "data/decisions/2026-27-gw1-promoted-squad.json",
                "report": "reports/gw1-promoted-squad.md",
            }
        )
    elif args.command == "robust-search":
        result = run_robust_search(
            discovery_candidates=args.discovery_candidates,
            screen_simulations=args.screen_simulations,
            shortlist=args.shortlist,
            selection_simulations=args.selection_simulations,
            finalists=args.finalists,
            holdout_simulations=args.holdout_simulations,
            discovery_seed=args.discovery_seed,
            selection_seed=args.selection_seed,
            holdout_seed=args.holdout_seed,
            stress_goal_multiplier=args.stress_goal_multiplier,
            global_restarts=args.global_restarts,
            evolution_population=args.evolution_population,
            evolution_generations=args.evolution_generations,
            evolution_offspring=args.evolution_offspring,
            minimum_seed_distance=args.minimum_seed_distance,
        )
        _print(
            {
                "report": "reports/gw1-global-robust-search.md",
                "results": "data/model/robust_search_v2_global/results.json",
                "decision": "data/decisions/2026-27-gw1-global-robust-search.json",
                "funnel": result["funnel"],
                "leader": result["leader"]["candidate_id"],
                "leader_name": result["leader"]["display_name"],
                "robust_regret": result["leader"]["robust_regret"],
                "central_comparison": result["central_paired_comparison"],
            }
        )
    elif args.command == "horizon-audit":
        result = run_horizon_audit(
            horizon_candidates=args.horizon_candidates,
            horizon_neighbours=args.horizon_neighbours,
            horizon_neighbour_seeds=args.horizon_neighbour_seeds,
            selection_simulations=args.selection_simulations,
            finalists=args.finalists,
            holdout_simulations=args.holdout_simulations,
            candidate_seed=args.candidate_seed,
            selection_seed=args.selection_seed,
            holdout_seed=args.holdout_seed,
        )
        _print(
            {
                "report": "reports/gw1-horizon-adequacy-audit.md",
                "results": "data/model/horizon_audit_v1/results.json",
                "decision": "data/decisions/2026-27-gw1-horizon-audit.json",
                "verdict": result["verdict"],
                "leader": result["leader"]["candidate_id"],
                "incumbent": result["incumbent"]["candidate_id"],
                "central_comparison": result["leader_minus_incumbent_central"],
            }
        )
    elif args.command == "synthesize-gw1":
        result = run_decision_synthesis(
            horizon_family_weight=args.horizon_family_weight,
            family_worst_weight=args.family_worst_weight,
        )
        _print(
            {
                "report": "reports/gw1-synthesized-decision.md",
                "results": "data/model/gw1_decision_synthesis_v1/results.json",
                "decision": "data/decisions/2026-27-gw1-synthesized.json",
                "leader": result["decision"]["candidate_id"],
                "verdict": result["verdict"],
            }
        )
    elif args.command == "build-gw1":
        catalog = build_catalog()
        prepared = build_features(args.horizon)
        quality = audit_features(args.horizon)
        trained = train()
        predicted = forecast()
        receipt = select_initial_squad(args.stability_samples)
        _print(
            {
                "catalog": catalog,
                "features": prepared,
                "data_quality": quality,
                "training": trained,
                "forecast": predicted,
                "decision": {
                    "budget_spent": receipt["budget_spent"],
                    "bank": receipt["bank"],
                    "gw1_expected_points": receipt["gameweeks"]["1"]["expected_points"],
                    "report": "reports/gw1-initial-squad.md",
                },
            }
        )
    elif args.command == "deadline-status":
        result = audit_deadline_evidence(
            as_of=args.as_of,
            manager_entry_id=args.manager_entry_id,
        )
        availability = audit_availability_watch(as_of=args.as_of)
        result["availability_watch"] = {
            "receipt": "data/manifests/fpl-availability-watch.json",
            "status": availability["status"],
            "current": availability["current"],
            "decision_action": availability["decision_action"],
            "decision_change_authorized": availability["decision_change_authorized"],
            "summary": availability.get("summary", {}),
            "issues": availability["issues"],
            "warnings": availability["warnings"],
        }
        _print(result)
    elif args.command == "availability-status":
        _print(audit_availability_watch(as_of=args.as_of))
    elif args.command == "deadline-run":
        _print(
            run_weekly_deadline_pipeline(
                manager_entry_id=args.manager_entry_id,
                horizon=args.horizon,
                as_of=args.as_of,
                reuse_latest_official=args.reuse_latest_official,
                alternatives_per_transfer_count=args.alternatives_per_transfer_count,
                max_total_transfers=args.max_total_transfers,
                max_paid_transfers=args.max_paid_transfers,
                residual_simulations=args.residual_simulations,
                component_simulations=args.component_simulations,
            )
        )
    elif args.command == "rehearse-weekly-decision":
        _print(
            run_weekly_rehearsal(
                event=args.event,
                horizon=args.horizon,
                observed_at=args.observed_at,
                alternatives_per_transfer_count=args.alternatives_per_transfer_count,
                max_total_transfers=args.max_total_transfers,
                max_paid_transfers=args.max_paid_transfers,
                residual_simulations=args.residual_simulations,
                component_simulations=args.component_simulations,
            )
        )
    elif args.command == "gw1-deadline-run":
        result = run_gw1_deadline_pipeline(
            as_of=args.as_of,
            reuse_latest_official=args.reuse_latest_official,
            stability_samples=args.stability_samples,
        )
        _print(
            {
                "status": result["status"],
                "published": result["published"],
                "reused": result.get("reused", False),
                "input_fingerprint": result.get("input_fingerprint"),
                "stages": result.get("stages", []),
                "artifacts": result.get("published_artifacts", {}),
                "message": result.get("message"),
            }
        )
    elif args.command == "calibrate-transfer-value":
        result = run_transfer_value_calibration(event_stride=args.event_stride)
        _print(
            {
                "artifact": "data/model/transfer_value_v1/terminal-free-transfer-value.json",
                "report": "reports/terminal-free-transfer-value.md",
                "promoted": result["fit"]["promotion_gate"]["promoted"],
                "selected_curve": result["fit"]["selected_curve"],
                "held_out_metrics": result["fit"]["held_out_metrics"],
            }
        )
    elif args.command == "score-weekly-event":
        scored = score_weekly_event(args.event, decision_path=args.decision)
        _print(
            {
                "event_score": scored,
                "season_scoreboard": build_prospective_scoreboard(),
                "prospective_2026": build_2026_prospective_scoreboard(),
                "distribution_calibration": build_distribution_scoreboard(),
                "participation_calibration": build_participation_scoreboard(),
            }
        )
    elif args.command == "prospective-scoreboard":
        result = build_prospective_scoreboard()
        _print(
            {
                "status": result["status"],
                "completed_events": result["completed_events"],
                "receipt_path": result["receipt_path"],
                "report": "reports/prospective-season-scoreboard.md",
            }
        )
    elif args.command == "participation-scoreboard":
        _print(build_participation_scoreboard())
    elif args.command == "challenger-registry":
        result = build_challenger_registry()
        _print(
            {
                "production_champion": result["production_champion"],
                "production_changed": result["production_changed"],
                "summary": result["summary"],
                "receipt_path": result["receipt_path"],
                "report": "reports/forecast-challenger-registry.md",
            }
        )
    elif args.command == "mini-league-shadow":
        result = run_mini_league_shadow(args.decision, args.context)
        _print(
            {
                "status": result["status"],
                "mode": result["mode"],
                "points_first_action_id": result["points_first_action_id"],
                "shadow_preference": result["shadow_preference"],
                "decision_authority": result["decision_authority"],
                "receipt_path": result["receipt_path"],
                "report_path": result["report_path"],
            }
        )
    elif args.command == "freeze-gw1-prospective":
        contract = freeze_gw1_prospective_contract(maximum_candidates=args.maximum_candidates)
        _print(
            {
                "contract_path": contract["contract_path"],
                "contract_fingerprint": contract["contract_fingerprint"],
                "evaluated_candidates": len(contract["action_summaries"]),
                "selected_action_id": contract["selected_action_id"],
                "reference_action_id": contract["reference_action_id"],
            }
        )
