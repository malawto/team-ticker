package ui

import "github.com/charmbracelet/lipgloss"

var (
	borderColor = lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"}

	liveColor     = lipgloss.AdaptiveColor{Light: "#B00020", Dark: "#FF5555"}
	matchdayColor = lipgloss.AdaptiveColor{Light: "#946200", Dark: "#F5C542"}
	idleColor     = lipgloss.AdaptiveColor{Light: "#0060DF", Dark: "#7AA2F7"}

	fgColor   = lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}
	dimColor  = lipgloss.AdaptiveColor{Light: "#666666", Dark: "#888888"}
	teamColor = lipgloss.AdaptiveColor{Light: "#0A6B0A", Dark: "#5FD75F"}

	bannerStyle = lipgloss.NewStyle().
			Bold(true).
			Padding(0, 2)

	panelStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(borderColor).
			Padding(1, 2)

	headingStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(fgColor)

	dimStyle = lipgloss.NewStyle().
			Foreground(dimColor)

	scoreStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(fgColor)

	teamRowStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(teamColor)

	errorStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(liveColor)

	warnStyle = lipgloss.NewStyle().
			Foreground(matchdayColor)
)
