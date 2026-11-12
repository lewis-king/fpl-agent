"""Terminal view over the same API/validated workspace as the browser.

No optimizer, receipt mutation, credential loading or FPL writes live here.
Only --refresh requests authentication, private sync and the API-owned worker.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import textwrap
import time
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from typing import Any, TextIO
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from .models import DeadlineScheduleView, WorkspaceRefreshView, WorkspaceView

REFRESH = "/api/v1/workspace/refresh"
CHIPS = {
    "no_chip": "No chip - retain your chips",
    "bench_boost": "Bench Boost",
    "triple_captain": "Triple Captain",
    "wildcard": "Wildcard",
    "free_hit": "Free Hit",
    "schedule_watch": "Fixture watch",
}


class DecisionCliError(Exception):
    pass


class DecisionCliTimeout(DecisionCliError):
    """An individual API request timed out; the server-owned job may continue."""


class DecisionCliUnreachable(DecisionCliError):
    """The API did not answer at all; a busy refresh can cause this briefly."""


def positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.description = "Read the saved weekly recommendation; optionally refresh and wait."
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="Sync FPL, refresh via API, then wait")
    mode.add_argument(
        "--wait", action="store_true", help="Wait for an existing refresh; do not start one"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--json", action="store_true", help="Emit a single JSON report instead of text"
    )
    parser.add_argument(
        "--timeout", type=positive_seconds, default=1800, help="Wait limit in seconds (1800)"
    )
    parser.add_argument(
        "--poll-interval", type=positive_seconds, default=3, help="Poll interval in seconds (3)"
    )
    parser.add_argument("--width", type=int, default=None, help="Text width (minimum 50 columns)")


def clean(value: Any) -> str:
    # Source names/news must not be able to inject terminal controls or new rows.
    return " ".join(
        "".join(c for c in str(value) if not unicodedata.category(c).startswith("C")).split()
    )


def date_label(value: str | None) -> str:
    if not value:
        return "not recorded"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return clean(value) + " (timezone unknown)"
        return dt.astimezone(ZoneInfo("Europe/London")).strftime("%d %b %Y, %H:%M %Z")
    except ValueError:
        return clean(value)


def readiness(
    workspace: WorkspaceView,
    refresh: WorkspaceRefreshView,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Fail closed: do not turn a fallback XI or another chip route into instructions."""
    problems = []
    weekly = workspace.decision.weekly
    squad = workspace.decision.recommended_squad
    event = workspace.phase.decision_event or workspace.phase.event
    selected = weekly.selected
    if refresh.status == "running":
        problems.append("A refresh is still running; this is not its completed recommendation.")
    elif refresh.status in {"failed", "blocked", "not_ready"}:
        problems.append(f"Latest refresh {refresh.status}: {refresh.message}")
    if weekly.status != "ready" or selected is None:
        problems.append(weekly.explanation or "No validated weekly recommendation is available.")
    if workspace.freshness.refresh_required or workspace.freshness.status == "stale":
        problems.append(workspace.freshness.message)
    if event != weekly.event or squad.event != event:
        problems.append("The saved recommendation is not for the actionable Gameweek.")
    deadline = workspace.phase.decision_deadline or workspace.phase.deadline
    try:
        dt = datetime.fromisoformat(deadline)
        if dt.tzinfo is None or dt <= (now or datetime.now(UTC)):
            problems.append("The recommendation deadline has passed or has no timezone.")
    except ValueError:
        problems.append("The recommendation deadline cannot be verified.")
    if selected is not None:
        if squad.source != "weekly_decision" or squad.action_id != selected.action_id:
            problems.append("Transfer and lineup action IDs differ; instructions are withheld.")
        starters = squad.starters
        bench = squad.bench
        ids = [p.player_id for p in starters + bench]
        positions = Counter(p.position for p in starters)
        legal_xi = (
            positions["GK"] == 1
            and 3 <= positions["DEF"] <= 5
            and 2 <= positions["MID"] <= 5
            and 1 <= positions["FWD"] <= 3
        )
        legal_squad = Counter(p.position for p in starters + bench) == {
            "GK": 2,
            "DEF": 5,
            "MID": 5,
            "FWD": 3,
        }
        if (
            len(starters) != 11
            or len(bench) != 4
            or len(set(ids)) != 15
            or not legal_xi
            or not legal_squad
        ):
            problems.append("The recommended 15 or starting formation is incomplete/illegal.")
        if {p.player_id for p in starters} != set(selected.starter_player_ids) or [
            p.player_id for p in bench
        ] != selected.bench_player_ids:
            problems.append("The displayed XI/bench does not match the selected action.")
        starter_ids = {p.player_id for p in starters}
        if (
            selected.captain_player_id not in starter_ids
            or selected.vice_captain_player_id not in starter_ids
            or selected.captain_player_id == selected.vice_captain_player_id
            or {p.player_id for p in starters if p.captain} != {selected.captain_player_id}
            or {p.player_id for p in starters if p.vice_captain}
            != {selected.vice_captain_player_id}
        ):
            problems.append("Captain/vice-captain does not match the selected starting XI.")
        chip = weekly.chip_advice
        if chip is None:
            problems.append("Chip advice is missing; do not assume no chip was selected.")
        elif chip.recommendation in {"wildcard", "free_hit"} and (
            not chip.recommended_action_id
            or selected.action_id != chip.recommended_action_id
        ):
            problems.append(
                "The squad-chip rebuild and the displayed squad cannot be matched. Do not "
                "combine these instructions."
            )
        elif chip.recommendation in {"bench_boost", "triple_captain"} and (
            not chip.recommended_action_id or chip.parent_action_id != selected.action_id
            or (selected.configuration_action_id is not None
                and selected.configuration_action_id != chip.recommended_action_id)
        ):
            problems.append(
                "Chip and transfer route cannot be matched. Do not combine these instructions; "
                "the chip-parent display issue needs review (restart an older API if metadata is missing)."
            )
        # The refresh normally hashes the pipeline manifest, whereas the workspace
        # hashes the published decision. Those are different artifacts by design.
        # WorkspaceBuilder validates their lineage; only compare hashes directly
        # when both responses explicitly identify the same artifact.
        if (
            refresh.status in {"published", "reused"}
            and refresh.event == event
            and refresh.receipt_path is not None
            and refresh.receipt_path == weekly.receipt_path
            and refresh.receipt_sha256
            and refresh.receipt_sha256 != weekly.receipt_sha256
        ):
            problems.append(
                "Refresh and workspace receipt hashes differ; read again after publication."
            )
        if not weekly.receipt_sha256:
            problems.append("No validated receipt hash is recorded for this recommendation.")
    return list(dict.fromkeys(problems))


