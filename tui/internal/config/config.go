// Package config persists team-ticker-view's settings across runs, the
// same way nyt-term persists its API key: a small file under ~/.config,
// owner-only permissions, no encryption (there's nothing secret in a
// ticker.json URL — this is just to keep the two sibling projects
// consistent).
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Path is where settings are read from and written to:
// ~/.config/team-ticker-view/env, containing a single TICKER_URL=... line.
func Path() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("could not determine home directory: %w", err)
	}
	return filepath.Join(home, ".config", "team-ticker-view", "env"), nil
}

// LoadURL reads TICKER_URL from Path. Returns "" (no error) if the config
// file doesn't exist yet — that's the normal state before first run.
func LoadURL() (string, error) {
	path, err := Path()
	if err != nil {
		return "", err
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", fmt.Errorf("reading %s: %w", path, err)
	}

	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "TICKER_URL=") {
			continue
		}
		url := strings.TrimPrefix(line, "TICKER_URL=")
		return strings.Trim(url, `"'`), nil
	}

	return "", nil
}

// SaveURL writes url to Path, creating the containing directory if needed.
func SaveURL(url string) error {
	path, err := Path()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("creating config directory: %w", err)
	}
	if err := os.WriteFile(path, []byte("TICKER_URL="+url+"\n"), 0o600); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	return nil
}
