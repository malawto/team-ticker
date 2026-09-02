package ticker

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestFetch_Idle(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{
			"mode": "idle",
			"idle": {
				"next_fixture": {"opponent": "Nottingham Forest", "kickoff_utc": "2026-08-29T11:30Z", "home_away": "home"},
				"table": [],
				"full_table": [{"team": "Liverpool", "abbreviation": "LIV", "position": 10, "played": 1, "points": 1, "goal_difference": 0, "is_team": true}],
				"headlines": ["Some headline"]
			},
			"generated_at": "2026-08-28T21:17:18Z"
		}`))
	}))
	defer srv.Close()

	doc, err := Fetch(srv.URL, time.Second)
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if doc.Mode != "idle" {
		t.Fatalf("Mode = %q, want idle", doc.Mode)
	}
	if doc.Idle == nil {
		t.Fatal("Idle is nil")
	}
	if got := *doc.Idle.NextFixture.Opponent; got != "Nottingham Forest" {
		t.Errorf("NextFixture.Opponent = %q", got)
	}
	if len(doc.Idle.FullTable) != 1 || !doc.Idle.FullTable[0].IsTeam {
		t.Errorf("FullTable = %+v", doc.Idle.FullTable)
	}
}

func TestFetch_Live(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{
			"mode": "live",
			"live": {
				"opponent": "Arsenal", "home_away": "away",
				"score": {"team": 2, "opponent": 1},
				"clock": "67'", "period": 2, "status_detail": "2nd Half"
			},
			"generated_at": "2026-08-28T21:17:18Z"
		}`))
	}))
	defer srv.Close()

	doc, err := Fetch(srv.URL, time.Second)
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if doc.Live == nil {
		t.Fatal("Live is nil")
	}
	if *doc.Live.Score.Team != 2 || *doc.Live.Score.Opponent != 1 {
		t.Errorf("Score = %+v", doc.Live.Score)
	}
}

func TestFetch_NonOKStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	_, err := Fetch(srv.URL, time.Second)
	if err == nil {
		t.Fatal("expected error for 404 response")
	}
	if !strings.Contains(err.Error(), "404") {
		t.Errorf("error = %v, want mention of 404", err)
	}
}

func TestFetch_InvalidJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`not json`))
	}))
	defer srv.Close()

	_, err := Fetch(srv.URL, time.Second)
	if err == nil {
		t.Fatal("expected error for invalid JSON")
	}
}
