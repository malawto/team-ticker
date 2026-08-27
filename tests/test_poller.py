import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from poller import (
    POLL_INTERVAL_BY_MODE,
    POLL_INTERVAL_IDLE,
    POLL_INTERVAL_LIVE,
    POLL_INTERVAL_MATCHDAY,
    _run_once_requested,
    build_ticker_document,
    determine_mode,
    headlines_from_rss,
    table_slice_from_standings,
)

LIVERPOOL = {
    "id": "364",
    "displayName": "Liverpool",
}
EVERTON = {"id": "368", "displayName": "Everton"}
ARSENAL = {"id": "359", "displayName": "Arsenal"}
MAN_CITY = {"id": "382", "displayName": "Manchester City"}


def _standings_entry(team, position, played, points, goal_difference):
    return {
        "team": team,
        "stats": [
            {"name": "gamesPlayed", "value": float(played)},
            {"name": "points", "value": float(points)},
            {"name": "pointDifferential", "value": float(goal_difference)},
            {"name": "rank", "value": float(position)},
        ],
    }


def _standings_with(entries):
    return {"children": [{"standings": {"entries": entries}}]}


def _competition(state, team_score, opp_score, home_away="home",
                  opponent=EVERTON, display_clock=None, period=None,
                  short_detail=None, date="2026-08-27T19:00Z"):
    return {
        "date": date,
        "status": {
            "displayClock": display_clock,
            "period": period,
            "type": {"state": state, "shortDetail": short_detail},
        },
        "competitors": [
            {
                "homeAway": home_away,
                "team": LIVERPOOL,
                "score": str(team_score) if team_score is not None else None,
            },
            {
                "homeAway": "away" if home_away == "home" else "home",
                "team": opponent,
                "score": str(opp_score) if opp_score is not None else None,
            },
        ],
    }


def _scoreboard_with(competition):
    return {"events": [{"competitions": [competition]}]}


