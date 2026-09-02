# team-ticker

A generic sports ticker: a Python backend that polls ESPN and BBC Sport for
a configured team's fixture status and league news, and CircuitPython
firmware for an Adafruit Matrix Portal M4 LED matrix that displays it.

No team or league is hardcoded — the reference/default instance is
Liverpool FC / the English Premier League, but any team ESPN tracks works
by changing two environment variables.

## Architecture

```
poller.py (Docker container, polls every 60s-15m)
    -> writes ticker.json to a bind-mounted volume
        -> nginx serves it directly as a static file, both:
            - HTTPS (mkcert cert)   — for browsers/normal .home traffic
            - plain HTTP, no redirect — for the Matrix Portal, which can't
              install a custom CA on its ESP32 co-processor
                -> Matrix Portal M4 polls the HTTP copy and renders it
                -> tui/'s team-ticker-view polls the same HTTP copy and
                   prints a formatted snapshot to a terminal
```

The backend and its consumers never talk to each other directly —
`ticker.json` on disk is the entire interface. Nothing about a given
display (WiFi, polling, rendering) depends on how that file got there, or
on what else is reading it.

## Repository layout

```
backend/     Docker container + poller.py — fetches data, writes ticker.json
firmware/    CircuitPython code for the Matrix Portal display
tui/         Go CLI — prints a formatted single-page snapshot of ticker.json
```

## Configuration reference

Set via `backend/.env` (copy from `backend/.env.example`):

| Variable | Required | Default | Notes |
|---|---|---|---|
| `TEAM_ID` | No | `364` (Liverpool FC) | ESPN's numeric team id. Find it by opening `https://site.api.espn.com/apis/site/v2/sports/soccer/<LEAGUE>/scoreboard` and reading a competitor's `team.id`. |
| `LEAGUE` | No | `eng.1` | ESPN's league slug. |
| `LOCAL_TZ` | No | `UTC` | IANA timezone name (e.g. `America/New_York`) `matchday` is judged against — a fixture is `matchday` when its kickoff falls on today's calendar date *in this timezone*, not UTC's. |
| `PUID` / `PGID` | No | `1000` / `1000` | UID/GID the container runs as — must match the host user that owns the bind-mounted `data/` directory. Check with `id <your-user>`. |
| `TICKER_JSON_PATH` | No (container-internal) | `/data/ticker.json` | Set in the Dockerfile, not `.env` — where `ticker.json` is written inside the container. Only relevant if you change the Dockerfile/compose volume layout. |
| `KUMA_PUSH_URL` | No | unset | Push-monitor URL (Uptime Kuma or compatible). See **Monitoring** below. |

`TEAM_ID`/`LEAGUE`/`LOCAL_TZ` fail fast (the poller logs and exits) if set to
something that isn't a plausible id/slug/IANA timezone name — better than
silently polling the wrong team, or misjudging "matchday", forever.

## Backend setup

Requirements: Docker and Docker Compose.

```sh
cd backend
cp .env.example .env
# edit .env — see Configuration reference above
docker compose up -d --build                              # local/dev
docker compose -f docker-compose.prod.yml up -d --build    # production
```

`ticker.json` lands in the bind-mounted `data/` directory. Serve that
directory (or just the file) over plain HTTP for the display — see
**nginx / deployment notes** below for exactly how this project does it.

Poll interval adapts to the mode just written: 60s while a match is live,
5 minutes on matchday, 15 minutes idle.

### Running tests

```sh
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest tests.test_poller
```

## ESPN/BBC API quirks

These cost real debugging time to work out and are easy to "fix" back to
wrong later, so they're pinned down here rather than left as tribal
knowledge:

- **Standings live at a different path than you'd guess.** The scoreboard
  endpoint's sibling path, `apis/site/v2/.../standings`, returns an empty
  `{}` for at least `eng.1`. The endpoint that actually returns standings
  data is `apis/v2/.../standings` — no `site/` segment. See
  `STANDINGS_URL_TEMPLATE` in `poller.py`.
