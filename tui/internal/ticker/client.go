package ticker

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Fetch retrieves and decodes ticker.json from url (the same plain-HTTP
// endpoint the Matrix Portal firmware polls — see secrets.py.example's
// ticker_url). No auth, no retries: this is a one-shot CLI, not a
// long-running poller, so a failure just surfaces as a single error.
func Fetch(url string, timeout time.Duration) (*Document, error) {
	client := &http.Client{Timeout: timeout}

	resp, err := client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("fetching %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fetching %s: unexpected status %s", url, resp.Status)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading response from %s: %w", url, err)
	}

	var doc Document
	if err := json.Unmarshal(body, &doc); err != nil {
		return nil, fmt.Errorf("decoding ticker.json from %s: %w", url, err)
	}

	return &doc, nil
}
