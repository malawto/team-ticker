"""team-ticker poller — Stage 1.

Fetches the configured team's current fixture status from ESPN's
(unofficial) soccer scoreboard API, determines whether a match is live,
upcoming/just-finished today ("matchday"), or there's no match today
("idle"), and writes the result to ticker.json.

Which team/league to track is configured via the TEAM_ID and LEAGUE
environment variables (see .env.example) — this module has no team baked in.
The defaults (364 / eng.1, i.e. Liverpool / English Premier League) are just
the reference instance this project was built against, not the only
supported team.

Run once: `python poller.py`. No scheduling loop yet — that's added later
when this moves into a container.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# Reference instance this project was built against — not the only
# supported team. Override via the TEAM_ID / LEAGUE env vars (see
# .env.example).
DEFAULT_TEAM_ID = "364"  # Liverpool FC
DEFAULT_LEAGUE = "eng.1"  # English Premier League

SCOREBOARD_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
)

# Note the different path prefix from SCOREBOARD_URL_TEMPLATE — the
# apis/site/v2 standings endpoint (mirroring the scoreboard path) returns an
# empty object for eng.1; this apis/v2 path is the one that actually returns
# standings data (verified against the real API).
STANDINGS_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/v2/sports/soccer/{league}/standings"
)

# General football news, not per-league — BBC doesn't offer a per-league feed.
HEADLINES_URL = "https://feeds.bbci.co.uk/sport/football/rss.xml"

# The team "schedule" endpoint only returns already-played fixtures (verified
# against the real API — `?season=` and `?half=` don't change that), so next
# fixture is found by querying the scoreboard with a forward-looking `dates`
# range instead.
NEXT_FIXTURE_LOOKAHEAD_DAYS = 30

# How many places above/below the configured team to include in idle mode's
# table slice, and how many headlines to surface.
TABLE_CONTEXT_SIZE = 2
HEADLINES_LIMIT = 5

USER_AGENT = "team-ticker-poller/0.1 (+https://github.com/mikelawton/team-ticker)"

TICKER_JSON_PATH = "ticker.json"

REQUEST_TIMEOUT_SECONDS = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("poller")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    team_id: str
    league: str
    scoreboard_url: str
    standings_url: str


def load_config() -> Config:
    """Load TEAM_ID/LEAGUE from the environment (via .env if present).

    Fails fast (logs and exits) on an unset/invalid TEAM_ID rather than
    letting a doomed API call fail confusingly downstream.
    """
    load_dotenv()

    team_id = os.environ.get("TEAM_ID", DEFAULT_TEAM_ID).strip()
    league = os.environ.get("LEAGUE", DEFAULT_LEAGUE).strip()

    if not team_id or not team_id.isdigit():
        log.error(
            "TEAM_ID is unset or invalid (%r) — set TEAM_ID in your .env or "
            "environment to your team's numeric ESPN team id.",
            team_id,
        )
        sys.exit(1)

    if not league:
        log.error(
            "LEAGUE is unset — set LEAGUE in your .env or environment to "
            "your league's ESPN slug (e.g. eng.1)."
        )
        sys.exit(1)

    return Config(
        team_id=team_id,
        league=league,
        scoreboard_url=SCOREBOARD_URL_TEMPLATE.format(league=league),
        standings_url=STANDINGS_URL_TEMPLATE.format(league=league),
    )


# --------------------------------------------------------------------------
# HTTP fetching
# --------------------------------------------------------------------------


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def fetch_json(
    session: requests.Session, url: str, params: Optional[dict] = None
) -> Optional[dict]:
    """Fetch and parse a JSON endpoint. Returns None on any failure."""
    log.info("fetching %s params=%s", url, params)
    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.error("fetch failed for %s: %s", url, exc)
        return None

    try:
        return response.json()
    except ValueError as exc:
        log.error("could not parse JSON from %s: %s", url, exc)
        return None


def fetch_text(
    session: requests.Session, url: str, params: Optional[dict] = None
) -> Optional[str]:
    """Fetch a URL and return its raw response body. Returns None on failure."""
    log.info("fetching %s params=%s", url, params)
    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.error("fetch failed for %s: %s", url, exc)
        return None
    return response.text


def fetch_scoreboard(session: requests.Session, scoreboard_url: str) -> Optional[dict]:
    return fetch_json(session, scoreboard_url)


def fetch_standings(session: requests.Session, standings_url: str) -> Optional[dict]:
    return fetch_json(session, standings_url)


def fetch_headlines_xml(
    session: requests.Session, headlines_url: str = HEADLINES_URL
) -> Optional[str]:
    return fetch_text(session, headlines_url)


def fetch_upcoming_scoreboard(
    session: requests.Session,
    scoreboard_url: str,
    now: Optional[datetime] = None,
    days_ahead: int = NEXT_FIXTURE_LOOKAHEAD_DAYS,
) -> Optional[dict]:
    """Fetch a forward-looking window of fixtures via the `dates` range param.

    Same response shape as the plain scoreboard endpoint, just covering
    [now, now + days_ahead] instead of "today".
    """
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)
    dates_param = f"{now:%Y%m%d}-{end:%Y%m%d}"
    return fetch_json(session, scoreboard_url, params={"dates": dates_param})


# --------------------------------------------------------------------------
# Mode detection (pure, testable without hitting the network)
# --------------------------------------------------------------------------


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _find_team_competitor(
    competitors: list[dict], team_id: str
) -> tuple[Optional[dict], Optional[dict]]:
    """Return (team_competitor, opponent_competitor) from a competitors list."""
    team_competitor = None
    opponent_competitor = None
    for competitor in competitors or []:
        competitor_team_id = str((competitor.get("team") or {}).get("id", ""))
        if competitor_team_id == str(team_id):
            team_competitor = competitor
        else:
            opponent_competitor = competitor
    return team_competitor, opponent_competitor


def find_team_competition(scoreboard_data: dict, team_id: str) -> Optional[dict]:
    """Find today's competition (match) dict involving team_id, if any.

    Returns the raw ESPN "competition" object (has status + competitors),
    or None if the team has no match in this scoreboard response.
    """
    if not scoreboard_data:
        return None

    for event in scoreboard_data.get("events") or []:
        for competition in event.get("competitions") or []:
            competitors = competition.get("competitors") or []
            team_competitor, _ = _find_team_competitor(competitors, team_id)
            if team_competitor is not None:
                return competition

    return None


def classify_competition(competition: dict, team_id: str) -> dict:
    """Turn a competition dict into a live/matchday mode payload.

    Assumes `competition` involves `team_id` (i.e. came from
    find_team_competition). Pure function, no network access.
    """
    competitors = competition.get("competitors") or []
    team_competitor, opponent_competitor = _find_team_competitor(
        competitors, team_id
    )

    opponent_name = (
        (opponent_competitor or {}).get("team", {}).get("displayName")
        or (opponent_competitor or {}).get("team", {}).get("name")
        or "Unknown"
    )
    home_away = (team_competitor or {}).get("homeAway", "unknown")

    status = competition.get("status") or {}
    status_type = status.get("type") or {}
    state = status_type.get("state", "pre")

    if state == "in":
        return {
            "mode": "live",
            "live": {
                "opponent": opponent_name,
                "home_away": home_away,
                "score": {
                    "team": _safe_int((team_competitor or {}).get("score")),
                    "opponent": _safe_int((opponent_competitor or {}).get("score")),
                },
                "clock": status.get("displayClock"),
                "period": status.get("period"),
                "status_detail": status_type.get("shortDetail")
                or status_type.get("detail"),
            },
        }

    # "pre" (not started) or "post" (finished) -> matchday
    matchday: dict[str, Any] = {
        "opponent": opponent_name,
        "home_away": home_away,
    }
    if state == "post":
        matchday["final_score"] = {
            "team": _safe_int((team_competitor or {}).get("score")),
            "opponent": _safe_int((opponent_competitor or {}).get("score")),
        }
    else:
        matchday["kickoff_utc"] = competition.get("date") or ""

    return {"mode": "matchday", "matchday": matchday}


def next_fixture_from_scoreboard_range(
    range_data: Optional[dict], team_id: str, now: datetime
) -> dict:
    """Find the next upcoming fixture for team_id from a scoreboard response
    covering a forward-looking date range (see fetch_upcoming_scoreboard).

    Returns an idle-mode "next_fixture" payload; falls back to a placeholder
    if the data is missing/empty or has no not-yet-started events.
    """
    placeholder = {"opponent": None, "kickoff_utc": None, "home_away": None}

    if not range_data:
        return placeholder

    events = range_data.get("events") or []
    upcoming = []
    for event in events:
        event_date_str = event.get("date")
        if not event_date_str:
            continue
        try:
            event_date = datetime.fromisoformat(
                event_date_str.replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if event_date <= now:
            continue

        for competition in event.get("competitions") or []:
            status_state = (
                (competition.get("status") or {}).get("type") or {}
            ).get("state")
            if status_state != "pre":
                continue

            competitors = competition.get("competitors") or []
            team_competitor, opponent_competitor = _find_team_competitor(
                competitors, team_id
            )
            if team_competitor is None:
                continue
            upcoming.append(
                (
                    event_date,
                    {
                        "opponent": (opponent_competitor or {})
                        .get("team", {})
                        .get("displayName")
                        or "Unknown",
                        "kickoff_utc": event_date_str,
                        "home_away": team_competitor.get("homeAway", "unknown"),
                    },
                )
            )

    if not upcoming:
        return placeholder

    upcoming.sort(key=lambda pair: pair[0])
    return upcoming[0][1]


def _standings_entries(standings_data: Optional[dict]) -> list[dict]:
    """Flatten every group's entries from a standings response.

    ESPN nests the actual rows under children[].standings.entries. In
    practice a single-league standings response (like eng.1) has exactly one
    child/group; this doesn't attempt to handle multi-group standings (e.g.
    conference splits) correctly beyond concatenating them. Defensive about
    unexpected shapes (non-dict/non-list) since there's no official schema.
    """
    if not isinstance(standings_data, dict):
        return []

    children = standings_data.get("children")
    if not isinstance(children, list):
        return []

    entries: list[dict] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        standings = child.get("standings")
        if not isinstance(standings, dict):
            continue
        child_entries = standings.get("entries")
        if isinstance(child_entries, list):
            entries.extend(entry for entry in child_entries if isinstance(entry, dict))
    return entries


def table_slice_from_standings(
    standings_data: Optional[dict],
    team_id: str,
    context: int = TABLE_CONTEXT_SIZE,
) -> list[dict]:
    """Return the configured team's standings row plus `context` rows of
    surrounding table either side, sorted by position.

    Returns [] if the team isn't found in the standings (newly promoted and
    not yet listed, unexpected response shape, etc.) rather than raising.
    Pure function, no network access.
    """
    entries = _standings_entries(standings_data)

    team_index = None
    for index, entry in enumerate(entries):
        if str((entry.get("team") or {}).get("id", "")) == str(team_id):
            team_index = index
            break

    if team_index is None:
        return []

    start = max(0, team_index - context)
    end = min(len(entries), team_index + context + 1)

    rows = []
    for index, entry in enumerate(entries[start:end], start=start):
        team = entry.get("team") or {}
        stats = {stat.get("name"): stat.get("value") for stat in entry.get("stats") or []}
        rows.append(
            {
                "team": team.get("displayName") or team.get("name") or "Unknown",
                "position": _safe_int(stats.get("rank")) or (index + 1),
                "played": _safe_int(stats.get("gamesPlayed")),
                "points": _safe_int(stats.get("points")),
                "goal_difference": _safe_int(stats.get("pointDifferential")),
                "is_team": index == team_index,
            }
        )
    return rows


def headlines_from_rss(
    xml_text: Optional[str],
    team_display_name: Optional[str] = None,
    limit: int = HEADLINES_LIMIT,
) -> list[str]:
    """Extract up to `limit` headline titles from a BBC Sport RSS feed body.

    When `team_display_name` is given, headlines mentioning it (case
    insensitive) are surfaced first, then general headlines fill any
    remaining slots — general headlines are never dropped just because
    there aren't enough team-specific ones. Pure function: takes the
    already-fetched XML text, does no network access, and returns []
    rather than raising on empty/malformed XML.
    """
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.error("could not parse RSS feed XML")
        return []

    titles = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        if title:
            titles.append(title)

    if not team_display_name:
        return titles[:limit]

    needle = team_display_name.lower()
    team_titles = [title for title in titles if needle in title.lower()]
    other_titles = [title for title in titles if needle not in title.lower()]
    return (team_titles + other_titles)[:limit]


def determine_mode(
    scoreboard_data: Optional[dict],
    upcoming_scoreboard_data: Optional[dict] = None,
    standings_data: Optional[dict] = None,
    headlines_xml: Optional[str] = None,
    team_id: str = DEFAULT_TEAM_ID,
    now: Optional[datetime] = None,
) -> dict:
    """Pure mode-detection entry point.

    Given already-fetched (or hand-built, for tests) ESPN/BBC payloads,
    return a dict with a "mode" key ("live" / "matchday" / "idle") and the
    mode-specific payload. Does no I/O. `team_id` is an explicit parameter
    (not read from global config) so this stays testable without env setup —
    callers wire in the configured team's id (see Config/load_config).

    `upcoming_scoreboard_data`, `standings_data`, and `headlines_xml`, when
    provided, are only consulted for idle mode's next_fixture/table/
    headlines respectively — see fetch_upcoming_scoreboard, fetch_standings,
    and fetch_headlines_xml.
    """
    now = now or datetime.now(timezone.utc)

    competition = find_team_competition(scoreboard_data or {}, team_id)
    if competition is not None:
        return classify_competition(competition, team_id)

    log.info("no match found for team %s in scoreboard; falling back to idle", team_id)

    table = table_slice_from_standings(standings_data, team_id)
    team_row = next((row for row in table if row.get("is_team")), None)
    team_display_name = team_row["team"] if team_row else None

    return {
        "mode": "idle",
        "idle": {
            "next_fixture": next_fixture_from_scoreboard_range(
                upcoming_scoreboard_data, team_id, now
            ),
            "table": table,
            "headlines": headlines_from_rss(
                headlines_xml, team_display_name=team_display_name
            ),
        },
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def build_ticker_document(mode_result: dict) -> dict:
    document = dict(mode_result)
    document["generated_at"] = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    return document


def write_ticker_json(document: dict, path: str = TICKER_JSON_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2)
    log.info("wrote %s (mode=%s)", path, document.get("mode"))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def run() -> dict:
    config = load_config()
    log.info("configured for team_id=%s league=%s", config.team_id, config.league)

    session = make_session()
    scoreboard_data = fetch_scoreboard(session, config.scoreboard_url)

    mode_result = determine_mode(scoreboard_data, team_id=config.team_id)

    # Only bother fetching next-fixture/table/headlines data if we actually
    # landed on idle mode.
    if mode_result["mode"] == "idle":
        upcoming_data = fetch_upcoming_scoreboard(session, config.scoreboard_url)
        standings_data = fetch_standings(session, config.standings_url)
        headlines_xml = fetch_headlines_xml(session)
        mode_result = determine_mode(
            scoreboard_data,
            upcoming_scoreboard_data=upcoming_data,
            standings_data=standings_data,
            headlines_xml=headlines_xml,
            team_id=config.team_id,
        )

    log.info("mode determined: %s", mode_result["mode"])

    document = build_ticker_document(mode_result)
    write_ticker_json(document)
    return document


if __name__ == "__main__":
    run()
