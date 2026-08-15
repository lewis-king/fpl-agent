import json
import urllib.error
from datetime import UTC, datetime

import pytest

from fplagent_engine.betfair_exchange import (
    _download,
    build_exchange_rows,
    collect_betfair_exchange_snapshot,
    discover_competition,
    extract_app_key,
)


def _runner(name: str, back: float, lay: float) -> dict:
    return {
        "description": {"runnerName": name},
        "exchange": {
            "availableToBack": [{"price": back, "size": 10.0}],
            "availableToLay": [{"price": lay, "size": 12.0}],
        },
    }


def _payloads() -> tuple[dict, dict, dict]:
    navigation = {
        "fixtures": {
            "2026-08-21": [
                {"eventId": 7, "name": "Arsenal v Coventry"},
            ]
        }
    }
    catalogue = {
        "eventTypes": [
            {
                "eventNodes": [
                    {
                        "eventId": 7,
                        "marketNodes": [
                            {
                                "marketId": "1.1",
                                "description": {"marketType": "MATCH_ODDS"},
                            },
                            {
                                "marketId": "1.2",
                                "description": {"marketType": "OVER_UNDER_25"},
                            },
                        ],
                    }
                ]
            }
        ]
    }
    prices = {
        "eventTypes": [
            {
                "eventNodes": [
                    {
                        "eventId": 7,
                        "marketNodes": [
                            {
                                "marketId": "1.1",
                                "isMarketDataDelayed": True,
                                "description": {"marketType": "MATCH_ODDS"},
                                "state": {"totalMatched": 100.0},
                                "runners": [
                                    _runner("Arsenal", 1.8, 1.82),
                                    _runner("Coventry", 5.0, 5.2),
                                    _runner("The Draw", 3.8, 3.9),
                                ],
                            },
                            {
                                "marketId": "1.2",
                                "description": {"marketType": "OVER_UNDER_25"},
                                "state": {"totalMatched": 50.0},
                                "runners": [
                                    _runner("Under 2.5 Goals", 2.0, 2.04),
                                    _runner("Over 2.5 Goals", 1.9, 1.94),
                                ],
                            },
                        ],
                    }
                ]
            }
        ]
    }
    return navigation, catalogue, prices


def test_exchange_rows_use_probability_midpoint_and_named_runners() -> None:
    navigation, catalogue, prices = _payloads()
    rows = build_exchange_rows(
        navigation,
        [catalogue],
        [prices],
        observed_at="2026-08-09T18:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["HomeTeam"] == "Arsenal"
    assert rows[0]["AwayTeam"] == "Coventry"
    assert rows[0]["betfair_match_market_id"] == "1.1"
    assert rows[0]["betfair_totals_market_id"] == "1.2"
    expected_home = 1.0 / (((1.0 / 1.8) + (1.0 / 1.82)) / 2.0)
    assert rows[0]["AvgH"] == pytest.approx(expected_home)
    assert rows[0]["betfair_delayed"] is True


def test_collect_discovers_public_key_and_requests_both_market_types() -> None:
    navigation, catalogue, prices = _payloads()
    calls = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if url.endswith("/football"):
            return b'"default": {"EDSKey": "public123"}'
        if "navigation-aggregator" in url:
            return json.dumps(navigation).encode()
        if "byevent" in url:
            return json.dumps(catalogue).encode()
        if "bymarket" in url:
            return json.dumps(prices).encode()
        raise AssertionError(url)

    def post(url: str, payload: dict) -> bytes:
        calls.append(url)
        assert payload["textQuery"]["query"] == "English Premier League"
        return json.dumps(
            {
                "attachments": {
                    "competitions": {
                        "future-id": {
                            "competitionId": 10932509,
                            "eventTypeId": 1,
                            "name": "English Premier League",
                        }
                    }
                }
            }
        ).encode()

    result = collect_betfair_exchange_snapshot(
        fetch=fetch,
        post=post,
        now=lambda: datetime(2026, 8, 9, 18, tzinfo=UTC),
    )

    assert len(result["rows"]) == 1
    assert result["event_ids"] == ["7"]
    assert result["market_ids"] == ["1.1", "1.2"]
    assert any("_ak=public123" in url and "eventIds=7" in url for url in calls)
    assert any("marketIds=1.1%2C1.2" in url for url in calls)
    assert extract_app_key('"default": {"EDSKey": "again456"}') == "again456"


def test_competition_discovery_requires_exact_football_name() -> None:
    competition = discover_competition(
        {
            "attachments": {
                "competitions": {
                    "1": {
                        "competitionId": 1,
                        "eventTypeId": 1,
                        "name": "English Northern Premier League",
                    },
                    "2": {
                        "competitionId": 2,
                        "eventTypeId": 1,
                        "name": "English Premier League",
                    },
                }
            }
        }
    )
    assert competition["competitionId"] == 2


def test_exchange_download_retries_a_transient_public_endpoint_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def read() -> bytes:
            return b"ready"

    def urlopen(request: object, *, timeout: int) -> Response:
        nonlocal attempts
        attempts += 1
        assert timeout == 30
        if attempts == 1:
            raise urllib.error.HTTPError(
                url="https://example.test",
                code=403,
                msg="transient",
                hdrs=None,
                fp=None,
            )
        return Response()

    monkeypatch.setattr("fplagent_engine.betfair_exchange.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("fplagent_engine.betfair_exchange.time.sleep", lambda _seconds: None)

    assert _download("https://example.test") == b"ready"
    assert attempts == 2