class DetermineModeTests(unittest.TestCase):
    def test_live_match_in_progress(self):
        competition = _competition(
            "in", 2, 1, home_away="home", opponent=EVERTON,
            display_clock="67'", period=2, short_detail="2nd Half",
        )
        result = determine_mode(_scoreboard_with(competition))

        self.assertEqual(result["mode"], "live")
        live = result["live"]
        self.assertEqual(live["opponent"], "Everton")
        self.assertEqual(live["home_away"], "home")
        self.assertEqual(live["score"], {"team": 2, "opponent": 1})
        self.assertEqual(live["clock"], "67'")

    def test_matchday_not_started(self):
        competition = _competition(
            "pre", None, None, home_away="away", opponent=MAN_CITY,
            date="2026-08-27T16:30Z",
        )
        result = determine_mode(_scoreboard_with(competition))

        self.assertEqual(result["mode"], "matchday")
        matchday = result["matchday"]
        self.assertEqual(matchday["opponent"], "Manchester City")
        self.assertEqual(matchday["home_away"], "away")
        self.assertEqual(matchday["kickoff_utc"], "2026-08-27T16:30Z")
        self.assertNotIn("final_score", matchday)

    def test_matchday_finished(self):
        competition = _competition(
            "post", 3, 0, home_away="home", opponent=ARSENAL,
        )
        result = determine_mode(_scoreboard_with(competition))

        self.assertEqual(result["mode"], "matchday")
        matchday = result["matchday"]
        self.assertEqual(matchday["opponent"], "Arsenal")
        self.assertEqual(matchday["final_score"], {"team": 3, "opponent": 0})
        self.assertNotIn("kickoff_utc", matchday)

    def test_idle_with_next_fixture(self):
        scoreboard = {"events": []}
        upcoming = {
            "events": [
                {
                    "date": "2026-08-30T14:00Z",
                    "competitions": [
                        {
                            "status": {"type": {"state": "pre"}},
                            "competitors": [
                                {"homeAway": "home", "team": LIVERPOOL},
                                {"homeAway": "away", "team": MAN_CITY},
                            ],
                        }
                    ],
                }
            ]
        }
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)

        result = determine_mode(scoreboard, upcoming_scoreboard_data=upcoming, now=now)

        self.assertEqual(result["mode"], "idle")
        next_fixture = result["idle"]["next_fixture"]
        self.assertEqual(next_fixture["opponent"], "Manchester City")
        self.assertEqual(next_fixture["kickoff_utc"], "2026-08-30T14:00Z")
        self.assertEqual(next_fixture["home_away"], "home")

    def test_idle_with_no_upcoming_scoreboard_data(self):
        result = determine_mode({"events": []}, upcoming_scoreboard_data=None)

        self.assertEqual(result["mode"], "idle")
        self.assertIsNone(result["idle"]["next_fixture"]["opponent"])

    def test_idle_ignores_past_fixtures_in_range(self):
        scoreboard = {"events": []}
        upcoming = {
            "events": [
                {
                    "date": "2026-08-23T15:30Z",
                    "competitions": [
                        {
                            "status": {"type": {"state": "post"}},
                            "competitors": [
                                {"homeAway": "away", "team": LIVERPOOL},
                                {"homeAway": "home", "team": {"id": "361", "displayName": "Newcastle United"}},
                            ],
                        }
                    ],
                }
            ]
        }
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)

        result = determine_mode(scoreboard, upcoming_scoreboard_data=upcoming, now=now)

        self.assertEqual(result["mode"], "idle")
        self.assertIsNone(result["idle"]["next_fixture"]["opponent"])

    def test_idle_skips_non_pre_events_within_the_range(self):
        # The forward-looking range can include a match that's already live
        # or finished (e.g. a boundary/timing edge case); only "pre" fixtures
        # should ever be picked as the next fixture.
        scoreboard = {"events": []}
        upcoming = {
            "events": [
                {
                    "date": "2026-08-27T19:00Z",
                    "competitions": [
                        {
                            "status": {"type": {"state": "in"}},
                            "competitors": [
                                {"homeAway": "home", "team": LIVERPOOL},
                                {"homeAway": "away", "team": EVERTON},
                            ],
                        }
                    ],
                },
                {
                    "date": "2026-08-30T14:00Z",
                    "competitions": [
                        {
                            "status": {"type": {"state": "pre"}},
                            "competitors": [
                                {"homeAway": "away", "team": LIVERPOOL},
                                {"homeAway": "home", "team": MAN_CITY},
                            ],
                        }
                    ],
                },
            ]
        }
        now = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)

        result = determine_mode(scoreboard, upcoming_scoreboard_data=upcoming, now=now)

        next_fixture = result["idle"]["next_fixture"]
        self.assertEqual(next_fixture["opponent"], "Manchester City")

    def test_mode_detection_works_for_a_non_liverpool_team(self):
        # Proves determine_mode isn't secretly Liverpool-specific: track
        # Arsenal (359) instead of the default team_id, using a payload
        # where Arsenal — not Liverpool — is the "team" competitor.
        competition = {
            "date": "2026-08-27T14:00Z",
            "status": {
                "displayClock": "34'",
                "period": 1,
                "type": {"state": "in", "shortDetail": "1st Half"},
            },
            "competitors": [
                {"homeAway": "home", "team": ARSENAL, "score": "1"},
                {"homeAway": "away", "team": EVERTON, "score": "0"},
            ],
        }
        result = determine_mode(_scoreboard_with(competition), team_id="359")

        self.assertEqual(result["mode"], "live")
        live = result["live"]
        self.assertEqual(live["opponent"], "Everton")
        self.assertEqual(live["home_away"], "home")
        self.assertEqual(live["score"], {"team": 1, "opponent": 0})

        # Same payload, default team_id (Liverpool) -> Liverpool isn't in
        # this match at all, so it's idle instead of live.
        idle_result = determine_mode(_scoreboard_with(competition))
        self.assertEqual(idle_result["mode"], "idle")

    def test_build_ticker_document_adds_timestamp(self):
        document = build_ticker_document({"mode": "idle", "idle": {}})
        self.assertIn("generated_at", document)
        self.assertTrue(document["generated_at"].endswith("Z"))


