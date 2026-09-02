package ui

import (
	"fmt"
	"strings"
	"time"

	"github.com/mikelawton/team-ticker-view/internal/ticker"
)

// staleAfter flags the page as stale once ticker.json is older than this.
// The backend's slowest poll interval is 15m (idle mode) — see
// POLL_INTERVAL_BY_MODE in poller.py — so anything past ~2x that plus
// margin means the poller likely isn't running, not just between cycles.
const staleAfter = 35 * time.Minute

// timeLayouts covers the two generated_at/kickoff_utc shapes poller.py
// emits: with seconds (generated_at) and without (kickoff_utc, e.g.
// "2026-08-29T11:30Z" — see next_fixture_from_scoreboard_range).
var timeLayouts = []string{time.RFC3339, "2006-01-02T15:04Z"}

func parseUTC(s string) (time.Time, bool) {
	for _, layout := range timeLayouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

// Render renders the full single-page view of a ticker.json document.
func Render(doc *ticker.Document) string {
	var b strings.Builder

	b.WriteString(banner(doc.Mode))
	b.WriteString("\n\n")

	switch doc.Mode {
	case "live":
		if doc.Live != nil {
			b.WriteString(renderLive(doc.Live))
		}
	case "matchday":
		if doc.Matchday != nil {
			b.WriteString(renderMatchday(doc.Matchday))
		}
	case "idle":
		if doc.Idle != nil {
			b.WriteString(renderIdle(doc.Idle))
		}
	default:
		b.WriteString(errorStyle.Render(fmt.Sprintf("unrecognized mode %q in ticker.json", doc.Mode)))
		b.WriteString("\n")
	}

	b.WriteString("\n")
	b.WriteString(footer(doc.GeneratedAt))
	b.WriteString("\n")

	return b.String()
}

func banner(mode string) string {
	switch mode {
	case "live":
		return bannerStyle.Foreground(liveColor).Render("● LIVE")
	case "matchday":
		return bannerStyle.Foreground(matchdayColor).Render("○ MATCHDAY")
	case "idle":
		return bannerStyle.Foreground(idleColor).Render("TEAM TICKER")
	default:
		return bannerStyle.Foreground(dimColor).Render(strings.ToUpper(mode))
	}
}

func homeAwayLabel(homeAway string) string {
	switch homeAway {
	case "home":
		return "vs"
	case "away":
		return "at"
	default:
		return "vs/at"
	}
}

func renderLive(l *ticker.Live) string {
	var b strings.Builder

	b.WriteString(fmt.Sprintf("%s %s\n\n", homeAwayLabel(l.HomeAway), headingStyle.Render(l.Opponent)))

	teamScore, oppScore := "–", "–"
	if l.Score.Team != nil {
		teamScore = fmt.Sprintf("%d", *l.Score.Team)
	}
	if l.Score.Opponent != nil {
		oppScore = fmt.Sprintf("%d", *l.Score.Opponent)
	}
	b.WriteString(scoreStyle.Render(fmt.Sprintf("%s — %s", teamScore, oppScore)))
	b.WriteString("\n\n")

	detail := l.StatusDetail
	if l.Clock != "" {
		if detail != "" {
			detail = fmt.Sprintf("%s, %s", l.Clock, detail)
		} else {
			detail = l.Clock
		}
	}
	if detail != "" {
		b.WriteString(dimStyle.Render(detail))
		b.WriteString("\n")
	}

	return b.String()
}

func renderMatchday(m *ticker.Matchday) string {
	var b strings.Builder

	b.WriteString(fmt.Sprintf("%s %s\n\n", homeAwayLabel(m.HomeAway), headingStyle.Render(m.Opponent)))

	if m.FinalScore != nil {
		teamScore, oppScore := "–", "–"
		if m.FinalScore.Team != nil {
			teamScore = fmt.Sprintf("%d", *m.FinalScore.Team)
		}
		if m.FinalScore.Opponent != nil {
			oppScore = fmt.Sprintf("%d", *m.FinalScore.Opponent)
		}
		b.WriteString(scoreStyle.Render(fmt.Sprintf("Final: %s — %s", teamScore, oppScore)))
		b.WriteString("\n")
		return b.String()
	}

	if m.KickoffUTC != "" {
		if kt, ok := parseUTC(m.KickoffUTC); ok {
			b.WriteString(dimStyle.Render("Kick-off: " + kt.Local().Format("Mon Jan 2, 3:04 PM MST")))
			b.WriteString("\n")
		} else {
			b.WriteString(dimStyle.Render("Kick-off: " + m.KickoffUTC + " UTC"))
			b.WriteString("\n")
		}
	}

	return b.String()
}

func renderIdle(idle *ticker.Idle) string {
	var b strings.Builder

	b.WriteString(headingStyle.Render("Next fixture"))
	b.WriteString("\n")
	if idle.NextFixture.Opponent == nil || *idle.NextFixture.Opponent == "" {
		b.WriteString(dimStyle.Render("None scheduled"))
		b.WriteString("\n")
	} else {
		homeAway := "unknown"
		if idle.NextFixture.HomeAway != nil {
			homeAway = *idle.NextFixture.HomeAway
		}
		line := fmt.Sprintf("%s %s", homeAwayLabel(homeAway), *idle.NextFixture.Opponent)
		if idle.NextFixture.KickoffUTC != nil {
			if kt, ok := parseUTC(*idle.NextFixture.KickoffUTC); ok {
				line += dimStyle.Render(" — " + kt.Local().Format("Mon Jan 2, 3:04 PM MST"))
			}
		}
		b.WriteString(line)
		b.WriteString("\n")
	}
	b.WriteString("\n")

	table := idle.FullTable
	if len(table) == 0 {
		table = idle.Table
	}
	if len(table) > 0 {
		b.WriteString(headingStyle.Render("Table"))
		b.WriteString("\n")
		b.WriteString(renderTable(table))
		b.WriteString("\n")
	}

	if len(idle.Headlines) > 0 {
		b.WriteString(headingStyle.Render("Headlines"))
		b.WriteString("\n")
		for _, h := range idle.Headlines {
			b.WriteString(dimStyle.Render("• ") + h)
			b.WriteString("\n")
		}
	}

	return b.String()
}

func renderTable(rows []ticker.TableRow) string {
	var b strings.Builder
	for _, row := range rows {
		line := fmt.Sprintf("%3d  %-24s P%-3d  Pts%-3d  GD%+d",
			row.Position, row.Team, row.Played, row.Points, row.GoalDifference)
		if row.IsTeam {
			b.WriteString(teamRowStyle.Render(line))
		} else {
			b.WriteString(line)
		}
		b.WriteString("\n")
	}
	return b.String()
}

func footer(generatedAt string) string {
	t, ok := parseUTC(generatedAt)
	if !ok {
		return dimStyle.Render("updated: unknown")
	}

	age := time.Since(t)
	line := "updated " + roundDuration(age)
	if age > staleAfter {
		return warnStyle.Render(line + " — poller may be stuck")
	}
	return dimStyle.Render(line)
}

func roundDuration(d time.Duration) string {
	if d < time.Minute {
		return "just now"
	}
	if d < time.Hour {
		return fmt.Sprintf("%dm ago", int(d.Minutes()))
	}
	return fmt.Sprintf("%dh%dm ago", int(d.Hours()), int(d.Minutes())%60)
}
