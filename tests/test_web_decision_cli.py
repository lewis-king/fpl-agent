from __future__ import annotations

import argparse
import io
import json
from datetime import UTC, datetime

import httpx
import pytest

from fplagent_web import decision_cli as cli
from fplagent_web.models import DeadlineScheduleView, WorkspaceRefreshView, WorkspaceView
from fplagent_web.workspace import WorkspaceBuilder

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
STAMP = "2026-09-11T10:00:00+00:00"


def args(*values):
    parser = argparse.ArgumentParser()
    cli.configure_parser(parser)
    return parser.parse_args(values)


@pytest.fixture
def views():
    starters = [1, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14]
    bench = [15, 5, 6, 11]  # reserve GK first in API order, not outfield priority #1
    players = {}
    for player_id in range(1, 16):
        position = (
            "GK"
            if player_id in {1, 15}
            else "DEF"
            if player_id <= 6
            else "MID"
            if player_id <= 11
            else "FWD"
        )
        fixture = {
            "opponent": "ARS",
            "venue": "H",
            "difficulty": 3,
            "kickoff_time": "2099-09-13T15:00:00Z",
            "label": "ARS (H)",
        }
        players[player_id] = {
            "player_id": player_id,
            "name": "Bruno Fernandes" if player_id == 7 else f"Player {player_id}",
            "position": position,
            "team": "Test club",
            "team_short_name": "TST",
            "price": 6.0,
            "expected_points": 4.25,
            "robust_points": 4.0,
            "expected_minutes": 80,
            "play_probability": 0.95,
            "fixture": fixture,
            "fixtures": [fixture],
            "role": "starter" if player_id in starters else "bench",
            "order": (starters if player_id in starters else bench).index(player_id) + 1,
            "captain": player_id == 7,
            "vice_captain": player_id == 8,
            "availability_status": "a",
            "news": "",
            "participation": {
                "evidence_status": "clear",
                "confidence": "high",
                "headline": "Clear",
                "detail": "No flags",
                "states": {
                    "dnp": 0.05,
                    "minutes_1_59": 0.05,
                    "minutes_60_89": 0.8,
                    "minutes_90_plus": 0.1,
                },
            },
        }
    selected = {
        "action_id": "move-1",
        "route_type": "one_free_transfer",
        "label": "Improve the forward slot",
        "transfer_count": 1,
        "transfers": [
            {
                "outgoing_player_id": 99,
                "outgoing_name": "Old forward",
                "incoming_player_id": 12,
                "incoming_name": "Player 12",
                "incoming_price": 6,
            }
        ],
        "formation": "3-4-3",
        "captain_player_id": 7,
        "captain_name": "Bruno Fernandes",
        "vice_captain_player_id": 8,
        "vice_captain_name": "Player 8",
        "starter_player_ids": starters,
        "bench_player_ids": bench,
        "projected_points": 53.87,
        "incremental_points_cost": 0,
        "next_free_transfers": 1,
        "terminal_free_transfers": 2,
        "terminal_transfer_value": 1.2,
        "event_lineups": [
            {
                "event": event,
                "formation": "3-4-3",
                "projected_points": 53.87,
                "starter_player_ids": starters,
                "bench_player_ids": bench,
                "captain_player_id": 7,
                "vice_captain_player_id": 8,
            }
            for event in range(4, 9)
        ],
    }
    recommended = {
        "event": 4,
        "source": "weekly_decision",
        "action_id": "move-1",
        "formation": "3-4-3",
        "expected_points": 53.87,
        "starters": [players[p] for p in starters],
        "bench": [players[p] for p in bench],
    }
    current = {k: v for k, v in recommended.items() if k not in {"event", "action_id", "source"}}
    current.update(
        source="connected",
        confirmed=True,
        requires_confirmation=False,
        budget_spent=98.5,
        bank=1.5,
        candidate_id="current-15",
        source_label="Synced FPL",
    )
    captain = {
        "captain_player_id": 7,
        "captain_name": "Bruno Fernandes",
        "vice_captain_player_id": 8,
        "vice_captain_name": "Player 8",
        "current_captain_player_id": 7,
        "current_captain_name": "Bruno Fernandes",
        "current_vice_captain_player_id": 8,
        "current_vice_captain_name": "Player 8",
        "recommendation_aligned": True,
        "lineup_recommendation_aligned": True,
        "recommended_formation": "3-4-3",
        "evidence_status": "ready",
        "score_metric": "robust",
        "score_edge": 1,
        "receipt_id": "captain-1",
        "main_risk": "Variance",
    }
    workspace = WorkspaceView.model_validate(
        {
            "generated_at": STAMP,
            "user": {
                "user_id": "local",
                "display_name": "Test",
                "manager_id": 1,
                "connection_state": "connected",
            },
            "phase": {
                "phase": "pre_deadline",
                "season": "2026-27",
                "event": 4,
                "label": "GW4",
                "title": "Decision",
                "narrative": "Choose",
                "deadline": "2099-09-12T12:30:00Z",
                "deadline_label": "Upcoming",
                "decision_event": 4,
                "primary_action": "manage_team",
                "decision_modules": ["transfers", "chips"],
            },
            "freshness": {
                "status": "fresh",
                "observed_at": STAMP,
                "model_generated_at": STAMP,
                "squad_synced_at": STAMP,
                "age_seconds": 0,
                "refresh_required": False,
                "message": "Fresh",
            },
            "participation": {"status": "current", "headline": "Clear", "detail": "Checked"},
            "squad": current,
            "critique": {
                "status": "strong",
                "headline": "Good",
                "summary": "Sound",
                "benchmark_expected_points": 50,
                "expected_points_delta": 3.87,
                "strengths": [],
                "concerns": [],
                "suggested_questions": [],
            },
            "decision": {
                "status": "confirmed",
                "captain": captain,
                "recommended_squad": recommended,
                "comparison": {
                    "status": "adopt_recommendation",
                    "authoritative_squad": "weekly",
                    "incumbent_candidate_id": "current-15",
                    "current_expected_points": 50,
                    "headline": "Make a move",
                    "detail": "Passed",
                },
                "horizon": [],
                "evidence": [],
                "recommendation": "Move",
                "caveat": "Uncertain",
                "weekly": {
                    "status": "ready",
                    "event": 4,
                    "created_at": STAMP,
                    "selected": selected,
                    "promotion_status": "promoted",
                    "explanation": "Passed paired gates.",
                    "expected_gain_vs_roll": 2.19,
                    "worst_scenario_gain": 0.94,
                    "confidence_scenario": "residual",
                    "confidence_low": 1.0,
                    "confidence_high": 3.0,
                    "beat_roll_probability": 0.62,
                    "receipt_path": "data/decisions/test.json",
                    "receipt_sha256": "abc123",
                    "chip_advice": {
                        "recommendation": "no_chip",
                        "headline": "Save chips",
                        "detail": "Better future opportunities",
                        "half_expiry_event": 19,
                        "candidate_statuses": [{"chip": "wildcard", "status": "research_only"}],
                        "next_opportunities": [
                            {"event": 7, "chip": "bench_boost", "projected_uplift": 13.24}
                        ],
                    },
                },
            },
            "capabilities": {},
        }
    )
    refresh = WorkspaceRefreshView(
        status="published",
        event=4,
        run_id="run-1",
        receipt_path="data/manifests/fpl-weekly-deadline-pipeline.json",
        receipt_sha256="pipeline-manifest-hash",
        completed_at=STAMP,
        published=True,
        message="Published",
    )
    schedule = DeadlineScheduleView(
        status="covered",
        checked_at=STAMP,
        event=4,
        last_validated_at=STAMP,
        message="Covered",
        cadence_label="2-hour cadence",
    )
    return workspace, refresh, schedule