def render_report(
    workspace: WorkspaceView,
    refresh: WorkspaceRefreshView,
    schedule: DeadlineScheduleView,
    *,
    width: int = 96,
    now: datetime | None = None,
) -> tuple[str, list[str]]:
    width = max(50, min(width, 120))
    lines: list[str] = []

    def write(value: Any = "", indent: str = "") -> None:
        lines.extend(
            textwrap.wrap(clean(value), width, initial_indent=indent, subsequent_indent=indent)
            or [""]
        )

    def section(title: str) -> None:
        write()
        write(title)
        lines.append("-" * width)

    weekly = workspace.decision.weekly
    event = workspace.phase.decision_event or workspace.phase.event
    problems = readiness(workspace, refresh, now=now)
    write(f"FPLAGENT | GW{event} DECISION | {workspace.phase.season}")
    lines.append("=" * width)
    conditional_chip = bool(weekly.chip_advice and (
        weekly.chip_advice.needs_review or (
            weekly.chip_advice.recommendation == "no_chip" and any(
                c.status in {"research_only", "needs_review"} and (c.joint_net_value or 0) > 0
                for c in weekly.chip_advice.candidate_statuses
            )
        )
    ))
    write(
        "NEEDS REVIEW - not an execution plan" if problems
        else "CONDITIONAL PLAN - chip decision needs review" if conditional_chip
        else "PUBLISHED RECOMMENDATION"
    )
    write(f"Deadline: {date_label(workspace.phase.decision_deadline or workspace.phase.deadline)}")
    write(f"Decision created: {date_label(weekly.created_at)}")
    write(
        f"Last validated: {date_label(schedule.last_validated_at) if schedule.event == event else 'not recorded for this event'}"
    )
    write(f"Evidence observed: {date_label(workspace.freshness.observed_at)}")
    write(f"FPL squad synced: {date_label(workspace.freshness.squad_synced_at)}")
    write(
        f"Latest refresh: {refresh.status} | {date_label(refresh.completed_at or refresh.started_at)}"
    )
    if refresh.status == "running":
        write(
            f"Progress: {refresh.completed_stage_count}/{refresh.total_stages or '?'} stages | {refresh.message}"
        )
    if problems:
        section("WHY INSTRUCTIONS ARE WITHHELD")
        for problem in problems:
            write(f"! {problem}")
        write(
            "Use 'fplagent decisions --wait' for a running job, or '--refresh' to sync and request a new check."
        )
        write("The last saved workspace has not been overwritten by this command.")
        return "\n".join(lines) + "\n", problems

    selected = weekly.selected
    assert selected is not None  # checked by readiness
    squad = workspace.decision.recommended_squad
    chip = weekly.chip_advice
    assert chip is not None
    section("SAVED TRANSFER ROUTE - assumes no chip" if conditional_chip else "YOUR MOVES")
    if selected.transfers:
        for index, transfer in enumerate(selected.transfers, 1):
            write(
                f"{index}. SELL {transfer.outgoing_name} -> BUY {transfer.incoming_name} (£{transfer.incoming_price:.1f}m)"
            )
    else:
        write("No transfers - keep your 15 and set the lineup below.")
    write(
        f"Transfer hit: {selected.incremental_points_cost} points | Free transfers next GW: {selected.next_free_transfers if selected.next_free_transfers is not None else 'unknown'}"
    )
    write(f"CAPTAIN: {selected.captain_name} (C) | VICE: {selected.vice_captain_name} (VC)")
    write(f"CHIP: {'UNRESOLVED — no chip authorised' if conditional_chip else CHIPS[chip.recommendation]}")
    if conditional_chip:
        write("REVIEW BEFORE EXECUTION: A positive chip alternative has not cleared its evidence checks. Saving the chip has not been proven better; these transfers assume no chip.")
    label = (
        "Base projection before extra chip points"
        if chip.recommendation != "no_chip"
        else "Projection"
    )
    write(
        f"{label}: {squad.expected_points:.2f} GW{event} points including captaincy; transfer hit listed separately."
    )

    def player_row(player: Any, prefix: str = "") -> None:
        markers = " (C)" if player.captain else " (VC)" if player.vice_captain else ""
        fixtures = player.fixtures or ([player.fixture] if player.fixture else [])
        fixture = ", ".join(f.label for f in fixtures) or "No fixture listed"
        name = clean(f"{prefix}{player.position} {player.name}{markers}")
        detail = clean(f"{player.team_short_name} | {fixture}")
        numbers = f"xP {player.expected_points:5.2f} | min {player.expected_minutes:4.1f} | plays {player.play_probability:.0%}"
        if width >= 94 and len(name) <= 33 and len(detail) <= 22:
            lines.append(f"{name:<33} {detail:<22} {numbers}")
        else:
            write(name)
            write(f"{detail} | {numbers}", indent="  ")

    section(f"STARTING XI | {selected.formation}")
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    for player in sorted(squad.starters, key=lambda p: (order[p.position], p.order)):
        player_row(player)
    section("BENCH | outfield autosub priority")
    for index, player in enumerate((p for p in squad.bench if p.position != "GK"), 1):
        player_row(player, f"{index}. ")
    for player in squad.bench:
        if player.position == "GK":
            player_row(player, "Reserve ")
    write(
        "Player xP is undoubled raw model xP. The team total uses the saved decision scoring basis, not a new sum. Plays is appearance probability, not chance of starting. Autosubs must preserve a legal formation."
    )

    section("WHY THIS PLAN")
    write(weekly.explanation)
    events = [lineup.event for lineup in selected.event_lineups]
    horizon = f"GW{min(events)}-{max(events)}" if events else "saved horizon"
    if weekly.expected_gain_vs_roll is not None:
        write(
            f"{horizon} weighted gain vs rolling: {weekly.expected_gain_vs_roll:+.2f} points (after costs)."
        )
    if weekly.worst_scenario_gain is not None:
        write(
            f"Worst model-world mean gain: {weekly.worst_scenario_gain:+.2f} points - not a worst possible outcome."
        )
    if weekly.beat_roll_probability is not None:
        write(
            f"Simulated probability of beating roll: {weekly.beat_roll_probability:.1%} (model-dependent)."
        )
    if weekly.confidence_low is not None and weekly.confidence_high is not None:
        write(
            f"Simulation mean 95% CI ({weekly.confidence_scenario}): {weekly.confidence_low:+.2f} to {weekly.confidence_high:+.2f}. This is not a 95% interval for your actual score."
        )
    if selected.event_lineups:
        write(
            "Future projections are conditional plans, not instructions to execute future transfers:"
        )
        write(
            " | ".join(
                f"GW{row.event}: {row.projected_points:.1f}" for row in selected.event_lineups
            )
        )
    if weekly.execution_timing:
        write(
            f"Transfer timing: {weekly.execution_timing.headline}. {weekly.execution_timing.detail}"
        )

    section("CHIP STRATEGY")
    write(chip.detail)
    if chip.half_expiry_event is not None:
        write(f"Current chip-half expiry: GW{chip.half_expiry_event}.")
    for candidate in chip.candidate_statuses:
        value = (
            f" | net option value {candidate.joint_net_value:+.2f}"
            if candidate.joint_net_value is not None
            else ""
        )
        write(
            f"{CHIPS.get(candidate.chip, candidate.chip)}: {candidate.status.replace('_', ' ')}{value}"
        )
    if chip.deadline_plan:
        write(
            f"Chip plan to GW{chip.half_expiry_event} (re-planned every week; every chip is used before expiry):"
        )
        for row in chip.deadline_plan:
            when = "PLAY NOW" if row.play_now else f"planned GW{row.planned_event}"
            gain = (
                f" | about {row.expected_gain:.0f} points" if row.expected_gain is not None else ""
            )
            write(
                f"{CHIPS.get(row.chip, row.chip)}: {when}{gain} | latest safe GW{row.latest_safe_event}",
                indent="  ",
            )
    if chip.next_opportunities:
        write("Future windows to watch, not booked chip dates:")
        for opportunity in chip.next_opportunities:
            detail = opportunity.schedule_note or (
                f"estimated uplift {opportunity.projected_uplift:.2f} points"
                if opportunity.projected_uplift is not None
                else "uplift not recorded"
            )
            write(
                f"GW{opportunity.event} {CHIPS.get(opportunity.chip, opportunity.chip)}: {detail}",
                indent="  ",
            )

    warnings = [
        f"{p.name}: {p.participation.headline}"
        for p in squad.starters + squad.bench
        if p.participation.evidence_status not in {"clear"}
    ]
    if warnings or workspace.freshness.status == "attention":
        section("WATCH BEFORE THE DEADLINE")
        if workspace.freshness.status == "attention":
            write(workspace.freshness.message)
        for warning in warnings:
            write(warning)
    section("RECEIPT")
    write(f"Action: {selected.action_id} | SHA256: {weekly.receipt_sha256 or 'not recorded'}")
    write(
        f"Next scheduled check: {date_label(schedule.next_window_at)} | {schedule.cadence_label or schedule.status}"
    )
    write(
        "Same recommendation as the web workspace. No changes have been submitted to FPL. Predictions are not guarantees."
    )
    return "\n".join(lines) + "\n", problems