class TableSliceFromStandingsTests(unittest.TestCase):
    def _seven_team_standings(self):
        teams = [
            ({"id": "331", "displayName": "Brighton"}, 1, 3, 9, 6),
            ({"id": "359", "displayName": "Arsenal"}, 2, 3, 7, 5),
            ({"id": "337", "displayName": "Brentford"}, 3, 3, 6, 3),
            (LIVERPOOL, 4, 3, 6, 2),
            ({"id": "368", "displayName": "Everton"}, 5, 3, 5, 1),
            ({"id": "382", "displayName": "Manchester City"}, 6, 3, 4, 0),
            ({"id": "361", "displayName": "Newcastle United"}, 7, 3, 3, -2),
        ]
        entries = [_standings_entry(*team) for team in teams]
        return _standings_with(entries)

    def test_returns_team_plus_context_either_side(self):
        table = table_slice_from_standings(self._seven_team_standings(), "364")

        self.assertEqual(len(table), 5)  # 2 above + team + 2 below
        self.assertEqual(
            [row["team"] for row in table],
            ["Arsenal", "Brentford", "Liverpool", "Everton", "Manchester City"],
        )
        liverpool_row = table[2]
        self.assertEqual(liverpool_row["position"], 4)
        self.assertEqual(liverpool_row["played"], 3)
        self.assertEqual(liverpool_row["points"], 6)
        self.assertEqual(liverpool_row["goal_difference"], 2)
        self.assertTrue(liverpool_row["is_team"])
        self.assertFalse(table[0]["is_team"])

    def test_clamps_at_top_of_table(self):
        # Brighton is 1st — there's no "2 above" to include, should just
        # clamp rather than error or wrap around.
        table = table_slice_from_standings(self._seven_team_standings(), "331")

        self.assertEqual(len(table), 3)  # team + 2 below only
        self.assertEqual(table[0]["team"], "Brighton")
        self.assertTrue(table[0]["is_team"])

    def test_team_not_found_returns_empty_list(self):
        # Newly promoted / not yet listed / unexpected shape - must not
        # crash, just degrade to an empty table.
        table = table_slice_from_standings(self._seven_team_standings(), "999999")
        self.assertEqual(table, [])

    def test_missing_standings_data_returns_empty_list(self):
        self.assertEqual(table_slice_from_standings(None, "364"), [])
        self.assertEqual(table_slice_from_standings({}, "364"), [])

    def test_malformed_standings_shape_returns_empty_list_not_crash(self):
        self.assertEqual(table_slice_from_standings({"children": "nope"}, "364"), [])
        self.assertEqual(
            table_slice_from_standings({"children": [{"standings": None}]}, "364"), []
        )


class HeadlinesFromRssTests(unittest.TestCase):
    def _feed(self, titles):
        items = "".join(f"<item><title>{title}</title></item>" for title in titles)
        return (
            "<?xml version='1.0'?><rss><channel>"
            f"<title>BBC Sport</title>{items}"
            "</channel></rss>"
        )

    def test_returns_up_to_limit_general_headlines(self):
        titles = [f"Headline {i}" for i in range(8)]
        headlines = headlines_from_rss(self._feed(titles))

        self.assertEqual(len(headlines), 5)
        self.assertEqual(headlines, titles[:5])

    def test_team_headlines_surface_first(self):
        titles = [
            "Arsenal beat Chelsea",
            "Liverpool close in on deal for winger",
            "Transfer news roundup",
            "Villa sign new midfielder",
            "Liverpool held to draw",
            "Everton appoint new manager",
        ]
        headlines = headlines_from_rss(
            self._feed(titles), team_display_name="Liverpool", limit=4
        )

        self.assertEqual(
            headlines,
            [
                "Liverpool close in on deal for winger",
                "Liverpool held to draw",
                "Arsenal beat Chelsea",
                "Transfer news roundup",
            ],
        )

    def test_general_headlines_fill_remaining_slots_when_team_short(self):
        # Only one team-specific headline exists; the rest of the slots
        # should still fill with general news, not be left empty.
        titles = ["Liverpool sign new keeper", "General story A", "General story B"]
        headlines = headlines_from_rss(
            self._feed(titles), team_display_name="Liverpool", limit=3
        )

        self.assertEqual(len(headlines), 3)
        self.assertEqual(headlines[0], "Liverpool sign new keeper")

    def test_case_insensitive_team_match(self):
        titles = ["LIVERPOOL win again", "Other news"]
        headlines = headlines_from_rss(
            self._feed(titles), team_display_name="liverpool", limit=2
        )
        self.assertEqual(headlines[0], "LIVERPOOL win again")

    def test_empty_feed_returns_empty_list(self):
        self.assertEqual(headlines_from_rss(None), [])
        self.assertEqual(headlines_from_rss(""), [])

    def test_malformed_xml_returns_empty_list_not_crash(self):
        self.assertEqual(headlines_from_rss("<rss><channel><item>not closed"), [])
        self.assertEqual(headlines_from_rss("this is not xml at all"), [])

    def test_feed_with_no_items_returns_empty_list(self):
        empty_feed = "<?xml version='1.0'?><rss><channel><title>Empty</title></channel></rss>"
        self.assertEqual(headlines_from_rss(empty_feed), [])


