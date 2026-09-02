#!/usr/bin/env bash
# Build a .deb package for team-ticker-view: just the binary, installed
# system-wide under /usr/bin. Unlike nyt-term's build-deb.sh, there's no
# desktop entry/icon here — this tool prints one page and exits, so
# there's no persistent app window for a launcher to point at.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PKG_NAME="team-ticker-view"
BIN_NAME="team-ticker-view"

die() {
  echo "Error: $*" >&2
  exit 1
}

for cmd in go dpkg-deb dpkg; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing required tool: $cmd"
done

ARCH="$(dpkg --print-architecture)"

echo "Building $BIN_NAME (CGO_ENABLED=0 for a dependency-free static binary)..."
CGO_ENABLED=0 go -C "$SCRIPT_DIR" build -o "$SCRIPT_DIR/$BIN_NAME" .

# The binary is the single source of truth for the version (see the
# `version` const in main.go) — read it back rather than keeping a
# separate copy here that could drift out of sync.
VERSION="$("$SCRIPT_DIR/$BIN_NAME" --version)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/bin"

install -m 755 "$SCRIPT_DIR/$BIN_NAME" "$STAGE/usr/bin/$BIN_NAME"

INSTALLED_SIZE_KB="$(du -sk "$STAGE/usr" | cut -f1)"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_SIZE_KB
Maintainer: Mike Lawton <mikelawton@gmail.com>
Description: Terminal snapshot viewer for team-ticker
 Fetches ticker.json from a running team-ticker backend and prints a
 single formatted page to stdout — live score, matchday, or next
 fixture/table/headlines — a terminal equivalent of the Matrix Portal
 display, not an interactive TUI.
EOF

OUT="$SCRIPT_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo "Built $OUT"
echo "Install with: sudo apt install $OUT"