def test_readable_report_preserves_plan_points_and_bench_priority(views):
    report, problems = cli.render_report(*views, now=NOW)
    assert problems == []
    assert "SELL Old forward -> BUY Player 12 (£6.0m)" in report
    assert "CAPTAIN: Bruno Fernandes (C) | VICE: Player 8 (VC)" in report
    assert "Projection: 53.87 GW4 points" in report  # NOT 12 * player raw xP
    assert "CHIP: No chip" in report
    assert "1. DEF Player 5" in report and "3. MID Player 11" in report
    assert "Reserve GK Player 15" in report and "1. GK" not in report
    assert "GW4-8 weighted gain vs rolling: +2.19" in report
    assert "Wildcard: research only" in report
    assert "not a 95% interval for your actual score" in " ".join(report.split())
    assert "11 Sep 2026, 11:00 BST" in report
    assert max(map(len, report.splitlines())) <= 96


def test_long_names_narrow_terminal_double_blank_and_control_safety(views):
    workspace, _, _ = views
    player = workspace.decision.recommended_squad.starters[0]
    player.name = "Édouard A Very Long Player Name\x1b\r\n"
    player.fixtures.append(player.fixture.model_copy(update={"label": "CHE (A)"}))
    workspace.decision.recommended_squad.bench[0].fixture = None
    workspace.decision.recommended_squad.bench[0].fixtures = []
    report, problems = cli.render_report(*views, width=55, now=NOW)
    assert not problems
    assert "Édouard A Very Long Player Name" in report
    assert "ARS (H), CHE (A)" in report and "No fixture listed" in report
    assert "\x1b" not in report and "\r" not in report
    assert max(map(len, report.splitlines())) <= 55


