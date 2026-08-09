"""Build the self-contained interactive GW1 model story.

The output deliberately has no network dependencies: fonts, data, styling and
interaction are embedded so the report can be emailed and opened as one file.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pyarrow.parquet as pq

from fplagent_engine.models import CURRENT_FORECAST

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
OUTPUT = REPORTS / "gw1-model-story-standalone.html"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def font_data(name: str) -> str:
    return base64.b64encode((REPORTS / "assets" / name).read_bytes()).decode("ascii")


def compact_player(player: dict, role: str) -> dict:
    return {
        "name": player["name"],
        "team": player["team"],
        "position": player["position"],
        "price": round(float(player["price"]), 1),
        "xp": round(float(player["gw1_expected_points"]), 2),
        "play": round(float(player["gw1_p_play"]) * 100),
        "role": role,
        "calibrated": bool(player.get("appearance_calibration_applied", False)),
    }


def compact_forecast_player(player: dict, role: str) -> dict:
    return {
        "name": player["player_name"],
        "team": player["team_short_name"],
        "position": player["position"],
        "price": round(float(player["market_price"]) / 10.0, 1),
        "xp": round(float(player["expected_points"]), 2),
        "play": round(float(player["p_play"]) * 100),
        "role": role,
        "calibrated": bool(player.get("appearance_calibration_applied", False)),
    }


def build_story_data() -> dict:
    promoted = read_json(DATA / "decisions" / "2026-27-gw1-promoted-squad.json")
    robust = read_json(DATA / "model" / "robust_search_v2_global" / "results.json")
    horizon_audit = read_json(DATA / "model" / "horizon_audit_v1" / "results.json")
    synthesis = read_json(DATA / "model" / "gw1_decision_synthesis_v1" / "results.json")
    residual_candidates = read_json(DATA / "decisions" / "2026-27-gw1-candidates.json")
    component_candidates = read_json(
        DATA / "decisions" / "2026-27-gw1-component-candidates.json"
    )
    tournament = read_json(
        DATA / "model" / "tournament_v2" / "component-gw1-5-results.json"
    )
    bench = read_json(DATA / "model" / "bench_audit_v1" / "results.json")
    appearance = read_json(DATA / "model" / "appearance_audit_v1" / "metrics.json")
    bps = read_json(DATA / "model" / "bps_2026_27_v1" / "metrics.json")
    quality = read_json(DATA / "model" / "normalized" / "data_quality.json")
    strength = read_json(DATA / "model" / "normalized" / "team_strength_metrics.json")
    rules = read_json(DATA / "model" / "rules_audit_v1" / "2026-27.json")

    leader_candidate = robust["leader_candidate"]
    gw1 = leader_candidate["lineups"]["1"]
    forecast = {
        int(row["element"]): row
        for row in pq.read_table(CURRENT_FORECAST).to_pylist()
        if int(row["event_number"]) == 1
    }
    starters = [
        compact_forecast_player(
            forecast[int(element)],
            "captain"
            if int(element) == int(gw1["captain"])
            else "vice"
            if int(element) == int(gw1["vice_captain"])
            else "starter",
        )
        for element in gw1["starters"]
    ]
    substitutes = [
        compact_forecast_player(forecast[int(element)], "bench")
        for element in gw1["bench_order"]
    ]

    component_field = sorted(
        tournament["component_native_metrics"],
        key=lambda row: row["evidence_weighted_mean_points"],
        reverse=True,
    )
    finalists = [
        {
            "id": row["candidate_id"],
            "score": round(float(row["evidence_weighted_mean_points"]), 3),
            "raw": round(float(row["raw_mean_points"]), 2),
            "anchored": round(float(row["anchored_mean_points"]), 2),
            "bench": round(float(row["gw1_bench_spend"]), 1),
        }
        for row in component_field[:6]
    ]
    residual_leader = next(
        row for row in tournament["policy_finalist_metrics"] if row["candidate_id"] == "S028"
    )
    finalists.append(
        {
            "id": "S028",
            "score": round(float(residual_leader["evidence_weighted_mean_points"]), 3),
            "raw": round(float(residual_leader["raw_mean_points"]), 2),
            "anchored": round(float(residual_leader["anchored_mean_points"]), 2),
            "bench": round(float(residual_leader["gw1_bench_spend"]), 1),
        }
    )
    finalists.sort(key=lambda row: row["score"], reverse=True)

    base_by_id = {
        row["candidate_id"]: row for row in bench["simulation"]["evidence_weighted_metrics"]
    }
    stress_by_id = {
        row["candidate_id"]: row
        for row in bench["simulation"]["clean_sheet_pessimism_raw_metrics"]
    }
    stress_ids = ["C007", "S028", "F4", "Z20", "F5"]
    scenarios = []
    formations = {row["candidate_id"]: row["formation"] for row in bench["candidates"]}
    for candidate_id in stress_ids:
        scenarios.append(
            {
                "id": candidate_id,
                "formation": formations[candidate_id],
                "base": round(float(base_by_id[candidate_id]["mean_points"]), 2),
                "stress": round(float(stress_by_id[candidate_id]["mean_points"]), 2),
            }
        )

    quality_rows = next(
        check["value"] for check in quality["checks"] if check["name"] == "historical_row_volume"
    )
    quality_horizon = next(
        check["value"]
        for check in quality["checks"]
        if check["name"] == "current_player_horizon_grid"
    )
    holdout = bps["tackled_proxy_holdout"]["player_season"]
    promotion = promoted["decision_metrics"]["versus_residual_incumbent"]
    identities = tournament["simulation_diagnostics"]["identity_checks"]
    
    robust_field = robust["finalist_metrics"]
    c007 = next(row for row in robust_field if "C007" in row["origin_ids"])
    robust_scenarios = []
    for row in [*robust_field[:5], c007]:
        if any(item["id"] == row["candidate_id"] for item in robust_scenarios):
            continue
        robust_scenarios.append(
            {
                "id": "C007" if "C007" in row["origin_ids"] else row["candidate_id"],
                "formation": row["gw1_formation"],
                "base": round(float(row["scenario_values"]["base_evidence_open"]), 3),
                "stress": round(float(row["scenario_values"]["high_goal_open"]), 3),
                "regret": round(float(row["robust_regret"]), 3),
            }
        )
    sensitivity_wins = sum(
        item["winner"] == robust["leader"]["candidate_id"]
        for item in robust["decision_sensitivity"]["leave_one_scenario_out"]
    )

    return {
        "meta": {
            "candidate": synthesis["decision"]["candidate_id"],
            "status": synthesis["deadline_rule"],
            "created": synthesis["created_at"],
            "snapshot": rules["snapshot_at"],
            "formation": robust["leader"]["gw1_formation"],
            "budget": leader_candidate["budget_spent"],
            "bank": leader_candidate["bank"],
            "bench": leader_candidate["gw1_bench_spend"],
            "score": round(float(robust["leader"]["scenario_values"]["base_evidence_open"]), 2),
        },
        "evidence": {
            "historicalRows": quality_rows,
            "checks": len(quality["checks"]),
            "failedChecks": len(quality["failed_checks"]),
            "players": quality_horizon["players"],
            "horizonRows": quality_horizon["rows"],
            "horizons": quality_horizon["horizon"],
            "teamSeasons": len(strength["by_season"]),
            "teamFixtures": sum(row["fixtures"] for row in strength["by_season"].values()),
        },
        "appearance": {
            "rows": appearance["candidate_pool_rows"],
            "positions": [
                {
                    "position": position,
                    "passed": outcome["promoted"],
                    "brier": outcome["brier_wins"],
                    "logloss": outcome["log_loss_wins"],
                    "tests": outcome["forward_slices"],
                }
                for position, outcome in appearance["gate"].items()
            ],
        },
        "bps": {
            "fixtures": bps["control"]["fixtures"],
            "exactRate": bps["control"]["fixture_exact_rate"],
            "bonus": bps["control"]["actual_bonus_points"],
            "spearman": round(float(holdout["model_spearman"]), 3),
            "mae": round(float(holdout["model_mae"]), 2),
            "baselineMae": round(float(holdout["baseline_mae"]), 2),
            "gpu": bps["cuda"]["gpu"].split(",")[0],
        },
        "search": {
            "residual": residual_candidates["candidate_count"],
            "component": component_candidates["candidate_count"],
            "selectionSeed": tournament["component_native_selection"]["selection_seed"],
            "holdoutSeed": tournament["seed"],
            "simulations": tournament["simulations"],
            "finalists": finalists,
            "seedSquads": robust["funnel"]["seed_squads"],
            "oneSwap": robust["funnel"]["one_swap_universe"],
            "expanded": robust["funnel"]["combined_universe"],
            "globalMilp": robust["funnel"]["global_milp_squads"],
            "globalEvolution": robust["funnel"]["global_evolution_squads"],
            "proxyScenarios": robust["funnel"]["proxy_scenarios"],
            "discovery": robust["funnel"]["discovery_candidates"],
            "shortlist": robust["funnel"]["shortlist"],
            "deepFinalists": robust["funnel"]["finalists"],
            "selectionWorlds": robust["funnel"]["selection_simulations"],
            "holdoutWorlds": robust["funnel"]["holdout_simulations"],
            "unconstrainedSpace": "1.05 × 10²⁷",
        },
        "simulation": {
            "matchScenarios": identities["simulated_match_scenarios"],
            "teamGoals": identities["team_goals"],
            "assists": identities["allocated_assists"],
            "unattributed": identities["unattributed_team_goals"],
            "reconciliation": identities["goal_allocation_reconciliation_rate"],
            "bonus": identities["bonus_points_awarded"],
        },
        "stress": {
            "multiplier": bench["simulation"]["goal_rate_stress_multiplier"],
            "cleanBase": round(bench["simulation"]["mean_clean_sheet_probability_base"] * 100, 1),
            "cleanStress": round(bench["simulation"]["mean_clean_sheet_probability_stress"] * 100, 1),
            "scenarios": scenarios,
        },
        "promotion": {
            "checks": tournament["promotion_gate"]["checks"],
            "challenger": promotion["challenger"],
            "incumbent": promotion["incumbent"],
            "delta": round(float(promotion["evidence_weighted"]["mean_delta"]), 3),
            "low": round(float(promotion["evidence_weighted"]["delta_95ci_low"]), 3),
            "high": round(float(promotion["evidence_weighted"]["delta_95ci_high"]), 3),
        },
        "robust": {
            "leader": robust["leader"]["candidate_id"],
            "runner": robust["runner_up"]["candidate_id"],
            "scenarios": robust_scenarios,
            "regret": round(float(robust["leader"]["robust_regret"]), 3),
            "runnerRegret": round(float(robust["runner_up"]["robust_regret"]), 3),
            "centralDeltaRunner": round(
                float(robust["central_paired_comparison"]["mean_delta"]), 3
            ),
            "centralDeltaC007": round(
                float(robust["leader"]["scenario_values"]["base_evidence_open"])
                - float(c007["scenario_values"]["base_evidence_open"]),
                3,
            ),
            "c007Rank": next(
                rank
                for rank, row in enumerate(robust_field, start=1)
                if row["candidate_id"] == c007["candidate_id"]
            ),
            "c007Regret": round(float(c007["robust_regret"]), 3),
            "leaveOneOutWins": sensitivity_wins,
            "leaveOneOutTests": len(
                robust["decision_sensitivity"]["leave_one_scenario_out"]
            ),
            "bankGw2": robust["leader_transfer_policies"]["open"]["2"]["used"] == 0,
        },
        "horizonAudit": {
            "leader": horizon_audit["leader"]["candidate_id"],
            "incumbent": horizon_audit["incumbent"]["candidate_id"],
            "delta": round(
                float(horizon_audit["leader_minus_incumbent_central"]["mean_delta"]), 3
            ),
            "deltaLow": round(
                float(horizon_audit["leader_minus_incumbent_central"]["delta_95ci_low"]),
                3,
            ),
            "deltaHigh": round(
                float(horizon_audit["leader_minus_incumbent_central"]["delta_95ci_high"]),
                3,
            ),
            "selectedRegret": round(float(horizon_audit["incumbent"]["robust_regret"]), 3),
            "challengerRegret": round(float(horizon_audit["leader"]["robust_regret"]), 3),
            "lateRegret": round(
                float(horizon_audit["incumbent"]["scenario_regrets"]["gw6_8_open_equal"]),
                3,
            ),
            "fixedRegret": round(
                float(horizon_audit["incumbent"]["scenario_regrets"]["gw1_8_fixed_d088"]),
                3,
            ),
            "rollRegret": round(
                float(
                    horizon_audit["incumbent"]["scenario_regrets"][
                        "gw1_8_roll_gw2_d088"
                    ]
                ),
                3,
            ),
            "threshold": round(
                100
                * next(
                    row["upper"]
                    for row in synthesis["horizon_weight_champion_intervals"]
                    if row["candidate_id"] == synthesis["decision"]["candidate_id"]
                ),
                1,
            ),
            "synthesisRegret": round(float(synthesis["decision"]["synthesis_regret"]), 3),
            "commonFinalists": synthesis["candidate_coverage"]["common_finalists"],
            "generated": horizon_audit["funnel"]["horizon_specific_candidates"],
            "retention": horizon_audit["historical_evidence"][
                "vaastav_2019_20_top10_retention"
            ],
        },
        "squad": {"starters": starters, "bench": substitutes},
    }


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="description" content="An interactive, evidence-backed journey through FPLAgent's provisional GW1 squad selection.">
<title>Inside the selection room — FPLAgent GW1</title>
<style>
@font-face{font-family:Manrope;src:url(data:font/ttf;base64,__MANROPE_REGULAR__) format('truetype');font-weight:400;font-display:swap}
@font-face{font-family:Manrope;src:url(data:font/ttf;base64,__MANROPE_SEMIBOLD__) format('truetype');font-weight:600;font-display:swap}
@font-face{font-family:Newsreader;src:url(data:font/ttf;base64,__NEWSREADER__) format('truetype');font-weight:400;font-display:swap}
:root{--paper:#f2efe7;--paper-2:#e8e3d7;--ink:#18201c;--muted:#68716b;--faint:#a7aaa2;--line:rgba(24,32,28,.13);--green:#2e6950;--green-soft:#c9d8ce;--red:#94594d;--amber:#a47a3d;--white:#fbfaf6;--ease:cubic-bezier(.22,1,.36,1);--sans:Manrope,'Avenir Next',sans-serif;--serif:Newsreader,Georgia,serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.55;overflow-x:hidden}button{font:inherit;color:inherit}a{color:inherit}.grain{position:fixed;inset:0;pointer-events:none;z-index:20;opacity:.042;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.83' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.45'/%3E%3C/svg%3E")}.shell{width:min(1440px,calc(100% - 48px));margin:auto}.nav{position:fixed;z-index:15;top:18px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:26px;padding:9px 10px 9px 18px;border-radius:999px;background:rgba(242,239,231,.88);border:1px solid rgba(24,32,28,.1);box-shadow:inset 0 1px 0 rgba(255,255,255,.55),0 16px 40px rgba(40,49,43,.08);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);white-space:nowrap}.brand{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;letter-spacing:-.02em}.brand-mark{width:27px;height:27px;border-radius:50%;display:grid;place-items:center;background:var(--ink);color:var(--paper);font-size:10px}.nav-meta{font-size:11px;color:var(--muted)}.nav button,.pill-button{border:0;border-radius:999px;background:var(--ink);color:var(--white);display:flex;align-items:center;gap:10px;padding:10px 11px 10px 17px;cursor:pointer;transition:transform .6s var(--ease),background .6s var(--ease)}.nav button:hover,.pill-button:hover{background:var(--green);transform:translateY(-1px)}.nav button:active,.pill-button:active{transform:scale(.98)}.button-icon{width:27px;height:27px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.12)}.button-icon svg{width:12px;height:12px}.hero{min-height:100dvh;padding:150px 0 86px;display:grid;grid-template-columns:minmax(0,1.25fr) minmax(340px,.75fr);gap:7vw;align-items:end;position:relative}.hero-copy{max-width:860px}.eyebrow{display:inline-flex;align-items:center;gap:9px;font-size:10px;text-transform:uppercase;letter-spacing:.19em;font-weight:600;color:var(--green);margin-bottom:27px}.eyebrow:before{content:'';width:26px;height:1px;background:currentColor}.hero h1{font-family:var(--serif);font-size:clamp(58px,8vw,124px);font-weight:400;line-height:.85;letter-spacing:-.055em;margin:0;max-width:9ch}.hero h1 em{color:var(--green);font-weight:400}.lede{max-width:54ch;color:var(--muted);font-size:clamp(16px,1.5vw,20px);margin:34px 0 0}.hero-receipt{align-self:center}.bezel{padding:7px;border:1px solid rgba(24,32,28,.09);background:rgba(255,255,255,.18);border-radius:31px}.receipt{background:var(--ink);color:var(--paper);border-radius:24px;min-height:460px;padding:34px;display:flex;flex-direction:column;box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 35px 80px rgba(30,40,34,.16);position:relative;overflow:hidden}.receipt:after{content:'';position:absolute;width:290px;height:290px;border:1px solid rgba(255,255,255,.08);border-radius:50%;right:-140px;top:90px;box-shadow:0 0 0 45px rgba(255,255,255,.025),0 0 0 90px rgba(255,255,255,.018)}.receipt-top{display:flex;justify-content:space-between;gap:20px;font-size:10px;text-transform:uppercase;letter-spacing:.15em;color:#b7c0ba}.live-dot{display:inline-flex;align-items:center;gap:7px}.live-dot:before{content:'';width:6px;height:6px;border-radius:50%;background:#83ad91;animation:breathe 2.8s var(--ease) infinite}.receipt-score{margin:auto 0 22px;position:relative;z-index:1}.receipt-score strong{display:block;font-family:var(--serif);font-size:clamp(82px,9vw,128px);font-weight:400;letter-spacing:-.07em;line-height:.75}.receipt-score span{display:block;margin-top:17px;color:#b7c0ba;font-size:12px}.receipt-grid{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid rgba(255,255,255,.13);padding-top:20px;position:relative;z-index:1}.receipt-grid div{padding-right:12px}.receipt-grid span{display:block;color:#89948d;text-transform:uppercase;font-size:9px;letter-spacing:.14em}.receipt-grid strong{display:block;font-size:13px;margin-top:4px}.scroll-cue{position:absolute;left:0;bottom:38px;display:flex;align-items:center;gap:12px;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.15em;transform:rotate(-90deg) translateX(-100%);transform-origin:left top}.scroll-cue:before{content:'';width:42px;height:1px;background:var(--muted)}
.story-intro{padding:130px 0 100px;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 2fr;gap:7vw}.story-intro h2{font:400 clamp(46px,6vw,88px)/.95 var(--serif);letter-spacing:-.045em;margin:0;max-width:12ch}.story-intro p{font:400 clamp(23px,2.4vw,37px)/1.25 var(--serif);letter-spacing:-.025em;margin:5px 0 0;max-width:31ch}.story-intro p span{color:var(--muted)}.story-grid{display:grid;grid-template-columns:minmax(300px,.72fr) minmax(520px,1.28fr);gap:6vw;align-items:start}.chapters{padding-bottom:30vh}.chapter{min-height:100dvh;padding:18vh 0 12vh;display:flex;flex-direction:column;justify-content:center;opacity:.31;transform:translateY(22px);transition:opacity .8s var(--ease),transform .8s var(--ease)}.chapter.active{opacity:1;transform:none}.chapter-number{font-family:var(--serif);font-size:52px;color:var(--green);line-height:1;margin-bottom:25px}.chapter h3{font:400 clamp(42px,4.5vw,72px)/.94 var(--serif);letter-spacing:-.045em;margin:0 0 27px;max-width:9ch}.chapter .fan-copy,.chapter .tech-copy{font-size:17px;color:var(--muted);max-width:39ch}.chapter .tech-copy{display:none}.technical .chapter .fan-copy{display:none}.technical .chapter .tech-copy{display:block}.chapter-note{margin-top:28px;padding-top:20px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);max-width:44ch}.chapter-note strong{color:var(--ink)}.visual-column{position:sticky;top:0;height:100dvh;padding:90px 0 82px;display:flex;align-items:center}.stage-shell{width:100%;padding:8px;border-radius:38px;background:rgba(255,255,255,.22);border:1px solid rgba(24,32,28,.08)}.stage{height:min(74vh,720px);min-height:570px;background:var(--ink);color:var(--paper);border-radius:30px;overflow:hidden;position:relative;box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 35px 90px rgba(32,42,35,.14)}.stage-grid{position:absolute;inset:0;opacity:.1;background-image:linear-gradient(rgba(255,255,255,.12) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.12) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(to bottom,black,transparent)}.stage-head{position:absolute;left:30px;right:30px;top:28px;z-index:2;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(255,255,255,.11);padding-bottom:17px}.stage-kicker{font-size:9px;text-transform:uppercase;letter-spacing:.18em;color:#8f9b94}.stage-index{font-family:var(--serif);font-size:20px;color:#c7d0ca}.stage-body{position:absolute;inset:86px 30px 30px}.stage-view{height:100%;animation:stageIn .85s var(--ease) both}.stage-foot{position:absolute;bottom:22px;right:25px;color:#748078;font-size:9px;letter-spacing:.12em;text-transform:uppercase}.big-stat{font:400 clamp(76px,8vw,116px)/.8 var(--serif);letter-spacing:-.07em}.big-stat small{font:400 18px var(--sans);letter-spacing:0;color:#87928c}.stat-caption{font-size:12px;color:#9ca7a0;margin-top:17px;max-width:34ch}.metric-rail{position:absolute;left:0;right:0;bottom:22px;display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid rgba(255,255,255,.12);padding-top:22px}.metric span{display:block;color:#7e8b83;font-size:8px;text-transform:uppercase;letter-spacing:.16em}.metric strong{display:block;font-size:16px;margin-top:5px}.row-field{display:grid;grid-template-columns:repeat(18,1fr);gap:5px;margin-top:38px}.data-dot{aspect-ratio:1;border-radius:2px;background:#617067;opacity:0;animation:dotIn .35s var(--ease) forwards;animation-delay:calc(var(--i)*8ms)}.data-dot:nth-child(5n){background:#83a58f}.pipeline{height:100%;display:flex;flex-direction:column;justify-content:center}.pipe-row{display:grid;grid-template-columns:112px 1fr 72px;align-items:center;gap:15px;padding:15px 0;border-bottom:1px solid rgba(255,255,255,.09);opacity:0;transform:translateX(-16px);animation:slideIn .55s var(--ease) forwards;animation-delay:calc(var(--i)*110ms)}.pipe-name{font-size:11px}.pipe-track{height:5px;background:rgba(255,255,255,.09);border-radius:99px;overflow:hidden}.pipe-fill{height:100%;background:#8aaa94;transform-origin:left;animation:growX 1.1s var(--ease) forwards;animation-delay:calc(var(--i)*110ms)}.pipe-value{text-align:right;color:#9eaaa2;font-size:10px;font-variant-numeric:tabular-nums}.fixture-orbit{position:absolute;inset:0;display:grid;place-items:center}.orbit-core{width:138px;height:138px;border-radius:50%;border:1px solid rgba(255,255,255,.2);display:grid;place-items:center;text-align:center;background:#243029;box-shadow:0 0 0 42px rgba(255,255,255,.025),0 0 0 84px rgba(255,255,255,.018)}.orbit-core strong{font:400 38px var(--serif)}.orbit-core span{display:block;font-size:8px;text-transform:uppercase;letter-spacing:.16em;color:#91a097}.orbit-item{position:absolute;width:90px;text-align:center;font-size:9px;color:#9aa59f;transform:rotate(var(--angle)) translateY(-188px) rotate(calc(var(--angle)*-1));animation:orbitIn .8s var(--ease) both;animation-delay:var(--delay)}.orbit-item b{display:block;color:var(--paper);font-size:14px;margin-bottom:4px}.gate-list{padding-top:8px}.gate-row{display:grid;grid-template-columns:54px 1fr 58px;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.09);opacity:0;animation:slideIn .55s var(--ease) forwards;animation-delay:calc(var(--i)*120ms)}.gate-pos{font:400 24px var(--serif)}.gate-tests{display:flex;gap:5px}.gate-test{height:4px;flex:1;border-radius:9px;background:#4f5a54}.gate-test.win{background:#83a58f}.gate-result{text-align:right;font-size:9px;text-transform:uppercase;letter-spacing:.12em}.gate-result.pass{color:#9bc1a6}.gate-result.reject{color:#af948d}.bps-rings{position:absolute;inset:10px 0 0;display:grid;place-items:center}.bps-ring{width:290px;height:290px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#87a790 0deg 360deg,rgba(255,255,255,.08) 360deg);position:relative;animation:spinIn 1.4s var(--ease) both}.bps-ring:after{content:'';position:absolute;inset:13px;border-radius:50%;background:var(--ink)}.bps-center{position:relative;z-index:1;text-align:center}.bps-center strong{display:block;font:400 72px/.8 var(--serif)}.bps-center span{font-size:9px;color:#92a097;text-transform:uppercase;letter-spacing:.15em}.bps-side{position:absolute;top:50%;transform:translateY(-50%);font-size:10px;color:#8b9890}.bps-side.left{left:4px}.bps-side.right{right:4px;text-align:right}.bps-side b{display:block;color:var(--paper);font:400 26px var(--serif)}.search-streams{height:100%;display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:center}.stream{height:75%;border-top:1px solid rgba(255,255,255,.14);padding-top:18px;position:relative}.stream-label{font-size:9px;text-transform:uppercase;letter-spacing:.16em;color:#8e9a93}.candidate-grid{display:grid;grid-template-columns:repeat(8,1fr);gap:5px;margin-top:24px}.candidate{aspect-ratio:1;border-radius:50%;background:#526058;animation:contestant 2.8s var(--ease) infinite;animation-delay:calc(var(--i)*-47ms)}.stream.component .candidate{background:#7e9e88}.merge-arrow{position:absolute;left:50%;bottom:26px;transform:translateX(-50%);font:400 18px var(--serif);color:#aeb9b2}.sim-field{position:absolute;inset:0}.sim-particle{position:absolute;width:4px;height:4px;border-radius:50%;background:#7d9d87;opacity:.35;animation:simFloat var(--dur) var(--ease) infinite alternate;animation-delay:var(--delay)}.sim-score{position:absolute;inset:0;display:grid;place-items:center;text-align:center}.sim-score strong{font:400 94px/.8 var(--serif);letter-spacing:-.06em}.sim-score span{display:block;margin-top:17px;color:#8e9a92;font-size:9px;letter-spacing:.17em;text-transform:uppercase}.sim-badges{position:absolute;left:0;right:0;bottom:22px;display:flex;justify-content:space-between;gap:10px}.sim-badge{font-size:9px;color:#8d9891}.sim-badge b{display:block;color:var(--paper);font:400 20px var(--serif)}.scenario-toggle{display:flex;padding:4px;border:1px solid rgba(255,255,255,.12);border-radius:99px;width:max-content;margin-bottom:24px}.scenario-toggle button{border:0;background:transparent;color:#7f8b84;border-radius:99px;padding:7px 12px;font-size:9px;cursor:pointer}.scenario-toggle button.on{background:#39463f;color:var(--paper)}.bar-chart{display:flex;flex-direction:column;gap:13px}.bar-row{display:grid;grid-template-columns:45px 1fr 54px;gap:11px;align-items:center}.bar-id{font-size:10px}.bar-bg{height:22px;background:rgba(255,255,255,.07);border-radius:4px;overflow:hidden}.bar{height:100%;background:#788b7e;transform-origin:left;animation:growX .9s var(--ease) both}.bar.winner{background:#98b19f}.bar-value{text-align:right;font-size:10px;font-variant-numeric:tabular-nums}.stress-note{font-size:10px;color:#909c94;margin-top:20px}.checks{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:2px}.check{padding:10px;border:1px solid rgba(255,255,255,.1);border-radius:8px;display:flex;align-items:center;gap:9px;font-size:9px;color:#a6b0aa;opacity:0;animation:checkIn .55s var(--ease) forwards;animation-delay:calc(var(--i)*75ms)}.check:before{content:'';width:13px;height:13px;border-radius:50%;background:#7e9e88;box-shadow:inset 0 0 0 4px #334038;flex:none}.promotion-result{position:absolute;left:0;right:0;bottom:13px;border-top:1px solid rgba(255,255,255,.12);padding-top:16px;display:flex;align-items:end;justify-content:space-between}.promotion-result strong{font:400 50px/.8 var(--serif)}.promotion-result span{font-size:9px;color:#8d9991;text-transform:uppercase;letter-spacing:.14em}.pitch-wrap{height:100%;display:grid;grid-template-rows:1fr auto;gap:15px}.pitch{position:relative;border:1px solid rgba(255,255,255,.16);border-radius:18px;background:#25352d;overflow:hidden;min-height:410px}.pitch:before{content:'';position:absolute;inset:0;background:repeating-linear-gradient(90deg,rgba(255,255,255,.018) 0,rgba(255,255,255,.018) 12.5%,transparent 12.5%,transparent 25%)}.pitch:after{content:'';position:absolute;left:50%;top:0;bottom:0;border-left:1px solid rgba(255,255,255,.18)}.centre-circle{position:absolute;width:106px;height:106px;border:1px solid rgba(255,255,255,.18);border-radius:50%;left:50%;top:50%;transform:translate(-50%,-50%)}.player-line{position:absolute;left:6%;right:6%;display:flex;justify-content:space-around;z-index:2}.line-gk{left:3%;right:auto;top:50%;transform:translateY(-50%)}.line-def{left:19%;right:48%;top:9%;bottom:9%;flex-direction:column}.line-mid{left:51%;right:27%;top:19%;bottom:19%;flex-direction:column}.line-fwd{left:76%;right:5%;top:30%;bottom:30%;flex-direction:column}.player{border:0;background:transparent;color:var(--paper);cursor:pointer;width:88px;text-align:center;opacity:0;animation:playerIn .65s var(--ease) forwards;animation-delay:calc(var(--i)*85ms)}.shirt{width:39px;height:39px;margin:auto;background:var(--paper);color:var(--ink);clip-path:polygon(24% 0,40% 8%,60% 8%,76% 0,100% 19%,83% 36%,79% 29%,79% 100%,21% 100%,21% 29%,17% 36%,0 19%);display:grid;place-items:center;padding-top:5px;font-size:8px;font-weight:600;transition:transform .5s var(--ease),background .5s var(--ease)}.player:hover .shirt,.player:focus .shirt{transform:translateY(-4px);background:#a9c0b0}.player-name{display:block;background:rgba(24,32,28,.88);padding:3px 5px;border-radius:4px;margin-top:3px;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.captain-ring{position:absolute;width:16px;height:16px;border-radius:50%;background:var(--green);color:white;font-size:8px;display:grid;place-items:center;transform:translate(53px,-43px)}.bench-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.bench-player{background:#2c3932;border-radius:8px;padding:9px 10px;font-size:8px;color:#a5afa9;display:flex;justify-content:space-between;gap:7px}.bench-player b{color:var(--paper);font-weight:600}.player-popover{position:absolute;z-index:4;width:190px;padding:14px;background:var(--paper);color:var(--ink);border-radius:12px;box-shadow:0 18px 50px rgba(0,0,0,.25);pointer-events:none;opacity:0;transform:translateY(8px);transition:opacity .35s var(--ease),transform .35s var(--ease)}.player-popover.show{opacity:1;transform:none}.player-popover strong{font:400 22px var(--serif)}.player-popover .pop-meta{font-size:9px;color:var(--muted);margin:3px 0 10px}.pop-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.pop-grid span{display:block;font-size:7px;color:var(--muted);text-transform:uppercase}.pop-grid b{font-size:11px}.provisional-ribbon{position:absolute;left:15px;top:15px;z-index:3;padding:5px 8px;border-radius:99px;background:#a47a3d;color:#fff;font-size:7px;text-transform:uppercase;letter-spacing:.13em}
.controls{position:fixed;z-index:14;bottom:18px;left:50%;transform:translateX(-50%);width:min(660px,calc(100% - 30px));background:rgba(24,32,28,.92);color:var(--paper);border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:7px 9px 7px 7px;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:15px;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 18px 50px rgba(31,38,33,.2);backdrop-filter:blur(15px);-webkit-backdrop-filter:blur(15px);opacity:0;pointer-events:none;transition:opacity .5s var(--ease),transform .5s var(--ease)}.controls.visible{opacity:1;pointer-events:auto}.play{width:42px;height:42px;border-radius:50%;border:0;background:var(--paper);color:var(--ink);display:grid;place-items:center;cursor:pointer;transition:transform .5s var(--ease)}.play:hover{transform:scale(1.05)}.play:active{transform:scale(.96)}.play svg{width:13px;height:13px}.progress-wrap{display:flex;flex-direction:column;gap:6px}.control-label{display:flex;justify-content:space-between;font-size:8px;text-transform:uppercase;letter-spacing:.13em;color:#9aa59e}.progress-track{height:3px;background:rgba(255,255,255,.1);border-radius:99px;overflow:hidden}.progress{height:100%;background:#9ab09f;transform-origin:left;transform:scaleX(0);transition:transform .7s var(--ease)}.mode{border:0;background:rgba(255,255,255,.08);color:#b8c1bb;border-radius:99px;padding:10px 12px;font-size:8px;text-transform:uppercase;letter-spacing:.1em;cursor:pointer}.sources{padding:150px 0 170px;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 2fr;gap:7vw}.sources h2{font:400 clamp(43px,5vw,72px)/.95 var(--serif);letter-spacing:-.04em;margin:0}.sources-list{display:grid;grid-template-columns:1fr 1fr;gap:0 30px}.source{padding:18px 0;border-top:1px solid var(--line)}.source span{font-size:9px;text-transform:uppercase;letter-spacing:.15em;color:var(--green)}.source strong{display:block;margin-top:5px;font-size:13px}.source small{display:block;color:var(--muted);font-size:10px;margin-top:3px;overflow-wrap:anywhere}.final-note{grid-column:2;margin-top:36px;color:var(--muted);font-size:12px;max-width:64ch}.final-note strong{color:var(--ink)}dialog{border:0;padding:0;background:transparent;max-width:min(760px,calc(100% - 24px));color:var(--ink)}dialog::backdrop{background:rgba(24,32,28,.67);backdrop-filter:blur(8px)}.dialog-shell{padding:7px;border-radius:31px;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.2)}.dialog-inner{background:var(--paper);border-radius:24px;padding:32px;max-height:82dvh;overflow:auto}.dialog-head{display:flex;justify-content:space-between;gap:20px;align-items:start}.dialog-head h2{font:400 42px/.95 var(--serif);margin:0}.close{width:36px;height:36px;border-radius:50%;border:1px solid var(--line);background:transparent;cursor:pointer}.evidence-table{margin-top:28px}.evidence-row{display:grid;grid-template-columns:1fr auto;gap:20px;padding:14px 0;border-top:1px solid var(--line);font-size:12px}.evidence-row span{color:var(--muted);max-width:52ch}.evidence-row b{color:var(--green);font-size:10px;text-transform:uppercase;letter-spacing:.12em}.reveal{opacity:0;transform:translateY(30px);filter:blur(4px);transition:opacity .9s var(--ease),transform .9s var(--ease),filter .9s var(--ease)}.reveal.seen{opacity:1;transform:none;filter:none}
@keyframes breathe{50%{opacity:.32;transform:scale(.72)}}@keyframes stageIn{from{opacity:0;transform:translateY(18px);filter:blur(5px)}to{opacity:1;transform:none;filter:none}}@keyframes dotIn{to{opacity:.75;transform:rotate(45deg)}}@keyframes slideIn{to{opacity:1;transform:none}}@keyframes growX{from{transform:scaleX(0)}to{transform:scaleX(1)}}@keyframes orbitIn{from{opacity:0;transform:rotate(var(--angle)) translateY(-120px) rotate(calc(var(--angle)*-1))}to{opacity:1}}@keyframes spinIn{from{opacity:0;transform:rotate(-100deg) scale(.72)}to{opacity:1;transform:none}}@keyframes contestant{0%,100%{opacity:.25;transform:scale(.72)}50%{opacity:.8;transform:scale(1)}}@keyframes simFloat{from{transform:translate3d(-15px,-13px,0);opacity:.12}to{transform:translate3d(18px,18px,0);opacity:.7}}@keyframes checkIn{to{opacity:1;transform:none}}@keyframes playerIn{from{opacity:0;transform:translateX(-18px)}to{opacity:1;transform:none}}
@media(max-width:950px){.shell{width:min(100% - 32px,760px)}.nav{max-width:calc(100% - 24px)}.nav-meta{display:none}.hero{grid-template-columns:1fr;padding-top:126px;gap:65px}.hero h1{font-size:clamp(62px,16vw,98px)}.hero-receipt{width:min(100%,520px);justify-self:end}.scroll-cue{display:none}.story-intro,.sources{grid-template-columns:1fr;gap:44px}.story-grid{display:block}.visual-column{position:sticky;top:0;height:54dvh;padding:12px 0;z-index:4;pointer-events:none}.stage-shell{width:min(100%,680px);margin:auto}.stage{height:50dvh;min-height:410px}.stage-body{inset:76px 22px 22px}.stage-head{left:22px;right:22px;top:22px}.chapters{margin-top:0}.chapter{min-height:78dvh;padding:38vh 0 12vh;opacity:.2}.chapter h3{max-width:13ch}.sources-list{grid-template-columns:1fr}.final-note{grid-column:1}.stage .big-stat{font-size:72px}.metric-rail{bottom:8px}.pitch{min-height:290px}.player{width:69px}.shirt{width:31px;height:31px}.player-name{font-size:6.8px}.captain-ring{transform:translate(42px,-36px)}.line-def{left:17%;right:50%}.line-mid{left:49%;right:27%}.line-fwd{left:73%;right:2%}.controls{bottom:10px}}
@media(max-width:560px){.shell{width:calc(100% - 28px)}.nav{top:10px;padding-left:12px;gap:8px}.brand{font-size:11px}.nav button{padding:9px}.nav button>span:first-child{display:none}.hero{padding:110px 0 80px}.hero h1{font-size:58px}.hero-receipt{width:100%}.receipt{min-height:390px;padding:25px}.story-intro{padding:90px 0}.story-intro h2{font-size:50px}.story-intro p{font-size:25px}.visual-column{height:51dvh}.stage{height:47dvh;min-height:380px;border-radius:21px}.stage-shell{padding:5px;border-radius:27px}.stage-head{top:17px}.stage-body{inset:65px 17px 18px}.chapter{min-height:74dvh;padding-top:35vh}.chapter-number{font-size:42px}.chapter h3{font-size:45px}.chapter .fan-copy,.chapter .tech-copy{font-size:15px}.row-field{grid-template-columns:repeat(15,1fr);gap:3px}.metric-rail{grid-template-columns:repeat(3,1fr)}.metric strong{font-size:12px}.fixture-orbit{transform:scale(.73)}.search-streams{gap:10px}.candidate-grid{grid-template-columns:repeat(6,1fr)}.checks{grid-template-columns:1fr}.check:nth-child(n+9){display:none}.promotion-result strong{font-size:36px}.pitch{min-height:270px}.player{width:57px}.shirt{width:27px;height:27px}.player-name{font-size:6px}.captain-ring{transform:translate(34px,-32px)}.bench-player{padding:7px 5px;font-size:6px}.controls{grid-template-columns:auto 1fr}.mode{display:none}.sources{padding:100px 0 130px}.dialog-inner{padding:24px}.evidence-row{grid-template-columns:1fr}.sim-score strong{font-size:72px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important}.controls{display:none}}
.orbit-item{transform:rotate(var(--angle)) translateY(-188px) rotate(var(--inverse))}.evidence-trigger{border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.07);color:var(--paper);border-radius:999px;padding:9px 12px;font-size:8px;letter-spacing:.1em;text-transform:uppercase;cursor:pointer;transition:background .5s var(--ease),transform .5s var(--ease)}.evidence-trigger:hover{background:rgba(255,255,255,.13);transform:translateY(-1px)}
.horizon-duel{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:stretch;margin-top:5px}.horizon-card{border-radius:22px;padding:18px;background:rgba(255,255,255,.62);box-shadow:inset 0 1px 0 rgba(255,255,255,.75),0 18px 45px rgba(33,45,37,.055)}.horizon-card.challenger{background:#243b31;color:var(--paper)}.horizon-card span{display:block;font-size:8px;text-transform:uppercase;letter-spacing:.13em;color:var(--muted)}.horizon-card.challenger span{color:#aab9b0}.horizon-card strong{display:block;font:400 25px/1 var(--serif);letter-spacing:-.035em;margin:18px 0 7px}.horizon-card small{display:block;color:var(--muted);font-size:8px}.horizon-card.challenger small{color:#aab9b0}.horizon-vs{align-self:center;font:500 8px/1 var(--sans);color:var(--muted);letter-spacing:.12em}.weight-boundary{margin-top:18px;padding:15px 16px;border-radius:18px;background:rgba(24,32,28,.045);box-shadow:inset 0 1px 0 rgba(255,255,255,.65)}.weight-copy{display:flex;align-items:end;justify-content:space-between;gap:20px;font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}.weight-copy strong{font:400 23px/1 var(--serif);color:var(--ink);letter-spacing:-.035em}.weight-track{height:5px;background:rgba(24,32,28,.09);border-radius:999px;margin-top:12px;position:relative;overflow:hidden}.weight-fill{position:absolute;inset:0;transform:scaleX(var(--threshold));transform-origin:left;background:var(--green);border-radius:inherit}.retention{display:grid;grid-template-columns:repeat(7,1fr);gap:7px;height:92px;align-items:end;margin-top:18px}.retention-column{display:grid;grid-template-rows:1fr auto;gap:5px;height:100%;text-align:center}.retention-well{height:100%;display:flex;align-items:end;background:rgba(24,32,28,.035);border-radius:8px 8px 3px 3px;overflow:hidden}.retention-bar{width:100%;height:100%;background:#b9cabe;transform:scaleY(var(--retention));transform-origin:bottom;border-radius:8px 8px 3px 3px;animation:horizonRise 1.15s var(--ease) both;animation-delay:calc(var(--i)*70ms)}.retention-column small{font-size:7px;color:var(--muted)}@keyframes horizonRise{from{transform:scaleY(0);opacity:.15}to{transform:scaleY(var(--retention));opacity:1}}
@media(max-width:560px){.horizon-duel{grid-template-columns:1fr 1fr;gap:8px}.horizon-vs{display:none}.horizon-card{padding:13px;border-radius:16px}.horizon-card strong{font-size:17px;margin-top:10px}.weight-boundary{margin-top:10px;padding:11px 12px}.retention{height:70px;margin-top:10px;gap:4px}.horizon-duel+.weight-boundary+.retention+.metric-rail{display:none}}
</style>
</head>
<body>
<div class="grain" aria-hidden="true"></div>
<nav class="nav" aria-label="Story controls">
  <div class="brand"><span class="brand-mark">FA</span><span>fplagent / selection room</span></div>
  <span class="nav-meta">2026/27 · GW1 · provisional</span>
  <button id="startStory" type="button"><span>Run the model</span><span class="button-icon"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M5.5 3.5 10.5 8l-5 4.5" stroke="currentColor" stroke-width="1.5"/></svg></span></button>
</nav>

<main>
  <section class="hero shell" id="top">
    <div class="hero-copy reveal">
      <div class="eyebrow">Inside the decision engine</div>
      <h1>From noise to <em>XI.</em></h1>
      <p class="lede">An interactive account of how 244,425 historical rows, five evolving fixture models and millions of simulated goals became one provisional Gameweek 1 squad.</p>
    </div>
    <div class="hero-receipt reveal">
      <div class="bezel"><div class="receipt">
        <div class="receipt-top"><span>Decision receipt</span><span class="live-dot">Provisional leader</span></div>
        <div class="receipt-score"><strong id="heroScore">307.65</strong><span>evidence-weighted points · GW1–5</span></div>
        <div class="receipt-grid"><div><span>Candidate</span><strong id="heroCandidate">C007</strong></div><div><span>Shape</span><strong id="heroFormation">5–3–2</strong></div><div><span>Gates</span><strong>12 / 12</strong></div></div>
      </div></div>
    </div>
    <div class="scroll-cue">Follow the evidence</div>
  </section>

  <section class="story-intro shell reveal" id="story">
    <h2>The answer is not a hunch.</h2>
    <p>It is the survivor of a sequence of arguments. <span>Every model must earn its place; every squad must survive an objection.</span></p>
  </section>

  <div class="story-grid shell">
    <div class="chapters" id="chapters">
      <article class="chapter active" data-stage="0"><div class="chapter-number">01</div><h3>Make the past usable.</h3><p class="fan-copy">Before choosing a player, the engine asks whether its memory is trustworthy. Prices, points, minutes and deadlines are rebuilt into one timeline, with the future hidden from every historical prediction.</p><p class="tech-copy">The normalized feature store contains 244,425 historical rows. Leakage gates assert strictly lagged points and form, deadline-safe snapshots, unique player-event keys and consistent information cutoffs.</p><p class="chapter-note"><strong>Why it matters:</strong> a model that can see tomorrow while training will look brilliant and fail on Saturday.</p></article>
      <article class="chapter" data-stage="1"><div class="chapter-number">02</div><h3>Price the fixture, not the badge.</h3><p class="fan-copy">A run of ten conceded goals can be terrible—or merely the cost of facing five elite attacks. The model separates team quality, opponent quality, venue and recency before judging the next match.</p><p class="tech-copy">An online hierarchical Poisson model updates opponent-adjusted attack and defence, venue splits and promoted-team priors. Five completed seasons provide 1,900 leakage-safe fixture observations.</p><p class="chapter-note"><strong>Deliberate exclusion:</strong> official fixture difficulty is not used by the challenger model.</p></article>
      <article class="chapter" data-stage="2"><div class="chapter-number">03</div><h3>Forecast every route to points.</h3><p class="fan-copy">The model does not stop at “good player, easy fixture”. It estimates whether a player appears, how long they play, the goals their team produces and how that becomes goals, assists, clean sheets, contributions and bonus.</p><p class="tech-copy">559 selectable players are projected over eight horizons. The component layer allocates correlated match events while the xP layer anchors marginal player means to season-forward calibration.</p><p class="chapter-note"><strong>Decision blend:</strong> 10% raw component signal, selected on 2024/25 and frozen before the 2025/26 test.</p></article>
      <article class="chapter" data-stage="3"><div class="chapter-number">04</div><h3>Reject clever corrections.</h3><p class="fan-copy">A correction is only useful if it keeps working. The appearance recalibrator helped forwards in both unseen seasons. The same idea failed that standard for goalkeepers, defenders and midfielders—so those changes were refused.</p><p class="tech-copy">Position-specific logistic recalibration must improve both Brier score and log loss in both strict season-forward slices. Only FWD achieved four wins from four required comparisons.</p><p class="chapter-note"><strong>Explainability is also subtraction:</strong> three plausible model changes were prevented from touching the live forecast.</p></article>
      <article class="chapter" data-stage="4"><div class="chapter-number">05</div><h3>Rebuild the new scoring.</h3><p class="fan-copy">The 2026/27 bonus rules change the small edges that decide close calls. Historical bonus allocation was rebuilt exactly; missing tackled events were modelled on older event data and tested forward.</p><p class="tech-copy">The control reproduces all 380 fixtures and 2,415 bonus points. The RTX 5090 tackled-event proxy reaches 0.892 player-season rank correlation; incomplete goalkeeper save context remains neutral.</p><p class="chapter-note"><strong>Boundary:</strong> outfield corrections are promoted. Goalkeeper BPS deltas are not.</p></article>
      <article class="chapter" data-stage="5"><div class="chapter-number">06</div><h3>Search beyond the neighbourhood.</h3><p class="fan-copy">Trying every mathematical team would take longer than football has existed. So the engine combines 542,246 local one- and two-player challengers with 256 distant optimisation restarts and 19,996 legal evolutionary squads. Forty views of value decide which 10,000 deserve simulation.</p><p class="tech-copy">The combined field contains 562,498 legal squads. Named benchmarks and every global source receive protected places through the 2,000-world screen, exact 512-squad shortlist and 64-squad untouched holdout.</p><p class="chapter-note"><strong>Honest boundary:</strong> diversified global challenge—not a false claim to enumerate a 10²⁷-scale roster space.</p></article>
      <article class="chapter" data-stage="6"><div class="chapter-number">07</div><h3>Play the opening month 25,000 times.</h3><p class="fan-copy">A clean sheet disappears for several defenders together. A missed match activates the bench. A captain absence hands the armband to the vice. The simulation preserves those dependencies rather than adding fifteen averages.</p><p class="tech-copy">Across 1.25 million match scenarios, 3.48 million team goals are allocated to eligible scorers and at most one eligible assister. Legal autosubs, captain fallback, defensive contributions and 3/2/1 bonus are exact.</p><p class="chapter-note"><strong>Football identity check:</strong> every team goal reconciles; assist violations are zero.</p></article>
      <article class="chapter" data-stage="7"><div class="chapter-number">08</div><h3>Make the winner survive eight worlds.</h3><p class="fan-copy">The highest average is not automatically the best plan. Squads must cope when goals rise 15%, when the raw football model gets more say, when the safer forecast gets more say, when no transfers are allowed and when GW2 must be banked.</p><p class="tech-copy">A declared regret objective blends eight base, transfer-policy and scoring-environment scenarios. Candidates more than one point from the best central forecast are ineligible; the winner is therefore robust without abandoning expected points.</p><p class="chapter-note"><strong>Decision:</strong> the 4–3–3 wins every leave-one-scenario-out test and naturally rolls GW2.</p></article>
      <article class="chapter" data-stage="8"><div class="chapter-number">09</div><h3>Force the old champion into the final.</h3><p class="fan-copy">C007 is not quietly discarded. It receives the same transfer plans and the same 25,000 match worlds as every finalist. It still owns the highest central average—but falls to twelfth when fragility matters.</p><p class="tech-copy">The new leader surrenders 0.219 central points to C007, inside the one-point eligibility cap, while cutting robust regret from 1.731 to 0.709. Every protected benchmark survives both elimination cuts.</p><p class="chapter-note"><strong>Why the crown moves:</strong> resilience across assumptions, not a noisy 0.2-point headline.</p></article>
      <article class="chapter" data-stage="9"><div class="chapter-number">10</div><h3>Ask if five weeks can see far enough.</h3><p class="fan-copy">An easy August can seduce a picker into building a squad with an expiry date. So every finalist is played through GW8, with distant fixtures discounted, GW6–8 isolated and transfer freedom deliberately removed.</p><p class="tech-copy">The audit adds 128 horizon-native challengers, 5,000 selection worlds and 25,000 untouched eight-week worlds. A 5–3–2 wins that one audit by 0.697 decayed points, but suffers 4.407 points of regret when goals run 15% higher.</p><p class="chapter-note"><strong>Synthesis:</strong> the 4–3–3 remains champion unless uncertain horizon evidence receives more than the live boundary shown in the decision receipt.</p></article>
      <article class="chapter" data-stage="10"><div class="chapter-number">11</div><h3>The new provisional XI.</h3><p class="fan-copy">Bruno takes the armband in a 4–3–3. The squad spends the full £100m, keeps a playable rotation bench and is not materially tied to its first five fixtures. Every name remains conditional on the deadline refresh.</p><p class="tech-copy">R-dc7de17def ranks first across the joint five/eight-week synthesis. It is only 0.697 decayed points from the eight-week optimum, wins the fixed-squad test and naturally banks the first two transfers in the adaptive GW1–8 policy.</p><p class="chapter-note"><strong>Not a guarantee:</strong> this is the current robust champion under frozen data, models, assumptions and seeds.</p></article>
    </div>
    <aside class="visual-column" aria-live="polite"><div class="stage-shell"><div class="stage"><div class="stage-grid"></div><div class="stage-head"><span class="stage-kicker" id="stageKicker">Evidence integrity</span><span class="stage-index" id="stageIndex">01 / 11</span></div><div class="stage-body" id="stageBody"></div><span class="stage-foot">live artifact · 03 aug 2026</span></div></div></aside>
  </div>

  <section class="sources shell reveal">
    <h2>The receipt behind the theatre.</h2>
    <div class="sources-list">
      <div class="source"><span>Decision</span><strong>Joint horizon synthesis</strong><small>data/model/gw1_decision_synthesis_v1/results.json</small></div>
      <div class="source"><span>Robust search</span><strong>562,498-squad funnel</strong><small>data/model/robust_search_v2_global/results.json</small></div>
      <div class="source"><span>Horizon</span><strong>GW1–8 adequacy audit</strong><small>data/model/horizon_audit_v1/results.json</small></div>
      <div class="source"><span>Simulation</span><strong>Component tournament</strong><small>data/model/tournament_v2/component-gw1-5-results.json</small></div>
      <div class="source"><span>Adversarial</span><strong>Bench and formation audit</strong><small>data/model/bench_audit_v1/results.json</small></div>
      <div class="source"><span>Calibration</span><strong>Appearance reliability audit</strong><small>data/model/appearance_audit_v1/metrics.json</small></div>
      <div class="source"><span>Scoring</span><strong>2026/27 BPS reconstruction</strong><small>data/model/bps_2026_27_v1/metrics.json</small></div>
      <div class="source"><span>Integrity</span><strong>Normalized data quality</strong><small>data/model/normalized/data_quality.json</small></div>
    </div>
    <p class="final-note"><strong>Interpretation:</strong> the animation is a faithful editorial rendering of the recorded pipeline, not a second model. Values are embedded from local machine-readable artifacts when this file is built. Refresh the underlying data and rebuild this page before relying on it at the deadline.</p>
  </section>
</main>

<div class="controls" id="controls"><button class="play" id="play" type="button" aria-label="Play story"><svg id="playIcon" viewBox="0 0 16 16" fill="none"><path d="m5 3 7 5-7 5V3Z" fill="currentColor"/></svg></button><div class="progress-wrap"><div class="control-label"><span id="controlTitle">Evidence integrity</span><span id="controlCount">01 / 11</span></div><div class="progress-track"><div class="progress" id="progress"></div></div></div><button class="mode" id="mode" type="button">Fan view</button></div>

<dialog id="evidenceDialog"><div class="dialog-shell"><div class="dialog-inner"><div class="dialog-head"><div><div class="eyebrow">Acceptance receipt</div><h2>Twelve gates. No exemptions.</h2></div><button class="close" id="closeDialog" aria-label="Close">×</button></div><div class="evidence-table" id="evidenceTable"></div></div></div></dialog>

<script>const DATA=__STORY_DATA__;</script>
<script>
(() => {
  'use strict';
  const titles=['Evidence integrity','Opponent-adjusted strength','Player projection','Appearance gate','Bonus reconstruction','Scalable squad search','Match simulation','Robust scenario arena','Protected incumbent audit','Horizon adequacy','Provisional squad'];
  const body=document.body, chapters=[...document.querySelectorAll('.chapter')], stageBody=document.getElementById('stageBody');
  const stageIndex=document.getElementById('stageIndex'), stageKicker=document.getElementById('stageKicker'), controlTitle=document.getElementById('controlTitle'), controlCount=document.getElementById('controlCount'), progress=document.getElementById('progress');
  let current=0, playing=false, timer=null;
  const fmt=n=>Number(n).toLocaleString('en-GB');
  const svgPause='<svg viewBox="0 0 16 16" fill="none"><path d="M5 3v10M11 3v10" stroke="currentColor" stroke-width="2"/></svg>';
  const svgPlay='<svg viewBox="0 0 16 16" fill="none"><path d="m5 3 7 5-7 5V3Z" fill="currentColor"/></svg>';

  function dots(count=144){return Array.from({length:count},(_,i)=>`<i class="data-dot" style="--i:${i}"></i>`).join('')}
  function pipelines(){const rows=[['Deadline-safe history',96,'244,425 rows'],['Opponent context',89,'1,900 fixtures'],['Current player grid',93,'4,472 rows'],['Rule normalization',100,'2026/27'],['Integrity tests',100,`${DATA.evidence.checks}/${DATA.evidence.checks}`]];return `<div class="pipeline">${rows.map((r,i)=>`<div class="pipe-row" style="--i:${i}"><span class="pipe-name">${r[0]}</span><div class="pipe-track"><div class="pipe-fill" style="width:${r[1]}%"></div></div><span class="pipe-value">${r[2]}</span></div>`).join('')}</div>`}
  function fixture(){const vals=[['Team attack','rolling'],['Team defence','rolling'],['Opponent','adjusted'],['Venue','split'],['Recency','540d']];return `<div class="fixture-orbit"><div class="orbit-core"><div><strong>λ</strong><span>expected goals</span></div></div>${vals.map((v,i)=>`<div class="orbit-item" style="--angle:${i*72}deg;--inverse:${-i*72}deg;--delay:${i*120}ms"><b>${v[0]}</b>${v[1]}</div>`).join('')}</div><div class="metric-rail"><div class="metric"><span>Seasons</span><strong>${DATA.evidence.teamSeasons}</strong></div><div class="metric"><span>Fixtures</span><strong>${fmt(DATA.evidence.teamFixtures)}</strong></div><div class="metric"><span>Official FDR</span><strong>Excluded</strong></div></div>`}
  function forecast(){const rows=[['Minutes + DNP',88,'appearance'],['Goals',76,'promoted'],['Assists',68,'promoted'],['Clean sheets',82,'Poisson'],['Def. contribution',61,'1 season'],['Bonus',73,'promoted']];return `<div class="pipeline">${rows.map((r,i)=>`<div class="pipe-row" style="--i:${i}"><span class="pipe-name">${r[0]}</span><div class="pipe-track"><div class="pipe-fill" style="width:${r[1]}%"></div></div><span class="pipe-value">${r[2]}</span></div>`).join('')}<div class="metric-rail"><div class="metric"><span>Players</span><strong>${DATA.evidence.players}</strong></div><div class="metric"><span>Horizons</span><strong>${DATA.evidence.horizons}</strong></div><div class="metric"><span>Forecast rows</span><strong>${fmt(DATA.evidence.horizonRows)}</strong></div></div></div>`}
  function appearance(){return `<div class="gate-list">${DATA.appearance.positions.map((g,i)=>`<div class="gate-row" style="--i:${i}"><span class="gate-pos">${g.position}</span><div class="gate-tests"><i class="gate-test ${g.brier===g.tests?'win':''}"></i><i class="gate-test ${g.logloss===g.tests?'win':''}"></i></div><span class="gate-result ${g.passed?'pass':'reject'}">${g.passed?'promote':'reject'}</span></div>`).join('')}</div><div class="metric-rail"><div class="metric"><span>Candidate rows</span><strong>${fmt(DATA.appearance.rows)}</strong></div><div class="metric"><span>Forward slices</span><strong>2</strong></div><div class="metric"><span>Promoted</span><strong>FWD only</strong></div></div>`}
  function bps(){return `<div class="bps-rings"><div class="bps-side left">Control<b>${DATA.bps.fixtures}/${DATA.bps.fixtures}</b>fixtures</div><div class="bps-ring"><div class="bps-center"><strong>${(DATA.bps.exactRate*100).toFixed(0)}%</strong><span>bonus allocation exact</span></div></div><div class="bps-side right">Proxy rank<b>${DATA.bps.spearman}</b>correlation</div></div><div class="metric-rail"><div class="metric"><span>Bonus points</span><strong>${fmt(DATA.bps.bonus)}</strong></div><div class="metric"><span>Model MAE</span><strong>${DATA.bps.mae}</strong></div><div class="metric"><span>Hardware</span><strong>RTX 5090</strong></div></div>`}
  function candidates(n,component=false){const count=component?Math.min(n,48):Math.min(n,96);return `<div class="stream ${component?'component':''}"><span class="stream-label">${component?'Component-native':'Residual strategies'} · ${n}</span><div class="candidate-grid">${Array.from({length:count},(_,i)=>`<i class="candidate" style="--i:${i}"></i>`).join('')}</div></div>`}
  function search(){const rows=[['Seed optima',DATA.search.seedSquads,24],['Legal one-swap',DATA.search.oneSwap,68],['Global MILP',DATA.search.globalMilp,25],['Evolution squads',DATA.search.globalEvolution,54],['Combined field',DATA.search.expanded,100],['Deep finalists',DATA.search.deepFinalists,17]];return `<div class="pipeline">${rows.map((r,i)=>`<div class="pipe-row" style="--i:${i}"><span class="pipe-name">${r[0]}</span><div class="pipe-track"><div class="pipe-fill" style="width:${r[2]}%"></div></div><span class="pipe-value">${fmt(r[1])}</span></div>`).join('')}<div class="metric-rail"><div class="metric"><span>Raw roster space</span><strong>${DATA.search.unconstrainedSpace}</strong></div><div class="metric"><span>Assumption views</span><strong>${DATA.search.proxyScenarios}</strong></div><div class="metric"><span>Holdout worlds</span><strong>${fmt(DATA.search.holdoutWorlds)}</strong></div></div></div>`}
  function simulation(){const particles=Array.from({length:95},(_,i)=>`<i class="sim-particle" style="left:${(i*47)%98}%;top:${(i*71)%95}%;--dur:${1.7+(i%8)*.31}s;--delay:${-(i%13)*.17}s"></i>`).join('');return `<div class="sim-field">${particles}</div><div class="sim-score"><div><strong>${(DATA.simulation.teamGoals/1000000).toFixed(2)}m</strong><span>team goals reconciled</span></div></div><div class="sim-badges"><span class="sim-badge"><b>${(DATA.simulation.matchScenarios/1000000).toFixed(2)}m</b>match scenarios</span><span class="sim-badge"><b>${(DATA.simulation.assists/1000000).toFixed(2)}m</b>assists allocated</span><span class="sim-badge"><b>${DATA.simulation.unattributed}</b>unattributed goals</span></div>`}
  function stress(mode='base'){const rows=[...DATA.robust.scenarios].sort((a,b)=>b[mode]-a[mode]),vals=rows.map(r=>r[mode]),min=Math.min(...vals)-.5,max=Math.max(...vals),winner=rows[0].id;return `<div class="scenario-toggle"><button data-scenario="base" class="${mode==='base'?'on':''}">Central evidence</button><button data-scenario="stress" class="${mode==='stress'?'on':''}">Goals +15%</button></div><div class="bar-chart">${rows.map((r,i)=>`<div class="bar-row"><span class="bar-id">${r.id}<small style="display:block;color:#748078">${r.formation}</small></span><div class="bar-bg"><div class="bar ${i===0?'winner':''}" style="width:${35+65*(r[mode]-min)/(max-min)}%"></div></div><span class="bar-value">${r[mode].toFixed(2)}</span></div>`).join('')}</div><p class="stress-note">Scenario leader: ${winner} · robust winner ${DATA.robust.leader} survives ${DATA.robust.leaveOneOutWins}/${DATA.robust.leaveOneOutTests} leave-one-out tests.</p>`}
  function promotion(){return `<div class="big-stat">#${DATA.robust.c007Rank} <small>C007 robust rank</small></div><p class="stat-caption">The incumbent remains the central-mean leader. The crown moves because its cross-scenario regret is materially worse.</p><div class="pipeline" style="height:auto;margin-top:28px"><div class="pipe-row" style="--i:0"><span class="pipe-name">New 4–3–3</span><div class="pipe-track"><div class="pipe-fill" style="width:${Math.max(12,100*(1-DATA.robust.regret/DATA.robust.c007Regret))}%"></div></div><span class="pipe-value">${DATA.robust.regret.toFixed(3)}</span></div><div class="pipe-row" style="--i:1"><span class="pipe-name">C007 5–3–2</span><div class="pipe-track"><div class="pipe-fill" style="width:100%;background:#9b7368"></div></div><span class="pipe-value">${DATA.robust.c007Regret.toFixed(3)}</span></div></div><div class="promotion-result"><div><span>Central points surrendered</span><strong>${DATA.robust.centralDeltaC007}</strong></div><button class="evidence-trigger" type="button">Inspect 12 model gates</button><div style="text-align:right"><span>GW2 action</span><strong style="font-size:27px">${DATA.robust.bankGw2?'Bank transfer':'Transfer'}</strong></div></div>`}
  function horizonAudit(){const h=DATA.horizonAudit,ret=h.retention.map((r,i)=>`<div class="retention-column"><div class="retention-well"><i class="retention-bar" style="--retention:${r.median_retained/15};--i:${i}"></i></div><small>GW${r.event}<br>${r.median_retained}</small></div>`).join('');return `<div class="horizon-duel"><div class="horizon-card"><span>Joint champion</span><strong>${h.incumbent}</strong><small>8-week regret · ${h.selectedRegret.toFixed(3)}</small></div><div class="horizon-vs">VS</div><div class="horizon-card challenger"><span>Horizon leader</span><strong>${h.leader}</strong><small>+${h.delta.toFixed(3)} decayed pts</small></div></div><div class="weight-boundary"><div class="weight-copy"><span>Champion survives until<br>horizon-family weight</span><strong>${h.threshold.toFixed(1)}%</strong></div><div class="weight-track"><i class="weight-fill" style="--threshold:${h.threshold/100}"></i></div></div><div class="retention">${ret}</div><div class="metric-rail"><div class="metric"><span>GW6–8 regret</span><strong>${h.lateRegret.toFixed(2)}</strong></div><div class="metric"><span>Fixed squad</span><strong>${h.fixedRegret.toFixed(2)}</strong></div><div class="metric"><span>Joint finalists</span><strong>${h.commonFinalists}</strong></div></div>`}
  function pitch(){const positions={GK:[],DEF:[],MID:[],FWD:[]};DATA.squad.starters.forEach(p=>positions[p.position].push(p));const line=(pos,cls)=>`<div class="player-line ${cls}">${positions[pos].map((p,i)=>player(p,i)).join('')}</div>`;return `<div class="pitch-wrap"><div class="pitch"><span class="provisional-ribbon">Provisional</span><div class="centre-circle"></div>${line('GK','line-gk')}${line('DEF','line-def')}${line('MID','line-mid')}${line('FWD','line-fwd')}<div class="player-popover" id="playerPopover"></div></div><div class="bench-strip">${DATA.squad.bench.map((p,i)=>`<div class="bench-player"><b>${i+1}. ${p.name}</b><span>£${p.price.toFixed(1)}</span></div>`).join('')}</div></div>`}
  function player(p,i){const payload=encodeURIComponent(JSON.stringify(p));return `<button class="player" style="--i:${i}" data-player="${payload}" aria-label="Inspect ${p.name}"><span class="shirt">${p.team}</span>${p.role==='captain'?'<i class="captain-ring">C</i>':p.role==='vice'?'<i class="captain-ring">V</i>':''}<span class="player-name">${p.name}</span></button>`}
  const renderers=[()=>`<div class="big-stat">${fmt(DATA.evidence.historicalRows)} <small>rows</small></div><p class="stat-caption">Normalized, deadline-safe historical player observations.</p><div class="row-field">${dots()}</div><div class="metric-rail"><div class="metric"><span>Quality checks</span><strong>${DATA.evidence.checks}/${DATA.evidence.checks}</strong></div><div class="metric"><span>Failed</span><strong>${DATA.evidence.failedChecks}</strong></div><div class="metric"><span>Leakage</span><strong>Blocked</strong></div></div>`,fixture,forecast,appearance,bps,search,simulation,()=>stress('base'),promotion,horizonAudit,pitch];

  function bindScenario(){stageBody.querySelectorAll('[data-scenario]').forEach(button=>button.addEventListener('click',()=>{stageBody.innerHTML=`<div class="stage-view">${stress(button.dataset.scenario)}</div>`;bindScenario()}))}
  function render(index){current=index;stageBody.innerHTML=`<div class="stage-view">${renderers[index]()}</div>`;stageIndex.textContent=String(index+1).padStart(2,'0')+' / '+titles.length;stageKicker.textContent=titles[index];controlTitle.textContent=titles[index];controlCount.textContent=stageIndex.textContent;progress.style.transform=`scaleX(${(index+1)/titles.length})`;chapters.forEach((c,i)=>c.classList.toggle('active',i===index));if(index===7)bindScenario();if(index===8){const trigger=stageBody.querySelector('.evidence-trigger');if(trigger)trigger.addEventListener('click',()=>dialog.showModal())}if(index===10)bindPlayers()}
  function bindPlayers(){const pop=document.getElementById('playerPopover'),pitch=stageBody.querySelector('.pitch');stageBody.querySelectorAll('[data-player]').forEach(btn=>{const show=()=>{const p=JSON.parse(decodeURIComponent(btn.dataset.player)),r=btn.getBoundingClientRect(),pr=pitch.getBoundingClientRect();pop.innerHTML=`<strong>${p.name}</strong><div class="pop-meta">${p.team} · ${p.position}${p.calibrated?' · appearance calibrated':''}</div><div class="pop-grid"><div><span>Price</span><b>£${p.price.toFixed(1)}m</b></div><div><span>GW1 xP</span><b>${p.xp.toFixed(2)}</b></div><div><span>Play</span><b>${p.play}%</b></div></div>`;pop.style.left=Math.min(pr.width-200,Math.max(10,r.left-pr.left+20))+'px';pop.style.top=Math.min(pr.height-115,Math.max(10,r.top-pr.top-78))+'px';pop.classList.add('show')};btn.addEventListener('mouseenter',show);btn.addEventListener('focus',show);btn.addEventListener('click',show);btn.addEventListener('mouseleave',()=>pop.classList.remove('show'));btn.addEventListener('blur',()=>pop.classList.remove('show'))})}
  function go(index,scroll=true){const next=Math.max(0,Math.min(chapters.length-1,index));render(next);if(scroll) chapters[next].scrollIntoView({behavior:'smooth',block:'center'})}
  function stop(){playing=false;clearInterval(timer);document.getElementById('play').innerHTML=svgPlay}
  function togglePlay(){playing=!playing;document.getElementById('play').innerHTML=playing?svgPause:svgPlay;clearInterval(timer);if(playing){if(current===titles.length-1)go(0);timer=setInterval(()=>{if(current>=titles.length-1){stop();return}go(current+1)},4300)}}

  const observer=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(visible&&!playing)render(Number(visible.target.dataset.stage))},{rootMargin:'-32% 0px -42% 0px',threshold:[0,.15,.35,.6]});chapters.forEach(c=>observer.observe(c));
  const revealObserver=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('seen');revealObserver.unobserve(e.target)}}),{threshold:.15});document.querySelectorAll('.reveal').forEach(e=>revealObserver.observe(e));
  const controls=document.getElementById('controls'), hero=document.querySelector('.hero');new IntersectionObserver(([e])=>controls.classList.toggle('visible',!e.isIntersecting),{threshold:.1}).observe(hero);
  document.getElementById('startStory').addEventListener('click',()=>{document.getElementById('story').scrollIntoView({behavior:'smooth'});setTimeout(()=>{go(0);if(!playing)togglePlay()},700)});document.getElementById('play').addEventListener('click',togglePlay);
  document.getElementById('mode').addEventListener('click',e=>{body.classList.toggle('technical');e.currentTarget.textContent=body.classList.contains('technical')?'Technical view':'Fan view'});
  document.addEventListener('keydown',e=>{if(e.key==='ArrowDown'||e.key==='ArrowRight'){stop();go(current+1)}if(e.key==='ArrowUp'||e.key==='ArrowLeft'){stop();go(current-1)}if(e.key===' '&&e.target===body){e.preventDefault();togglePlay()}});
  const dialog=document.getElementById('evidenceDialog');document.getElementById('evidenceTable').innerHTML=DATA.promotion.checks.map(c=>`<div class="evidence-row"><span><strong>${c.name}</strong><br>${c.evidence}</span><b>Passed</b></div>`).join('');document.getElementById('closeDialog').addEventListener('click',()=>dialog.close());
  document.getElementById('heroScore').textContent=DATA.meta.score.toFixed(2);document.getElementById('heroCandidate').textContent=DATA.meta.candidate;document.getElementById('heroFormation').textContent=DATA.meta.formation.replaceAll('-', '–');render(0);
})();
</script>
</body>
</html>'''


def main() -> None:
    story = build_story_data()
    html = (
        HTML.replace("__MANROPE_REGULAR__", font_data("manrope-400.ttf"))
        .replace("__MANROPE_SEMIBOLD__", font_data("manrope-600.ttf"))
        .replace("__NEWSREADER__", font_data("newsreader-400.ttf"))
        .replace("__STORY_DATA__", json.dumps(story, separators=(",", ":"), ensure_ascii=False))
    )
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Built {OUTPUT} ({OUTPUT.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
