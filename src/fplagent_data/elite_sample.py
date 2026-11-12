"""A weekly sample of high-ranked managers from the public FPL API.

The sample answers two questions the engine cannot answer from forecasts:
how many points the managers ahead scored each week, and which players they
own. Ownership is evidence about the field, never a forecast input. It is
used to measure the bets a squad takes against that field and to break ties
between players the forecast cannot separate.

Only public endpoints are read. No account data is sent.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTORY = ROOT / "data/analysis/elite"
API = "https://fantasy.premierleague.com/api/"
OVERALL_LEAGUE = 314
VERSION = "elite_sample_v1"
# Standings pages hold 50 managers, so page 20 starts at rank 951 and page 200
# at rank 9,951.
SAMPLE_BANDS = (("top_1k", 20), ("top_10k", 200))
THRESHOLD_PAGES = (
    ("rank_1", 1), ("top_1k", 20), ("top_10k", 200), ("top_100k", 2000),
    ("top_500k", 10000), ("top_1m", 20000),
)


def _public_get(client: httpx.Client, route: str, *, pause: float = 0.25) -> Any:
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = client.get(API + route)
            response.raise_for_status()
            time.sleep(pause)
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Public FPL request failed: {route}") from last


def summarise_sample(
    managers: Mapping[int, Mapping[str, Any]], *, event: int
) -> dict[str, Any]:
    """Ownership, captaincy, chips and weekly scores across the sampled managers."""
    count = len(managers)
    if not count:
        raise ValueError("Elite sample is empty")
    owned: Counter[int] = Counter()
    started: Counter[int] = Counter()
    captained: Counter[int] = Counter()
    chips: Counter[str] = Counter()
    active_chips: Counter[str] = Counter()
    for manager in managers.values():
        picks = manager["picks"]
        if picks.get("active_chip"):
            active_chips[str(picks["active_chip"])] += 1
        for pick in picks["picks"]:
            element = int(pick["element"])
            owned[element] += 1
            if int(pick["multiplier"]) > 0:
                started[element] += 1
            if pick["is_captain"]:
                captained[element] += 1
        for chip in manager["history"]["chips"]:
            if int(chip["event"]) <= event:
                chips[str(chip["name"])] += 1
    weekly = {
        week: statistics.median(
            int(row["points"]) - int(row["event_transfers_cost"])
            for manager in managers.values()
            for row in manager["history"]["current"]
            if int(row["event"]) == week
        )
        for week in range(1, event + 1)
        if any(
            int(row["event"]) == week
            for manager in managers.values()
            for row in manager["history"]["current"]
        )
    }
    return {
        "managers": count,
        "ownership": {str(k): v / count for k, v in sorted(owned.items())},
        "started": {str(k): v / count for k, v in sorted(started.items())},
        "captaincy": {str(k): v / count for k, v in sorted(captained.items())},
        "chips_played_to_date": {k: v / count for k, v in sorted(chips.items())},
        "active_chips": dict(sorted(active_chips.items())),
        "median_net_points_by_event": {str(k): v for k, v in weekly.items()},
        "median_total_points": statistics.median(
            int(manager["history"]["current"][-1]["total_points"])
            for manager in managers.values()
        ),
    }


def fetch_elite_sample(
    event: int,
    *,
    per_band: int = 30,
    directory: Path = DEFAULT_DIRECTORY,
    client: httpx.Client | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fetch and save the sample for a finished or locked Gameweek."""
    own_client = client is None
    client = client or httpx.Client(
        timeout=30, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False
    )
    try:
        thresholds = {}
        entries: list[int] = []
        for name, page in THRESHOLD_PAGES:
            rows = _public_get(
                client, f"leagues-classic/{OVERALL_LEAGUE}/standings/?page_standings={page}"
            )["standings"]["results"]
            thresholds[name] = {"rank": int(rows[0]["rank"]), "total": int(rows[0]["total"])}
            if any(name == band for band, _ in SAMPLE_BANDS):
                entries.extend(int(row["entry"]) for row in rows[:per_band])
        managers: dict[int, dict[str, Any]] = {}
        for index, entry in enumerate(entries, start=1):
            if progress:
                progress(f"Elite sample: manager {index} of {len(entries)}")
            managers[entry] = {
                "history": _public_get(client, f"entry/{entry}/history/"),
                "picks": _public_get(client, f"entry/{entry}/event/{event}/picks/"),
            }
    finally:
        if own_client:
            client.close()
    receipt = {
        "version": VERSION,
        "event": event,
        "created_at": datetime.now(UTC).isoformat(),
        "thresholds": thresholds,
        "sample_bands": [band for band, _ in SAMPLE_BANDS],
        **summarise_sample(managers, event=event),
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"gw{event:02d}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return receipt


def load_elite_sample(
    event: int | None = None, *, directory: Path = DEFAULT_DIRECTORY
) -> dict[str, Any] | None:
    """The sample for ``event``, or the latest saved one when no event is given."""
    paths = sorted(directory.glob("gw*.json"))
    if event is not None:
        paths = [p for p in paths if p.name == f"gw{event:02d}.json"]
    if not paths:
        return None
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def field_exposure(
    squad: Sequence[int],
    sample: Mapping[str, Any],
    *,
    names: Mapping[int, str] | None = None,
    template_share: float = 0.5,
) -> dict[str, Any]:
    """How far a squad sits from the sampled field.

    ``against`` lists widely owned players the squad lacks: each of their
    points is a loss against that share of the field. ``differentials`` are
    held players few of the field own.
    """
    ownership = {int(k): float(v) for k, v in sample["ownership"].items()}
    held = {int(p) for p in squad}
    label = (lambda p: (names or {}).get(p, str(p)))
    return {
        "mean_field_ownership_of_squad": sum(ownership.get(p, 0.0) for p in held) / len(held),
        "expected_shared_players": sum(ownership.get(p, 0.0) for p in held),
        "against": [
            {"element": p, "name": label(p), "field_ownership": share}
            for p, share in sorted(ownership.items(), key=lambda item: -item[1])
            if share >= template_share and p not in held
        ],
        "differentials": [
            {"element": p, "name": label(p), "field_ownership": ownership.get(p, 0.0)}
            for p in sorted(held, key=lambda p: ownership.get(p, 0.0))
            if ownership.get(p, 0.0) < 0.1
        ],
    }


# A weekly gap to the sampled median has a standard deviation of about 20
# points, so five weeks of ordinary luck spans roughly 45 either way. Trailing
# by more than that prompts a review of decisions; it never changes a pick.
SCOREBOARD_WINDOW = 5
SCOREBOARD_REVIEW_GAP = -50


def ensure_elite_sample(event: int, *, directory: Path = DEFAULT_DIRECTORY) -> dict[str, Any]:
    """The saved sample for ``event``, fetched once if it is missing."""
    return load_elite_sample(event, directory=directory) or fetch_elite_sample(
        event, directory=directory
    )


def latest_finished_event() -> int | None:
    """The last Gameweek whose official points are final."""
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
        events = _public_get(client, "bootstrap-static/", pause=0)["events"]
    done = [int(e["id"]) for e in events if e.get("finished") and e.get("data_checked")]
    return max(done) if done else None


def scoreboard(
    events: Sequence[Mapping[str, Any]],
    sample: Mapping[str, Any],
    *,
    squad: Sequence[int] = (),
    names: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Our weekly net points against the sampled top-manager median.

    ``events`` are finished weeks with ``event`` and ``net_points``. The result
    is a measurement: ``status`` asks for a review, it does not select players.
    """
    medians = {int(k): float(v) for k, v in sample["median_net_points_by_event"].items()}
    weeks, running = [], 0.0
    for row in sorted(events, key=lambda r: int(r["event"])):
        event = int(row["event"])
        if event not in medians:
            continue
        gap = float(row["net_points"]) - medians[event]
        running += gap
        weeks.append({"event": event, "net_points": int(row["net_points"]),
                      "top_manager_median": medians[event], "gap": gap,
                      "season_gap": running})
    recent = weeks[-SCOREBOARD_WINDOW:]
    recent_gap = sum(w["gap"] for w in recent)
    if len(recent) < SCOREBOARD_WINDOW:
        status = "too_early"
    elif recent_gap <= SCOREBOARD_REVIEW_GAP:
        status = "review"
    else:
        status = "on_pace"
    exposure = field_exposure(squad, sample, names=names) if squad else None
    return {
        "sample_event": int(sample["event"]),
        "managers": int(sample["managers"]),
        "sample_bands": list(sample.get("sample_bands", [])),
        "thresholds": sample.get("thresholds", {}),
        "weeks": weeks,
        "window": SCOREBOARD_WINDOW,
        "recent_gap": recent_gap,
        "review_gap": SCOREBOARD_REVIEW_GAP,
        "season_gap": running,
        "status": status,
        "widely_owned_missing": (exposure or {}).get("against", [])[:6],
        "shared_players": (exposure or {}).get("expected_shared_players"),
        "decision_authority": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a weekly sample of high-ranked FPL managers")
    parser.add_argument("--event", type=int, required=True)
    parser.add_argument("--per-band", type=int, default=30)
    args = parser.parse_args()
    receipt = fetch_elite_sample(args.event, per_band=args.per_band, progress=print)
    print(
        f"GW{args.event}: {receipt['managers']} managers, median total "
        f"{receipt['median_total_points']}, top 10k line {receipt['thresholds']['top_10k']['total']}"
    )


if __name__ == "__main__":
    main()
