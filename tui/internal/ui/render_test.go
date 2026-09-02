package ui

import (
	"strings"
	"testing"
	"time"

	"github.com/mikelawton/team-ticker-view/internal/ticker"
)

func intPtr(i int) *int       { return &i }
func strPtr(s string) *string { return &s }

func TestRender_Live(t *testing.T) {
	doc := &ticker.Document{
		Mode: "live",
		Live: &ticker.Live{
			Opponent:     "Arsenal",
			HomeAway:     "away",
			Score:        ticker.Score{Team: intPtr(2), Opponent: intPtr(1)},
			Clock:        "67'",
			StatusDetail: "2nd Half",
		},
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
	}

	out := Render(doc)
	for _, want := range []string{"LIVE", "Arsenal", "2", "1", "67'", "2nd Half", "updated"} {
		if !strings.Contains(out, want) {
			t.Errorf("Render output missing %q:\n%s", want, out)
		}
	}
}

func TestRender_MatchdayUpcoming(t *testing.T) {
	doc := &ticker.Document{
		Mode: "matchday",
		Matchday: &ticker.Matchday{
			Opponent:   "Everton",
			HomeAway:   "home",
			KickoffUTC: "2026-08-29T11:30Z",
		},
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
	}

	out := Render(doc)
	for _, want := range []string{"MATCHDAY", "Everton", "Kick-off"} {
		if !strings.Contains(out, want) {
			t.Errorf("Render output missing %q:\n%s", want, out)
		}
	}
}

func TestRender_MatchdayFinal(t *testing.T) {
	doc := &ticker.Document{
		Mode: "matchday",
		Matchday: &ticker.Matchday{
			Opponent:   "Everton",
			HomeAway:   "home",
			FinalScore: &ticker.Score{Team: intPtr(3), Opponent: intPtr(0)},
		},
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
	}

	out := Render(doc)
	if !strings.Contains(out, "Final: 3 — 0") {
		t.Errorf("Render output missing final score:\n%s", out)
	}
}

func TestRender_Idle(t *testing.T) {
	doc := &ticker.Document{
		Mode: "idle",
		Idle: &ticker.Idle{
			NextFixture: ticker.NextFixture{
				Opponent:   strPtr("Nottingham Forest"),
				KickoffUTC: strPtr("2026-08-29T11:30Z"),
				HomeAway:   strPtr("home"),
			},
			FullTable: []ticker.TableRow{
				{Team: "Manchester City", Abbreviation: "MNC", Position: 1, Played: 2, Points: 6, GoalDifference: 4},
				{Team: "Liverpool", Abbreviation: "LIV", Position: 10, Played: 1, Points: 1, GoalDifference: 0, IsTeam: true},
			},
			Headlines: []string{"Some transfer headline"},
		},
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
	}

	out := Render(doc)
	for _, want := range []string{"TEAM TICKER", "Nottingham Forest", "Manchester City", "Liverpool", "Some transfer headline"} {
		if !strings.Contains(out, want) {
			t.Errorf("Render output missing %q:\n%s", want, out)
		}
	}
}

func TestRender_IdleNoFixture(t *testing.T) {
	doc := &ticker.Document{
		Mode:        "idle",
		Idle:        &ticker.Idle{},
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
	}

	out := Render(doc)
	if !strings.Contains(out, "None scheduled") {
		t.Errorf("Render output missing fallback text:\n%s", out)
	}
}

func TestFooter_Stale(t *testing.T) {
	old := time.Now().UTC().Add(-time.Hour).Format(time.RFC3339)
	out := footer(old)
	if !strings.Contains(out, "poller may be stuck") {
		t.Errorf("footer() = %q, want stale warning", out)
	}
}

func TestFooter_Fresh(t *testing.T) {
	recent := time.Now().UTC().Format(time.RFC3339)
	out := footer(recent)
	if strings.Contains(out, "poller may be stuck") {
		t.Errorf("footer() = %q, unexpected stale warning", out)
	}
}

func TestFooter_UnparseableGeneratedAt(t *testing.T) {
	out := footer("not-a-timestamp")
	if !strings.Contains(out, "unknown") {
		t.Errorf("footer() = %q, want unknown-time fallback", out)
	}
}
