// team-ticker-view fetches ticker.json from a running team-ticker backend
// and prints a single formatted page to stdout — a terminal equivalent of
// the Matrix Portal display, not a full interactive TUI. Run it again (or
// alias it, or wrap it in `watch`) for a fresh look.
package main

import (
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/mikelawton/team-ticker-view/internal/ticker"
	"github.com/mikelawton/team-ticker-view/internal/ui"
)

const version = "0.1.0"

func main() {
	var (
		url     = flag.String("url", os.Getenv("TICKER_URL"), "URL of ticker.json (or set TICKER_URL)")
		timeout = flag.Duration("timeout", 5*time.Second, "HTTP request timeout")
		showVer = flag.Bool("version", false, "print version and exit")
	)
	flag.Parse()

	if *showVer {
		fmt.Println(version)
		return
	}

	if *url == "" {
		fmt.Fprintln(os.Stderr, "team-ticker-view: no ticker.json URL given — pass -url or set TICKER_URL")
		fmt.Fprintln(os.Stderr, "  e.g. team-ticker-view -url http://lfc-ticker.home/ticker.json")
		os.Exit(1)
	}

	doc, err := ticker.Fetch(*url, *timeout)
	if err != nil {
		fmt.Fprintln(os.Stderr, "team-ticker-view:", err)
		os.Exit(1)
	}

	fmt.Print(ui.Render(doc))
}
