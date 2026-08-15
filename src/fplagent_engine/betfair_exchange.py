from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

BETFAIR_COMPETITION_NAME = "English Premier League"
BETFAIR_BOOTSTRAP_URL = "https://www.betfair.com/exchange/plus/en/football"
BETFAIR_COMPETITION_URL_TEMPLATE = (
    "https://www.betfair.com/exchange/plus/en/football/"
    "english-premier-league-betting-{competition_id}"
)
BETFAIR_NAVIGATION_URL = "https://apieds.betfair.com/api/eds/navigation-aggregator/v2"
BETFAIR_FACET_URL = (
    "https://scan-inbf.betfair.com/www/sports/navigation/facet/v1/search"
)
BETFAIR_BY_EVENT_URL = (
    "https://ero.betfair.com/www/sports/exchange/readonly/v1/byevent"
)
BETFAIR_BY_MARKET_URL = (
    "https://ero.betfair.com/www/sports/exchange/readonly/v1/bymarket"
)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/139.0.0.0 Safari/537.36 FPLAgent-research/0.1"
)
_RETRYABLE_HTTP_STATUS = {403, 408, 429, 500, 502, 503, 504}
_REQUEST_ATTEMPTS = 3
_MARKET_TYPES = ("MATCH_ODDS", "OVER_UNDER_25")
_PRICE_TYPES = (
    "MARKET_STATE,MARKET_RATES,MARKET_DESCRIPTION,EVENT,RUNNER_DESCRIPTION,"
    "RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST"
)


class BetfairExchangeError(RuntimeError):
    pass


def _request_headers(*, accept: str) -> dict[str, str]:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": BETFAIR_BOOTSTRAP_URL,
        "Cache-Control": "no-cache",
    }


def _read_request(request: urllib.request.Request) -> bytes:
    for attempt in range(_REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_HTTP_STATUS or attempt + 1 >= _REQUEST_ATTEMPTS:
                raise
            time.sleep(0.35 * (2**attempt))
    raise AssertionError("Betfair request retry loop exhausted without a result")


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers=_request_headers(accept="application/json,text/html"),
    )
    return _read_request(request)


def _post_json(url: str, payload: Mapping[str, Any]) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            **_request_headers(accept="application/json"),
            "Content-Type": "application/json",
        },
    )
    return _read_request(request)


def extract_app_key(page: str) -> str:
    match = re.search(
        r'"default"\s*:\s*\{\s*"EDSKey"\s*:\s*"([A-Za-z0-9]+)"', page
    )
    if match is None:
        raise BetfairExchangeError("Betfair public EDS application key is missing")
    return match.group(1)