def test_positive_unvalidated_chip_is_not_presented_as_proven_retention(views):
    workspace, _, _ = views
    workspace.decision.weekly.chip_advice.needs_review = True
    workspace.decision.weekly.chip_advice.detail = "Wildcard comparison needs review."
    report, _ = cli.render_report(*views, now=NOW)
    assert "CHIP: UNRESOLVED" in report
    assert "REVIEW BEFORE EXECUTION" in report
    assert "CHIP: No chip - retain" not in report


@pytest.mark.parametrize(
    "condition",
    [
        "running",
        "failed",
        "stale",
        "missing_weekly",
        "wrong_event",
        "wrong_action",
        "wrong_bench",
        "wrong_captain",
        "missing_player",
        "chip_mismatch",
        "old_api_chip",
        "missing_chip",
        "hash_mismatch",
        "expired",
        "missing_hash",
    ],
)
def test_unsafe_states_withhold_execution_instructions(views, condition):
    workspace, refresh, _ = views
    weekly = workspace.decision.weekly
    if condition in {"running", "failed"}:
        refresh.status = condition
    elif condition == "stale":
        workspace.freshness.refresh_required = True
    elif condition == "missing_weekly":
        weekly.status, weekly.selected = "blocked", None
    elif condition == "wrong_event":
        workspace.phase.decision_event = 5
    elif condition == "wrong_action":
        workspace.decision.recommended_squad.action_id = "another-route"
    elif condition == "wrong_bench":
        weekly.selected.bench_player_ids.reverse()
    elif condition == "wrong_captain":
        weekly.selected.captain_player_id = 15
    elif condition == "missing_player":
        workspace.decision.recommended_squad.starters.pop()
    elif condition in {"chip_mismatch", "old_api_chip"}:
        weekly.chip_advice.recommendation = "bench_boost"
        weekly.chip_advice.recommended_action_id = "chip-1"
        weekly.chip_advice.parent_action_id = (
            "different-route" if condition == "chip_mismatch" else None
        )
    elif condition == "missing_chip":
        weekly.chip_advice = None
    elif condition == "hash_mismatch":
        refresh.receipt_path = weekly.receipt_path
        refresh.receipt_sha256 = "other-generation"
    elif condition == "missing_hash":
        weekly.receipt_sha256 = None
    elif condition == "expired":
        workspace.phase.deadline = "2026-09-11T11:59:00Z"
    report, problems = cli.render_report(*views, now=NOW)
    assert problems
    assert "NEEDS REVIEW" in report
    assert (
        "STARTING XI" not in report and "SELL Old forward" not in report and "CHIP:" not in report
    )


