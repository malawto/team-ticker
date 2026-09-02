// Package ticker decodes and fetches the team-ticker backend's ticker.json
// document — see the top-level README's "ticker.json schema" section for
// the authoritative shape. Field names/types here must track that schema.
package ticker

// Document is the full ticker.json payload. Exactly one of Live, Matchday,
// or Idle is populated, selected by Mode.
type Document struct {
	Mode        string    `json:"mode"`
	Live        *Live     `json:"live,omitempty"`
	Matchday    *Matchday `json:"matchday,omitempty"`
	Idle        *Idle     `json:"idle,omitempty"`
	GeneratedAt string    `json:"generated_at"`
}

type Score struct {
	Team     *int `json:"team"`
	Opponent *int `json:"opponent"`
}

type Live struct {
	Opponent     string `json:"opponent"`
	HomeAway     string `json:"home_away"`
	Score        Score  `json:"score"`
	Clock        string `json:"clock"`
	Period       *int   `json:"period"`
	StatusDetail string `json:"status_detail"`
}

type Matchday struct {
	Opponent   string `json:"opponent"`
	HomeAway   string `json:"home_away"`
	KickoffUTC string `json:"kickoff_utc,omitempty"`
	FinalScore *Score `json:"final_score,omitempty"`
}

type NextFixture struct {
	Opponent   *string `json:"opponent"`
	KickoffUTC *string `json:"kickoff_utc"`
	HomeAway   *string `json:"home_away"`
}

type TableRow struct {
	Team           string `json:"team"`
	Abbreviation   string `json:"abbreviation"`
	Position       int    `json:"position"`
	Played         int    `json:"played"`
	Points         int    `json:"points"`
	GoalDifference int    `json:"goal_difference"`
	IsTeam         bool   `json:"is_team"`
}

type Idle struct {
	NextFixture NextFixture `json:"next_fixture"`
	Table       []TableRow  `json:"table"`
	FullTable   []TableRow  `json:"full_table"`
	Headlines   []string    `json:"headlines"`
}
