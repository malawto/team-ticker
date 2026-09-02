package config

import (
	"testing"
)

func TestSaveAndLoadURL(t *testing.T) {
	t.Setenv("HOME", t.TempDir())

	url, err := LoadURL()
	if err != nil {
		t.Fatalf("LoadURL (before save): %v", err)
	}
	if url != "" {
		t.Fatalf("LoadURL (before save) = %q, want empty", url)
	}

	if err := SaveURL("http://lfc-ticker.home/ticker.json"); err != nil {
		t.Fatalf("SaveURL: %v", err)
	}

	url, err = LoadURL()
	if err != nil {
		t.Fatalf("LoadURL (after save): %v", err)
	}
	if url != "http://lfc-ticker.home/ticker.json" {
		t.Errorf("LoadURL = %q, want the saved URL", url)
	}
}

func TestLoadURL_MissingFile(t *testing.T) {
	t.Setenv("HOME", t.TempDir())

	url, err := LoadURL()
	if err != nil {
		t.Fatalf("LoadURL: %v", err)
	}
	if url != "" {
		t.Errorf("LoadURL = %q, want empty for missing config", url)
	}
}