def test_roll_and_live_event_target_and_consistent_chip(views):
    workspace, _, _ = views
    workspace.phase.phase = "live_gameweek"
    workspace.phase.event = 3  # decision_event remains 4
    weekly = workspace.decision.weekly
    weekly.selected.transfers = []
    weekly.selected.route_type = "roll"
    weekly.selected.transfer_count = 0
    weekly.chip_advice.recommendation = "triple_captain"
    weekly.chip_advice.recommended_action_id = "chip-1"
    weekly.chip_advice.parent_action_id = "move-1"
    report, problems = cli.render_report(*views, now=NOW)
    assert not problems
    assert "GW4 DECISION" in report and "No transfers" in report
    assert "CHIP: Triple Captain" in report
    assert "Base projection before extra chip points" in report


def test_api_chip_metadata_only_comes_from_exact_promoted_candidate():
    advice = WorkspaceBuilder._chip_advice_view(
        {
            "operational_recommendation": "bench_boost",
            "recommended_action_id": "chip-b",
            "candidates": [
                {"chip": "bench_boost", "action_id": "chip-a", "parent_action_id": "move-a"},
                {"chip": "bench_boost", "action_id": "chip-b", "parent_action_id": "move-b"},
            ],
        },
        {},
        {},
    )
    assert advice.parent_action_id == "move-b"
    assert advice.recommended_action_id == "chip-b"


def api_client(views, *, statuses=None, sync_ready=True, auth="connected", auth_statuses=None):
    workspace, refresh, schedule = views
    calls = []
    queue = list(statuses or ["published"])
    auth_queue = list(auth_statuses or [auth])

    def handler(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == cli.REFRESH:
            status = queue.pop(0) if len(queue) > 1 else queue[0]
            body = refresh.model_copy(update={"status": status}).model_dump(mode="json")
        elif path.endswith("/sync"):
            body = {
                "status": "synced",
                "manager_state_status": "ready" if sync_ready else "blocked",
            }
        elif path.endswith("/integrations/fpl"):
            body = {"status": auth_queue.pop(0) if len(auth_queue) > 1 else auth_queue[0]}
        elif path.endswith("/schedule"):
            body = schedule.model_dump(mode="json")
        elif path.endswith("/workspace"):
            body = workspace.model_dump(mode="json")
        else:
            pytest.fail(f"Unexpected endpoint: {path}")
        return httpx.Response(200, json=body)

    return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)), calls


def test_default_and_wait_are_read_only(views):
    for arguments in [args(), args("--wait")]:
        client, calls = api_client(
            views, statuses=["running", "published", "published"] if arguments.wait else ["running"]
        )
        with client:
            cli.collect_report(arguments, client, progress=io.StringIO(), sleep=lambda _: None)
        assert all(method == "GET" for method, _ in calls)


def test_refresh_connects_syncs_starts_once_waits_then_reads(views):
    client, calls = api_client(
        views,
        statuses=["published", "running", "running", "published"],
        auth_statuses=["not_authenticated", "connected"],
    )
    progress = io.StringIO()
    with client:
        result = cli.collect_report(
            args("--refresh"), client, progress=progress, sleep=lambda _: None
        )
    assert result[1].status == "published"
    assert [call for call in calls if call[0] == "POST"] == [
        ("POST", "/api/v1/integrations/fpl/sync"),
        ("POST", cli.REFRESH),
    ]
    assert calls.index(("GET", "/api/v1/integrations/fpl")) < calls.index(("POST", cli.REFRESH))
    assert "stages" in progress.getvalue()


def test_refresh_joins_existing_job_without_mutating_inputs(views):
    client, calls = api_client(views, statuses=["running", "published"])
    with client:
        cli.collect_report(args("--refresh"), client, progress=io.StringIO(), sleep=lambda _: None)
    assert all(method == "GET" for method, _ in calls)
    assert not any("integrations" in path for _, path in calls)


