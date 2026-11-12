from __future__ import annotations

import json
from pathlib import Path

import pytest

from fplagent_data.cli import parser
from fplagent_data.event_outcomes import (
    archive_event_outcome,
    build_current_player_history,
    collect_event_outcome,
    latest_event_outcome,
    validate_event_outcome,
)
from fplagent_data.http import sha256_file
from fplagent_data.live_snapshots import SnapshotValidationError


def _bootstrap(*, finished: bool = True, checked: bool = True) -> dict:
    return {
        "elements": [{"id": 1}, {"id": 2}, {"id": 3}],
        "events": [
            {
                "id": 2,
                "deadline_time": "2026-08-28T17:30:00+00:00",
                "finished": finished,
                "data_checked": checked,
            }
        ],
    }


def _live() -> dict:
    def stats(minutes: int, points: int, xg: str, xa: str) -> dict:
        return {
            "minutes": minutes,
            "total_points": points,
            "goals_scored": 0,
            "assists": 0,
            "expected_goals": xg,
            "expected_assists": xa,
            "bps": points * 3,
            "clean_sheets": int(minutes >= 60),
            "defensive_contribution": 0,
        }

    return {
        "elements": [
            {"id": 1, "stats": stats(90, 6, "0.52", "0.11")},
            {"id": 2, "stats": stats(0, 0, "0.00", "0.00")},
            {"id": 3, "stats": stats(45, 2, "0.07", "0.31")},
        ]
    }


def test_final_event_outcome_is_immutable_and_content_locked(tmp_path: Path) -> None:
    root = tmp_path / "outcomes"
    pointers = tmp_path / "pointers"
    observed = "2026-09-01T12:00:00+00:00"
    first = archive_event_outcome(
        _live(),
        _bootstrap(),
        event=2,
        observed_at=observed,
        outcome_root=root,
        pointer_root=pointers,
    )
    repeated = archive_event_outcome(
        _live(),
        _bootstrap(),
        event=2,
        observed_at=observed,
        outcome_root=root,
        pointer_root=pointers,
    )
    snapshot_dir, manifest, live = latest_event_outcome(
        2, outcome_root=root, pointer_root=pointers
    )

    assert first == repeated == manifest
    assert live == _live()
    assert snapshot_dir.is_dir()

    changed = _live()
    changed["elements"][0]["stats"]["total_points"] = 7
    with pytest.raises(SnapshotValidationError, match="immutable event outcome collision"):
        archive_event_outcome(
            changed,
            _bootstrap(),
            event=2,
            observed_at=observed,
            outcome_root=root,
            pointer_root=pointers,
        )


def test_collect_event_outcome_stages_download_before_immutable_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    official = tmp_path / "official"
    official.mkdir()
    (official / "bootstrap-static.json").write_text(
        json.dumps(_bootstrap()), encoding="utf-8"
    )
    monkeypatch.setattr(
        "fplagent_data.event_outcomes.latest_official_snapshot",
        lambda: (official, {"observed_at": "2026-09-01T12:00:00+00:00"}),
    )
    monkeypatch.setattr(
        "fplagent_data.event_outcomes.build_current_player_history",
        lambda **_: {"status": "ready"},
    )
    download_targets: list[Path] = []

    def fetcher(_url: str, target: Path, *, force: bool) -> Path:
        assert force is True
        download_targets.append(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_live(), indent=2), encoding="utf-8")
        return target

    root = tmp_path / "outcomes"
    result = collect_event_outcome(
        2,
        observed_at="2026-09-01T12:00:00+00:00",
        outcome_root=root,
        pointer_root=tmp_path / "pointers",
        fetcher=fetcher,
    )

    immutable = root / "event-2" / "20260901T120000000000Z" / "event-live.json"
    assert result["publishable"] is True
    assert immutable.is_file()
    assert download_targets[0] != immutable


@pytest.mark.parametrize(
    ("bootstrap", "message"),
    [
        (_bootstrap(finished=False), "not finished"),
        (_bootstrap(checked=False), "not been checked"),
    ],
)
def test_provisional_event_outcome_cannot_be_published(
    tmp_path: Path, bootstrap: dict, message: str
) -> None:
    with pytest.raises(SnapshotValidationError, match=message):
        archive_event_outcome(
            _live(),
            bootstrap,
            event=2,
            observed_at="2026-09-01T12:00:00+00:00",
            outcome_root=tmp_path / "outcomes",
            pointer_root=tmp_path / "pointers",
        )


def test_event_outcome_requires_exact_bootstrap_player_set(tmp_path: Path) -> None:
    incomplete = _live()
    incomplete["elements"].pop()
    with pytest.raises(SnapshotValidationError, match="player set differs"):
        archive_event_outcome(
            incomplete,
            _bootstrap(),
            event=2,
            observed_at="2026-09-01T12:00:00+00:00",
            outcome_root=tmp_path / "outcomes",
            pointer_root=tmp_path / "pointers",
        )


def test_event_outcome_accepts_audited_post_event_bootstrap_additions() -> None:
    bootstrap = _bootstrap()
    bootstrap["elements"].append(
        {
            "id": 4,
            "web_name": "Deadline signing",
            "team_join_date": "2026-08-28",
        }
    )

    result = validate_event_outcome(bootstrap, _live(), event=2)

    assert result["publishable"] is True
    assert result["post_event_bootstrap_additions"] == [
        {
            "element": 4,
            "player_name": "Deadline signing",
            "team_join_date": "2026-08-28",
        }
    ]