def discover_competition(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the exact EPL competition instead of trusting a durable numeric ID."""
    attachments = payload.get("attachments")
    competitions = (
        attachments.get("competitions") if isinstance(attachments, Mapping) else None
    )
    matches = []
    if isinstance(competitions, Mapping):
        for row in competitions.values():
            if not isinstance(row, Mapping):
                continue
            if str(row.get("name") or "").strip() != BETFAIR_COMPETITION_NAME:
                continue
            if int(row.get("eventTypeId") or 0) != 1:
                continue
            if row.get("competitionId") is not None:
                matches.append(dict(row))
    if len(matches) != 1:
        raise BetfairExchangeError(
            "Betfair competition discovery did not return exactly one English Premier League"
        )
    return matches[0]


def competition_search_payload() -> dict[str, Any]:
    return {
        "filter": {
            "marketBettingTypes": [],
            "productTypes": ["EXCHANGE"],
            "marketTypeCodes": [],
            "selectBy": "RANK",
            "maxResults": 20,
        },
        "textQuery": {
            "query": BETFAIR_COMPETITION_NAME,
            "facetsToSearch": ["COMPETITION"],
        },
        "facets": [],
    }


def _url(base: str, params: Mapping[str, Any]) -> str:
    return f"{base}?{urllib.parse.urlencode(params)}"


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _event_nodes(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for event_type in payload.get("eventTypes") or []:
        if not isinstance(event_type, Mapping):
            continue
        for node in event_type.get("eventNodes") or []:
            if isinstance(node, Mapping):
                yield node


def _market_nodes(payload: Mapping[str, Any]) -> Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    for event in _event_nodes(payload):
        for market in event.get("marketNodes") or []:
            if isinstance(market, Mapping):
                yield event, market


def _best_exchange_mid(runner: Mapping[str, Any]) -> dict[str, float] | None:
    exchange = runner.get("exchange")
    if not isinstance(exchange, Mapping):
        return None
    backs = exchange.get("availableToBack") or []
    lays = exchange.get("availableToLay") or []
    if not backs or not lays:
        return None
    try:
        back = float(backs[0]["price"])
        lay = float(lays[0]["price"])
        back_size = float(backs[0]["size"])
        lay_size = float(lays[0]["size"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (back, lay, back_size, lay_size)):
        return None
    if back <= 1.0 or lay <= 1.0 or back > lay or back_size < 0.0 or lay_size < 0.0:
        return None
    midpoint_probability = ((1.0 / back) + (1.0 / lay)) / 2.0
    return {
        "odds": 1.0 / midpoint_probability,
        "best_back": back,
        "best_lay": lay,
        "best_back_size": back_size,
        "best_lay_size": lay_size,
        "probability_spread": (1.0 / back) - (1.0 / lay),
    }


def _named_runners(market: Mapping[str, Any]) -> dict[str, tuple[Mapping[str, Any], dict[str, float]]]:
    result = {}
    for runner in market.get("runners") or []:
        if not isinstance(runner, Mapping):
            continue
        description = runner.get("description")
        name = description.get("runnerName") if isinstance(description, Mapping) else None
        price = _best_exchange_mid(runner)
        if name and price is not None:
            result[str(name)] = (runner, price)
    return result


def build_exchange_rows(
    navigation: Mapping[str, Any],
    catalogues: Iterable[Mapping[str, Any]],
    prices: Iterable[Mapping[str, Any]],
    *,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Normalize anonymous Betfair 1X2 and O/U 2.5 books into fixture rows."""
    fixtures = {
        int(row["eventId"]): row
        for rows in (navigation.get("fixtures") or {}).values()
        for row in rows
        if isinstance(row, Mapping) and row.get("eventId") is not None
    }
    market_ids: dict[tuple[int, str], str] = {}
    for payload in catalogues:
        for event, market in _market_nodes(payload):
            description = market.get("description")
            market_type = (
                str(description.get("marketType"))
                if isinstance(description, Mapping) and description.get("marketType")
                else ""
            )
            if market_type in _MARKET_TYPES and market.get("marketId"):
                market_ids[(int(event["eventId"]), market_type)] = str(market["marketId"])

    books: dict[tuple[int, str], Mapping[str, Any]] = {}
    for payload in prices:
        for event, market in _market_nodes(payload):
            description = market.get("description")
            market_type = (
                str(description.get("marketType"))
                if isinstance(description, Mapping) and description.get("marketType")
                else ""
            )
            if market_type in _MARKET_TYPES:
                books[(int(event["eventId"]), market_type)] = market

    rows = []
    for event_id, fixture in fixtures.items():
        match = books.get((event_id, "MATCH_ODDS"))
        totals = books.get((event_id, "OVER_UNDER_25"))
        if match is None or totals is None:
            continue
        event_name = str(fixture.get("name") or "")
        if " v " not in event_name:
            continue
        home_name, away_name = event_name.split(" v ", 1)
        match_runners = _named_runners(match)
        total_runners = _named_runners(totals)
        required = (
            match_runners.get(home_name),
            match_runners.get("The Draw"),
            match_runners.get(away_name),
            total_runners.get("Over 2.5 Goals"),
            total_runners.get("Under 2.5 Goals"),
        )
        if any(value is None for value in required):
            continue
        home, draw, away, over, under = (value[1] for value in required if value is not None)
        match_state = match.get("state") if isinstance(match.get("state"), Mapping) else {}
        totals_state = totals.get("state") if isinstance(totals.get("state"), Mapping) else {}
        rows.append(
            {
                "Div": "E0",
                "HomeTeam": home_name,
                "AwayTeam": away_name,
                "AvgH": home["odds"],
                "AvgD": draw["odds"],
                "AvgA": away["odds"],
                "Avg>2.5": over["odds"],
                "Avg<2.5": under["odds"],
                "betfair_event_id": event_id,
                "betfair_match_market_id": market_ids.get((event_id, "MATCH_ODDS")),
                "betfair_totals_market_id": market_ids.get((event_id, "OVER_UNDER_25")),
                "betfair_match_total_matched": float(match_state.get("totalMatched") or 0.0),
                "betfair_totals_total_matched": float(totals_state.get("totalMatched") or 0.0),
                "betfair_match_last_match_at": match_state.get("lastMatchTime"),
                "betfair_totals_last_match_at": totals_state.get("lastMatchTime"),
                "betfair_delayed": bool(match.get("isMarketDataDelayed"))
                or bool(totals.get("isMarketDataDelayed")),
                "betfair_home_best_back": home["best_back"],
                "betfair_home_best_lay": home["best_lay"],
                "betfair_draw_best_back": draw["best_back"],
                "betfair_draw_best_lay": draw["best_lay"],
                "betfair_away_best_back": away["best_back"],
                "betfair_away_best_lay": away["best_lay"],
                "betfair_over_best_back": over["best_back"],
                "betfair_over_best_lay": over["best_lay"],
                "betfair_under_best_back": under["best_back"],
                "betfair_under_best_lay": under["best_lay"],
                "betfair_max_probability_spread": max(
                    value["probability_spread"] for value in (home, draw, away, over, under)
                ),
                "source_observed_at": observed_at,
            }
        )
    return sorted(rows, key=lambda row: (str(row["HomeTeam"]), str(row["AwayTeam"])))


def collect_betfair_exchange_snapshot(
    *,
    fetch: Callable[[str], bytes] = _download,
    post: Callable[[str, Mapping[str, Any]], bytes] = _post_json,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Collect public delayed exchange prices without account credentials or browser automation."""
    clock = now or (lambda: datetime.now(UTC))
    observed = clock().astimezone(UTC).isoformat()
    page_payload = fetch(BETFAIR_BOOTSTRAP_URL)
    app_key = extract_app_key(page_payload.decode("utf-8", errors="replace"))
    facet_url = _url(BETFAIR_FACET_URL, {"_ak": app_key, "alt": "json"})
    discovery_payload = post(facet_url, competition_search_payload())
    competition = discover_competition(json.loads(discovery_payload))
    competition_id = int(competition["competitionId"])
    competition_url = BETFAIR_COMPETITION_URL_TEMPLATE.format(
        competition_id=competition_id
    )
    navigation_url = _url(
        BETFAIR_NAVIGATION_URL,
        {
            "_ak": app_key,
            "competitionId": competition_id,
            "timezone": "Europe/London",
        },
    )
    navigation_payload = fetch(navigation_url)
    navigation = json.loads(navigation_payload)
    event_ids = sorted(
        {
            str(row["eventId"])
            for rows in (navigation.get("fixtures") or {}).values()
            for row in rows
            if isinstance(row, Mapping) and row.get("eventId") is not None
        }
    )
    if not event_ids:
        raise BetfairExchangeError("Betfair navigation returned no Premier League fixtures")

    documents = [
        {"name": "bootstrap", "url": BETFAIR_BOOTSTRAP_URL, "payload": page_payload},
        {"name": "competition-search", "url": facet_url, "payload": discovery_payload},
        {"name": "navigation", "url": navigation_url, "payload": navigation_payload},
    ]
    catalogues = []
    # The anonymous catalogue returns every market attached to each event and rejects
    # larger batches with TOO_MUCH_DATA, even when only descriptions are requested.
    for index, chunk in enumerate(_chunks(event_ids, 2), start=1):
        url = _url(
            BETFAIR_BY_EVENT_URL,
            {
                "_ak": app_key,
                "currencyCode": "GBP",
                "eventIds": ",".join(chunk),
                "locale": "en_GB",
                "rollupLimit": 10,
                "rollupModel": "STAKE",
                "types": "MARKET_STATE,EVENT,MARKET_DESCRIPTION",
            },
        )
        payload = fetch(url)
        documents.append({"name": f"catalogue-{index}", "url": url, "payload": payload})
        catalogues.append(json.loads(payload))

    market_ids = sorted(
        {
            str(market["marketId"])
            for payload in catalogues
            for _, market in _market_nodes(payload)
            if isinstance(market.get("description"), Mapping)
            and market["description"].get("marketType") in _MARKET_TYPES
            and market.get("marketId")
        }
    )
    if not market_ids:
        raise BetfairExchangeError("Betfair returned no Match Odds or O/U 2.5 markets")

    prices = []
    for index, chunk in enumerate(_chunks(market_ids, 10), start=1):
        url = _url(
            BETFAIR_BY_MARKET_URL,
            {
                "_ak": app_key,
                "alt": "json",
                "currencyCode": "GBP",
                "locale": "en_GB",
                "marketIds": ",".join(chunk),
                "rollupLimit": 10,
                "rollupModel": "STAKE",
                "types": _PRICE_TYPES,
            },
        )
        payload = fetch(url)
        documents.append({"name": f"prices-{index}", "url": url, "payload": payload})
        prices.append(json.loads(payload))

    rows = build_exchange_rows(
        navigation,
        catalogues,
        prices,
        observed_at=observed,
    )
    semantic = {
        "provider": "betfair_exchange_public_delayed",
        "competition_id": competition_id,
        "competition_name": BETFAIR_COMPETITION_NAME,
        "competition_url": competition_url,
        "event_ids": event_ids,
        "market_ids": market_ids,
        "rows": rows,
    }
    return {
        **semantic,
        "observed_at": observed,
        "semantic_sha256": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "documents": documents,
    }