def fetch(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise DecisionCliError(
                "API returned a non-object response; no recommendation can be verified."
            )
        return result
    except httpx.HTTPStatusError as exc:
        raise DecisionCliError(
            f"API returned HTTP {exc.response.status_code} for {method} {path}. "
            "Inspect refresh details in the app; no fallback recommendation was invented."
        ) from None
    except httpx.TimeoutException:
        raise DecisionCliTimeout(
            "The FPLAgent API request timed out. A running refresh is not cancelled; "
            "use 'fplagent decisions --wait' to reconnect."
        ) from None
    except httpx.RequestError:
        raise DecisionCliUnreachable(
            "Cannot reach the FPLAgent API. Start '.venv/bin/fplagent-web --host 127.0.0.1 --port 8000'. "
            "If a refresh was already running, a client timeout does not cancel it."
        ) from None
    except ValueError:
        raise DecisionCliError(
            "API returned invalid JSON; check that --api-url points to FPLAgent."
        ) from None


def collect_report(
    args: argparse.Namespace,
    client: httpx.Client,
    *,
    progress: TextIO,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> tuple[WorkspaceView, WorkspaceRefreshView, DeadlineScheduleView]:
    end = monotonic() + args.timeout
    refresh = WorkspaceRefreshView.model_validate(fetch(client, "GET", REFRESH))
    if args.refresh and refresh.status != "running":
        print("Connecting through local MCP...", file=progress, flush=True)
        auth_end = min(end, monotonic() + 60)
        while True:
            auth = fetch(client, "GET", "/api/v1/integrations/fpl")
            if auth.get("status") == "connected":
                break
            if auth.get("status") not in {"not_authenticated", "ready"} or monotonic() >= auth_end:
                raise DecisionCliError(
                    "FPL is not connected. Check saved-login setup or sign in through the app, then retry."
                )
            sleep(min(args.poll_interval, max(0, auth_end - monotonic())))
        print(
            "Syncing squad, selling prices, free transfers and chips...", file=progress, flush=True
        )
        sync = fetch(client, "POST", "/api/v1/integrations/fpl/sync")
        if sync.get("status") != "synced" or sync.get("manager_state_status") != "ready":
            raise DecisionCliError(
                "Private squad sync is not ready. No decision refresh was requested; review the manager-state details in the app."
            )
        refresh = WorkspaceRefreshView.model_validate(
            fetch(client, "POST", REFRESH, json={"reason": "manual"})
        )
    elif args.refresh and refresh.status == "running":
        print(
            "Joining the existing refresh; not changing its input snapshot.",
            file=progress,
            flush=True,
        )
    last_progress = None
    if args.refresh or args.wait:
        while refresh.status == "running":
            message = f"[{refresh.completed_stage_count}/{refresh.total_stages or '?'} stages] {clean(refresh.message)}"
            if message != last_progress:
                print(message, file=progress, flush=True)
                last_progress = message
            if monotonic() >= end:
                raise DecisionCliError(
                    "Wait limit reached. The API job continues; use 'fplagent decisions --wait' to rejoin."
                )
            sleep(min(args.poll_interval, max(0, end - monotonic())))
            remaining = end - monotonic()
            if remaining <= 0:
                continue  # The next loop iteration reports the overall wait limit.
            try:
                refresh = WorkspaceRefreshView.model_validate(
                    fetch(client, "GET", REFRESH, timeout=min(60.0, remaining))
                )
            except (DecisionCliTimeout, DecisionCliUnreachable):
                # Only retry this read of an already observed running job. POST
                # timeouts are ambiguous and must never repeat sync/refresh. The
                # API can refuse or drop a status read while a simulation holds it.
                print(
                    "Progress request got no answer; the refresh may still be running. "
                    "Retrying status only within the wait limit...",
                    file=progress,
                    flush=True,
                )
    before = (refresh.run_id, refresh.status)
    workspace = WorkspaceView.model_validate(fetch(client, "GET", "/api/v1/workspace"))
    schedule = DeadlineScheduleView.model_validate(fetch(client, "GET", REFRESH + "/schedule"))
    refresh = WorkspaceRefreshView.model_validate(fetch(client, "GET", REFRESH))
    if before != (refresh.run_id, refresh.status) and refresh.status != "running":
        raise DecisionCliError(
            "The published generation changed while reading. Run 'fplagent decisions' again for a coherent view."
        )
    return workspace, refresh, schedule


def run(args: argparse.Namespace) -> int:
    try:
        with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=60, trust_env=False) as client:
            workspace, refresh, schedule = collect_report(args, client, progress=sys.stderr)
        report, problems = render_report(
            workspace,
            refresh,
            schedule,
            width=args.width or shutil.get_terminal_size((96, 24)).columns,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": "fplagent-cli-decisions-v1",
                        "status": "needs_review" if problems else "ready",
                        "issues": problems,
                        "workspace": workspace.model_dump(mode="json"),
                        "refresh": refresh.model_dump(mode="json"),
                        "schedule": schedule.model_dump(mode="json"),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(report, end="")
        return 2 if problems else 0
    except (DecisionCliError, ValidationError) as exc:
        message = (
            str(exc)
            if isinstance(exc, DecisionCliError)
            else "API schema is incompatible; update/restart the API before reading decisions."
        )
        print(f"FPLAgent: {clean(message)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "\nStopped waiting. Any API-owned refresh continues in the background.", file=sys.stderr
        )
        return 130
    except BrokenPipeError:
        return 0