def test_failed_sync_never_requests_a_refresh(views):
    client, calls = api_client(views, sync_ready=False)
    with client, pytest.raises(cli.DecisionCliError, match="sync is not ready"):
        cli.collect_report(args("--refresh"), client, progress=io.StringIO())
    assert ("POST", cli.REFRESH) not in calls


def test_offline_auth_is_not_bypassed(views):
    client, calls = api_client(views, auth="offline")
    with client, pytest.raises(cli.DecisionCliError, match="not connected"):
        cli.collect_report(args("--refresh"), client, progress=io.StringIO())
    assert all(method == "GET" for method, _ in calls)


def test_wait_timeout_does_not_cancel_job(views):
    client, calls = api_client(views, statuses=["running"])
    clock = iter([0, 10])
    with client, pytest.raises(cli.DecisionCliError, match="job continues"):
        cli.collect_report(
            args("--wait", "--timeout", "1"),
            client,
            progress=io.StringIO(),
            monotonic=lambda: next(clock),
        )
    assert all(method == "GET" for method, _ in calls)


def test_slow_progress_poll_retries_read_only_and_recovers(views, monkeypatch):
    client, calls = api_client(views, statuses=["running", "published"])
    original_fetch = cli.fetch
    status_reads = 0

    def slow_once(client, method, path, **kwargs):
        nonlocal status_reads
        if path == cli.REFRESH:
            status_reads += 1
            if status_reads == 2:
                raise cli.DecisionCliTimeout("timed out")
        return original_fetch(client, method, path, **kwargs)

    monkeypatch.setattr(cli, "fetch", slow_once)
    progress = io.StringIO()
    with client:
        _, refresh, _ = cli.collect_report(
            args("--wait"), client, progress=progress, sleep=lambda _: None
        )
    assert refresh.status == "published"
    assert "Retrying status only" in progress.getvalue()
    assert all(method == "GET" for method, _ in calls)


def test_repeated_progress_timeouts_respect_total_wait_limit(views, monkeypatch):
    client, calls = api_client(views, statuses=["running"])
    original_fetch = cli.fetch
    clock = [0.0]

    def timeout_after_initial(client, method, path, **kwargs):
        if calls:
            raise cli.DecisionCliTimeout("timed out")
        return original_fetch(client, method, path, **kwargs)

    monkeypatch.setattr(cli, "fetch", timeout_after_initial)
    with client, pytest.raises(cli.DecisionCliError, match="job continues"):
        cli.collect_report(
            args("--wait", "--timeout", "3", "--poll-interval", "1"), client,
            progress=io.StringIO(), monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        )
    assert clock[0] == 3
    assert calls == [("GET", cli.REFRESH)]


def test_sync_timeout_is_not_retried_or_followed_by_refresh(views, monkeypatch):
    client, calls = api_client(views)
    original_fetch = cli.fetch
    posts = []

    def timeout_post(client, method, path, **kwargs):
        if method == "POST":
            posts.append(path)
            raise cli.DecisionCliTimeout("timed out")
        return original_fetch(client, method, path, **kwargs)

    monkeypatch.setattr(cli, "fetch", timeout_post)
    with client, pytest.raises(cli.DecisionCliTimeout):
        cli.collect_report(args("--refresh"), client, progress=io.StringIO())
    assert posts == ["/api/v1/integrations/fpl/sync"]
    assert ("POST", cli.REFRESH) not in calls


def test_request_timeout_is_redacted_and_distinguished():
    def timeout(request):
        raise httpx.ReadTimeout("do not expose request secrets", request=request)

    with (
        httpx.Client(base_url="http://test", transport=httpx.MockTransport(timeout)) as client,
        pytest.raises(cli.DecisionCliTimeout) as error,
    ):
        cli.fetch(client, "GET", cli.REFRESH)
    assert "secrets" not in str(error.value)
    assert "not cancelled" in str(error.value)