- **The team "schedule" endpoint only ever returns already-played
  fixtures** — confirmed dead end, `?season=` and `?half=` params don't
  change that. Getting the *next* fixture instead requires querying the
  **scoreboard** endpoint with a forward-looking `dates=YYYYMMDD-YYYYMMDD`
  range param (see `fetch_upcoming_scoreboard`), not the schedule endpoint
  at all.
- **A claimed `curl`-vs-`requests` blocking difference did not reproduce.**
  Earlier notes on this project described `curl` getting blocked (403,
  Akamai TLS fingerprinting) against these ESPN endpoints while Python's
  `requests` worked fine. Retested live against all three endpoints
  (scoreboard, standings, BBC RSS) immediately before writing this section:
  plain `curl` returned `200` consistently, no blocking observed. Not
  removing the possibility this was real under some other condition (a
  different `curl` version, a flagged IP, Akamai's detection changing
  over time) — just noting it isn't currently reproducible, so don't trust
  it as a debugging shortcut without reverifying.

## Docker / deployment notes

- **`user: "${PUID:-1000}:${PGID:-1000}"` in compose, not baked into the
  image or handled by an entrypoint privilege-drop script.** The
  Dockerfile's `ENTRYPOINT ["python", "poller.py"]` is exec-form with no
  shell or `su`/`gosu` wrapper, so `python` runs as PID 1 directly, already
  running as the UID/GID compose assigned at container start. `docker stop`'s
  SIGTERM reaches `poller.py`'s own signal handler immediately — no signal
  proxying through an intermediate process needed. Baking a UID into the
  image, or dropping privilege at runtime via an entrypoint script, would
  both complicate that for no benefit.
- **Why `PUID`/`PGID` are configurable at all, not hardcoded**: the dev
  machine and the deploy host have different `mike` UID/GID
  (`1000:1000` vs `1000:100`). A UID baked in at build time would only be
  correct on one of them by coincidence.
- **nginx serves `ticker.json` directly as a static file** (`root
  .../data;` + `try_files $uri =404;`), not reverse-proxied — the container
  has no HTTP server of its own, it just writes a file. Two server blocks
  on the same host/port pattern used elsewhere in this homelab: HTTPS with
  a mkcert cert, and plain HTTP with **no redirect** to HTTPS (unlike every
  other `.home` site here) specifically because the Matrix Portal can't
  follow a redirect to a scheme it can't establish trust for.
- **`setfacl -m u:www-data:--x /home/mike` was required** on the deploy
  host. This was the first service there to have nginx read a file
  straight off disk under a user's home directory rather than reverse
  proxying to a container's own port — nginx (running as `www-data`) needs
  execute permission on every directory in the path down to the served
  file (`/home/mike/docker/lfc-ticker/data/ticker.json`), not just
  read permission on the file itself.

## `ticker.json` schema

Firmware only reads `next_fixture`, `full_table`, and `headlines` from
`idle` — `table` (a ±2-team window around your team) is additional data in
the payload not currently consumed by the reference firmware, useful if
you build a narrower display instead of the full vertical scroll.

<details>
<summary>Real example (idle mode, trimmed)</summary>

```json
{
  "mode": "idle",
  "idle": {
    "next_fixture": {
      "opponent": "Nottingham Forest",
      "kickoff_utc": "2026-08-29T11:30Z",
      "home_away": "home"
    },
    "table": [
      { "team": "Liverpool", "abbreviation": "LIV", "position": 10, "played": 1, "points": 1, "goal_difference": 0, "is_team": true }
    ],
    "full_table": [
      { "team": "Manchester City", "abbreviation": "MNC", "position": 1, "played": 2, "points": 6, "goal_difference": 4, "is_team": false }
    ],
    "headlines": [
      "What will Jackson bring to Villa with Watkins set for exit?"
    ]
  },
  "generated_at": "2026-08-28T21:17:18Z"
}
```

`mode` is `"live"` or `"matchday"` instead, with a differently-shaped
top-level key to match:

```json
{ "mode": "live", "live": {
  "opponent": "...", "home_away": "home",
  "score": { "team": 2, "opponent": 1 },
  "clock": "67'", "period": 2, "status_detail": "2nd Half"
}}
```