@pytest.mark.parametrize(
    "added_player",
    [
        {"id": 2, "web_name": "Non-tail omission", "team_join_date": "2026-08-28"},
        {"id": 4, "web_name": "Old signing", "team_join_date": "2026-08-27"},
        {"id": 4, "web_name": "Unknown signing"},
    ],
)
def test_event_outcome_rejects_unproven_bootstrap_supersets(
    added_player: dict,
) -> None:
    bootstrap = _bootstrap()
    if added_player["id"] == 2:
        bootstrap["elements"] = [
            row for row in bootstrap["elements"] if row["id"] != 2
        ]
        bootstrap["elements"].append(added_player)
        live = _live()
        live["elements"] = [row for row in live["elements"] if row["id"] != 2]
    else:
        bootstrap["elements"].append(added_player)
        live = _live()

    result = validate_event_outcome(bootstrap, live, event=2)

    assert result["publishable"] is False
    assert "player set differs" in result["issues"][0]


def test_event_outcome_requires_live_prediction_features(tmp_path: Path) -> None:
    incomplete = _live()
    del incomplete["elements"][0]["stats"]["expected_goals"]
    with pytest.raises(SnapshotValidationError, match="expected_goals"):
        archive_event_outcome(
            incomplete,
            _bootstrap(),
            event=2,
            observed_at="2026-09-01T12:00:00+00:00",
            outcome_root=tmp_path / "outcomes",
            pointer_root=tmp_path / "pointers",
        )


def test_final_events_normalize_to_current_player_history(tmp_path: Path) -> None:
    root = tmp_path / "outcomes"
    pointers = tmp_path / "pointers"
    snapshot = tmp_path / "official" / "bootstrap-static.json"
    fixtures = snapshot.with_name("fixtures.json")
    snapshot.parent.mkdir(parents=True)
    bootstrap = _bootstrap()
    bootstrap["elements"] = [
        {
            "id": 1,
            "code": 101,
            "team": 1,
            "element_type": 3,
            "web_name": "Active",
        },
        {
            "id": 2,
            "code": 102,
            "team": 2,
            "element_type": 2,
            "web_name": "Opponent",
        },
        {
            "id": 3,
            "code": 103,
            "team": 3,
            "element_type": 4,
            "web_name": "Blank",
        },
    ]
    snapshot.write_text(json.dumps(bootstrap), encoding="utf-8")
    fixtures.write_text(
        json.dumps(
            [
                {
                    "event": 2,
                    "kickoff_time": "2026-08-29T14:00:00+00:00",
                    "team_h": 1,
                    "team_a": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    archive_event_outcome(
        _live(),
        bootstrap,
        event=2,
        observed_at="2026-09-01T12:00:00+00:00",
        outcome_root=root,
        pointer_root=pointers,
        bootstrap_path=snapshot,
    )
    # Event 2 alone is deliberately rejected: the current-season history must
    # be contiguous so missing GW1 data cannot masquerade as a full rolling prior.
    with pytest.raises(SnapshotValidationError, match="not contiguous"):
        build_current_player_history(
            outcome_root=root,
            pointer_root=pointers,
            output_path=tmp_path / "player-events.parquet",
            receipt_path=tmp_path / "receipt.json",
        )

    # Re-label the same self-contained example as GW1 for a successful contract.
    bootstrap["events"][0]["id"] = 1
    bootstrap["events"][0]["deadline_time"] = "2026-08-21T17:30:00+00:00"
    snapshot.write_text(json.dumps(bootstrap), encoding="utf-8")
    fixture_rows = json.loads(fixtures.read_text(encoding="utf-8"))
    fixture_rows[0]["event"] = 1
    fixtures.write_text(json.dumps(fixture_rows), encoding="utf-8")
    archive_event_outcome(
        _live(),
        bootstrap,
        event=1,
        observed_at="2026-08-25T12:00:00+00:00",
        outcome_root=root,
        pointer_root=pointers,
        bootstrap_path=snapshot,
    )
    # Remove the deliberately non-contiguous pointer so only GW1 is normalized.
    (pointers / "event-2.json").unlink()
    output = tmp_path / "player-events.parquet"
    receipt_path = tmp_path / "receipt.json"
    receipt = build_current_player_history(
        outcome_root=root,
        pointer_root=pointers,
        output_path=output,
        receipt_path=receipt_path,
    )
    import pyarrow.parquet as pq

    rows = pq.read_table(output).to_pylist()
    assert receipt["events"] == [1]
    assert receipt["rows"] == 2  # The team-three player had a blank, not a DNP.
    assert rows[0]["xg"] == pytest.approx(0.52)
    assert rows[0]["xa"] == pytest.approx(0.11)
    assert receipt["output_sha256"] == sha256_file(output)


def test_corrupted_event_outcome_is_rejected_on_read(tmp_path: Path) -> None:
    root = tmp_path / "outcomes"
    pointers = tmp_path / "pointers"
    archive_event_outcome(
        _live(),
        _bootstrap(),
        event=2,
        observed_at="2026-09-01T12:00:00+00:00",
        outcome_root=root,
        pointer_root=pointers,
    )
    pointer = json.loads((pointers / "event-2.json").read_text(encoding="utf-8"))
    live_path = root / "event-2" / pointer["snapshot_id"] / "event-live.json"
    live_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SnapshotValidationError, match="live data changed"):
        latest_event_outcome(2, outcome_root=root, pointer_root=pointers)


def test_collect_event_outcome_command_is_exposed() -> None:
    args = parser().parse_args(
        ["collect-event-outcome", "--event", "2", "--reuse-latest-official"]
    )
    assert args.event == 2
    assert args.reuse_latest_official is True