def test_read_race_never_presents_a_mixed_generation(views):
    client, _ = api_client(views, statuses=["running", "published"])
    with client, pytest.raises(cli.DecisionCliError, match="generation changed"):
        cli.collect_report(args(), client, progress=io.StringIO())


def test_json_stdout_clean_and_blocked_exit_code(views, monkeypatch, capsys):
    client, _ = api_client(views)
    monkeypatch.setattr(cli.httpx, "Client", lambda **_: client)
    assert cli.run(args("--json")) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "ready"
    assert not output.err
    views[0].freshness.refresh_required = True
    # Restore constructor before creating the next mock client.
    monkeypatch.undo()
    client, _ = api_client(views)
    monkeypatch.setattr(cli.httpx, "Client", lambda **_: client)
    assert cli.run(args()) == 2
    assert "NEEDS REVIEW" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_wait_options(value):
    with pytest.raises(SystemExit):
        args("--timeout", value)


def test_http_failures_hide_response_body():
    with (
        httpx.Client(
            base_url="http://test",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(500, text="do not print an upstream secret")
            ),
        ) as client,
        pytest.raises(cli.DecisionCliError) as error,
    ):
        cli.fetch(client, "GET", cli.REFRESH)
    assert "HTTP 500" in str(error.value) and "secret" not in str(error.value)


def test_paid_hit_is_explicit_and_does_not_change_saved_projection(views):
    selected = views[0].decision.weekly.selected
    selected.incremental_points_cost = 4
    selected.route_type = "paid_transfer"
    report, problems = cli.render_report(*views, now=NOW)
    assert not problems
    assert "Transfer hit: 4 points" in report
    assert "Projection: 53.87 GW4 points" in report


def test_pipeline_manifest_hash_is_not_compared_with_decision_hash(views):
    workspace, refresh, _ = views
    assert refresh.receipt_path != workspace.decision.weekly.receipt_path
    assert refresh.receipt_sha256 != workspace.decision.weekly.receipt_sha256
    report, problems = cli.render_report(*views, now=NOW)
    assert not problems
    assert "PUBLISHED RECOMMENDATION" in report


def test_refresh_json_keeps_progress_on_stderr(views, monkeypatch, capsys):
    client, calls = api_client(views)
    monkeypatch.setattr(cli.httpx, "Client", lambda **_: client)
    assert cli.run(args("--refresh", "--json")) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "ready"
    assert "Connecting" in output.err and "Syncing" in output.err
    assert len([call for call in calls if call[0] == "POST"]) == 2


def test_offline_api_gives_an_actionable_error_and_nonzero_exit(monkeypatch, capsys):
    def offline(request):
        raise httpx.ConnectError("connection failed", request=request)

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(offline))
    monkeypatch.setattr(cli.httpx, "Client", lambda **_: client)
    assert cli.run(args()) == 1
    output = capsys.readouterr()
    assert "fplagent-web" in output.err and not output.out


def test_dropped_progress_poll_retries_read_only_and_recovers(views, monkeypatch):
    # A refresh that holds the API can refuse a status read outright. That
    # ended the watcher twice during GW10 while the job itself carried on.
    client, calls = api_client(views, statuses=["running", "published"])
    original_fetch = cli.fetch
    status_reads = 0

    def dropped_once(client, method, path, **kwargs):
        nonlocal status_reads
        if path == cli.REFRESH:
            status_reads += 1
            if status_reads == 2:
                raise cli.DecisionCliUnreachable("no answer")
        return original_fetch(client, method, path, **kwargs)

    monkeypatch.setattr(cli, "fetch", dropped_once)
    progress = io.StringIO()
    with client:
        _, refresh, _ = cli.collect_report(
            args("--wait"), client, progress=progress, sleep=lambda _: None
        )
    assert refresh.status == "published"
    assert "Retrying status only" in progress.getvalue()
    assert all(method == "GET" for method, _ in calls)