```json
{ "mode": "matchday", "matchday": {
  "opponent": "...", "home_away": "away",
  "kickoff_utc": "2026-08-29T11:30Z"
}}
```

`matchday` gets a `final_score` key instead of `kickoff_utc` once the match
has finished but before ESPN's data settles back to a normal fixture.

</details>

## Matrix Portal firmware

Hardware: an Adafruit Matrix Portal M4 driving a 64x32 HUB75 LED matrix
panel, running **CircuitPython 10.2.1**.

1. Install CircuitPython 10.2.1 on the board, then copy onto the
   `CIRCUITPY` drive:
   - `firmware/code.py` → `code.py`
   - The library bundle below → `lib/`

2. Copy `firmware/secrets.py.example` → `secrets.py` on `CIRCUITPY` and
   fill in:

   | Key | Required | Notes |
   |---|---|---|
   | `ssid` / `password` | Yes | Your WiFi network. |
   | `ticker_url` | Yes | Plain-HTTP URL to your backend's `ticker.json`. |
   | `utc_offset_minutes` | No | In minutes, not hours — exact for fractional-hour timezones. |
   | `timezone_label` | No | Label shown next to the converted local time, e.g. `"EDT"`. |

3. Save — CircuitPython auto-reloads and starts polling.

<details>
<summary>CircuitPython library bundle (traced from actual imports, CircuitPython 10.2.1)</summary>

`code.py` itself only directly imports `adafruit_display_text` and
`adafruit_matrixportal` — `adafruit_matrixportal.matrixportal.MatrixPortal`
is a fairly heavy convenience wrapper (WiFi, HTTP, and more) that pulls in
most of the rest transitively. This is the exact set verified working on
the actual device, so a future re-provision doesn't need to re-trace
imports from scratch:

```
adafruit_bitmap_font/
adafruit_bus_device/
adafruit_connection_manager.mpy
adafruit_display_text/
adafruit_esp32spi/
adafruit_fakerequests.mpy
adafruit_matrixportal/
adafruit_portalbase/
adafruit_requests.mpy
adafruit_ticks.mpy
neopixel.mpy
simpleio.mpy
```

`adafruit_imageload/`, `adafruit_io/`, `adafruit_minimqtt/`, and
`adafruit_miniqr.mpy` are also present on the currently-provisioned device
but **not required** by the current `code.py` — `adafruit_imageload` is a
leftover from an abandoned team-crest interstitial feature (reverted for
memory-safety reasons, see git history), the rest came bundled with
`adafruit_matrixportal`'s optional extras. Safe to omit all four on a
fresh provision.

</details>

### Rendering pattern: fighting a heap that never defragments

CircuitPython's allocator does not compact or defragment memory —
`gc.collect()` reclaims garbage but can't relocate live objects to close
gaps, so on a board this memory-constrained, fragmentation alone can crash
a `Label.text` assignment that's well within the *total* free memory
reported. Two patterns exist specifically to avoid that, confirmed live on
hardware over many rounds of `MemoryError` crashes:

- **One `Label` object, created once at boot, reused for everything** by
  mutating `.text`/`.color`/`.x`/`.y` — not a fresh `Label` per screen.
  `MatrixPortal.add_text()`/`set_text()` allocate a brand-new `Label` every
  call, which is fine for text that rarely changes but fragments the heap
  fast at this project's update rate (2-3+ text changes per poll cycle).
  A second permanent `Label` (tried for standings row-coloring) and a
  permanent `TileGrid`+`Bitmap` (tried for a crest interstitial) were both
  independently found to push this board over the edge even at small
  sizes — the constraint is the *number* of permanent `displayio` objects
  in the render tree, not any single one's content size. Both were
  reverted; the standings table renders in one color, and there's no crest
  feature.
- **One screen per headline, not one screen with all of them joined.** A
  ~400+ character joined string reliably crashed `Label._update_text` even
  on the very first cycle with plenty of `gc.mem_free()` reported — the
  allocator couldn't find one contiguous block that size despite enough
  *total* free memory. Same reasoning applies to the standings table: it
  renders in `TABLE_CHUNK_SIZE`-row chunks, not as one continuous scroll
  through all ~20 teams.