class IdleModeTableAndHeadlinesIntegrationTests(unittest.TestCase):
    def test_idle_payload_wires_table_and_headlines_together(self):
        standings = _standings_with(
            [
                _standings_entry(ARSENAL, 1, 3, 9, 6),
                _standings_entry(LIVERPOOL, 2, 3, 7, 5),
                _standings_entry(EVERTON, 3, 3, 6, 3),
            ]
        )
        feed = (
            "<?xml version='1.0'?><rss><channel>"
            "<item><title>Liverpool eye January move</title></item>"
            "<item><title>General transfer roundup</title></item>"
            "</channel></rss>"
        )

        result = determine_mode(
            {"events": []},
            standings_data=standings,
            headlines_xml=feed,
        )

        self.assertEqual(result["mode"], "idle")
        self.assertEqual(len(result["idle"]["table"]), 3)
        self.assertTrue(
            any(row["is_team"] and row["team"] == "Liverpool" for row in result["idle"]["table"])
        )
        self.assertEqual(
            result["idle"]["headlines"][0], "Liverpool eye January move"
        )


class PollIntervalTests(unittest.TestCase):
    def test_interval_ordering_matches_urgency(self):
        # live should poll fastest, idle slowest.
        self.assertLess(POLL_INTERVAL_LIVE, POLL_INTERVAL_MATCHDAY)
        self.assertLess(POLL_INTERVAL_MATCHDAY, POLL_INTERVAL_IDLE)

    def test_mode_lookup_matches_spec(self):
        self.assertEqual(POLL_INTERVAL_BY_MODE["live"], 60)
        self.assertEqual(POLL_INTERVAL_BY_MODE["matchday"], 300)
        self.assertEqual(POLL_INTERVAL_BY_MODE["idle"], 900)


class RunOnceRequestedTests(unittest.TestCase):
    def test_true_when_once_flag_passed(self):
        with mock.patch("sys.argv", ["poller.py", "--once"]):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RUN_ONCE", None)
                self.assertTrue(_run_once_requested())

    def test_true_when_run_once_env_set(self):
        with mock.patch("sys.argv", ["poller.py"]):
            with mock.patch.dict(os.environ, {"RUN_ONCE": "true"}):
                self.assertTrue(_run_once_requested())

    def test_run_once_env_is_case_insensitive_and_accepts_1(self):
        with mock.patch("sys.argv", ["poller.py"]):
            with mock.patch.dict(os.environ, {"RUN_ONCE": "1"}):
                self.assertTrue(_run_once_requested())
            with mock.patch.dict(os.environ, {"RUN_ONCE": "TRUE"}):
                self.assertTrue(_run_once_requested())

    def test_false_by_default(self):
        with mock.patch("sys.argv", ["poller.py"]):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RUN_ONCE", None)
                self.assertFalse(_run_once_requested())


if __name__ == "__main__":
    unittest.main()
