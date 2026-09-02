// team-ticker-view fetches ticker.json from a running team-ticker backend
// and prints a single formatted page to stdout — a terminal equivalent of
// the Matrix Portal display, not a full interactive TUI. Run it again (or
// alias it, or wrap it in `watch`) for a fresh look.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/mikelawton/team-ticker-view/internal/config"
	"github.com/mikelawton/team-ticker-view/internal/ticker"
	"github.com/mikelawton/team-ticker-view/internal/ui"
)

const version = "0.1.0"

func main() {
	var (
		urlFlag = flag.String("url", "", "URL of ticker.json — overrides any saved setting, just for this run")
		setURL  = flag.String("set-url", "", "save this URL as the default and exit (no fetch)")
		timeout = flag.Duration("timeout", 5*time.Second, "HTTP request timeout")
		showVer = flag.Bool("version", false, "print version and exit")
	)
	flag.Parse()

	if *showVer {
		fmt.Println(version)
		return
	}

	if *setURL != "" {
		if err := config.SaveURL(*setURL); err != nil {
			fmt.Fprintln(os.Stderr, "team-ticker-view:", err)
			os.Exit(1)
		}
		path, _ := config.Path()
		fmt.Printf("Saved %s to %s\n", *setURL, path)
		return
	}

	url, err := resolveURL(*urlFlag)
	if err != nil {
		fmt.Fprintln(os.Stderr, "team-ticker-view:", err)
		os.Exit(1)
	}

	doc, err := ticker.Fetch(url, *timeout)
	if err != nil {
		fmt.Fprintln(os.Stderr, "team-ticker-view:", err)
		os.Exit(1)
	}

	fmt.Print(ui.Render(doc))
}

// resolveURL picks the ticker.json URL in order: the -url flag, then
// TICKER_URL in the environment, then the saved setting
// (~/.config/team-ticker-view/env). If none of those are set, it prompts
// once on stdin and saves the answer via config.SaveURL so future runs
// don't need to repeat it — mirrors nyt-term's first-run API key prompt.
func resolveURL(flagURL string) (string, error) {
	if flagURL != "" {
		return flagURL, nil
	}
	if envURL := os.Getenv("TICKER_URL"); envURL != "" {
		return envURL, nil
	}

	savedURL, err := config.LoadURL()
	if err != nil {
		return "", err
	}
	if savedURL != "" {
		return savedURL, nil
	}

	return promptForURL()
}

func promptForURL() (string, error) {
	fmt.Fprint(os.Stderr, "No ticker.json URL configured.\nEnter one now (e.g. http://lfc-ticker.home/ticker.json): ")

	reader := bufio.NewReader(os.Stdin)
	input, err := reader.ReadString('\n')
	if err != nil {
		return "", fmt.Errorf("reading URL from stdin: %w", err)
	}
	url := strings.TrimSpace(input)
	if url == "" {
		return "", fmt.Errorf("no URL given — pass -url, set TICKER_URL, or run with -set-url <url>")
	}

	if err := config.SaveURL(url); err != nil {
		return "", err
	}
	path, _ := config.Path()
	fmt.Fprintf(os.Stderr, "Saved to %s — future runs won't ask again.\n\n", path)

	return url, nil
}