### `ascii_safe()`

`terminalio.FONT` only covers a roughly US-keyboard character set.
Football headlines routinely include £ (transfer fees), en/em dashes, and
curly quotes — `ascii_safe()` substitutes the common ones to something
legible and drops anything else outside ASCII, rather than every
unmapped character rendering as a stray `.`.

### Flashing: use a different machine than the primary dev machine

Bilbo's (this project's dev machine) USB stack reports 0 capacity on this
board's UF2 bootloader mass-storage device — flashing from Bilbo does not
work. Root cause unconfirmed (untested whether it's a Linux/Windows driver
difference or just needed a power cycle at the time). Flashing from a
Windows machine worked without issue. Don't spend time re-discovering
this — just use a different machine.

## Terminal client (`tui/`)

`team-ticker-view` is a small Go CLI that fetches `ticker.json` from a
running backend (the same plain-HTTP URL the Matrix Portal polls) and
prints one formatted page to stdout — a terminal equivalent of the LED
matrix display, not an interactive TUI. It has none of the LED matrix's
memory constraints, so unlike the firmware it renders the *full* league
table (`full_table`), not just the ±2-team window (`table`).

```sh
cd tui
go build -o team-ticker-view .
./team-ticker-view -set-url http://lfc-ticker.home/ticker.json   # save it once...
./team-ticker-view                                               # ...then just run it
```

The URL is resolved in this order: the `-url` flag (a one-off override,
not saved), then the `TICKER_URL` environment variable, then the saved
setting at `~/.config/team-ticker-view/env`. If none of those are set,
it prompts once on stdin and saves your answer for next time — same
first-run convention as nyt-term's API key prompt.

Run it again (alias it, or wrap it in `watch -n 60 ...`) whenever you want
a fresh look — it doesn't poll on its own. The footer's "updated Xm ago"
line turns into a warning once `generated_at` is older than 35 minutes,
since the backend's own slowest poll interval is 15 minutes (idle mode) —
see `POLL_INTERVAL_BY_MODE` in `poller.py` — so anything well past that
means the poller likely isn't running, not just between cycles.

**If `lfc-ticker.home` (or your equivalent `.home` hostname) fails to
resolve** with `dial tcp: lookup ... no such host` even though
`resolvectl status` lists your Pi-hole (or other LAN DNS) as one of the
link's servers: systemd-resolved doesn't know that server is authoritative
for `.home` and falls back to a public resolver, which returns NXDOMAIN.
Fix by adding a routing-only domain and clearing the resulting negative
cache entry:

```sh
sudo resolvectl domain <interface> '~home'   # e.g. enp4s0 — see `resolvectl status`
sudo systemctl restart systemd-resolved      # flush-caches alone did not clear
                                              # the stale NXDOMAIN on the machine
                                              # this was first hit on; a full
                                              # restart did.
resolvectl query lfc-ticker.home             # should now return an address
```

```sh
cd tui
go build ./...
go vet ./...
go test ./...
```

## Monitoring

Set `KUMA_PUSH_URL` to an Uptime Kuma (or compatible) push-monitor URL.
Every cycle that successfully writes `ticker.json` pushes `status=up`;
a cycle that fails pushes an explicit `status=down` with a short failure
message *before* the poller's own backoff/retry kicks in, rather than
relying on Kuma's own timeout detection alone to notice a dead poller. A
failed heartbeat push is logged and swallowed — monitoring must never be
able to take down the primary polling function.

Uptime Kuma's own monitor-side check/retry window (configured in the Kuma
web UI, not this repo) should be set longer than the poller's longest gap
between pushes — 900s in idle mode — to avoid false "down" alerts between
legitimate heartbeats.

## Where secrets live

`backend/.env`, the Uptime Kuma push URL, and the Matrix Portal's WiFi
credentials/`secrets.py` are all stored in 1Password — not reproduced here.
Only `.example` templates (`backend/.env.example`,
`firmware/secrets.py.example`) are committed; the real files are
gitignored.
