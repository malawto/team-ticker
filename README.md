# team-ticker

A generic sports ticker: a Python backend that polls ESPN and BBC Sport for
a configured team's fixture status and league news, and CircuitPython
firmware for an Adafruit Matrix Portal M4 LED matrix that displays it.

No team or league is hardcoded — the reference/default instance is
Liverpool FC / the English Premier League, but any team ESPN tracks works
by changing two environment variables.

## How it works

- **`backend/`** — a Python service (`poller.py`) that polls ESPN's
  scoreboard/standings APIs and the BBC Sport RSS feed, determines a mode
  (`live` / `matchday` / `idle`), and writes the result to `ticker.json`.
  Runs as a Docker container.
- **`firmware/`** — CircuitPython (`code.py`) for an Adafruit Matrix Portal
  M4 driving a 64x32 HUB75 LED matrix, which polls `ticker.json` and
  renders it as scrolling text: green while a match is live, amber on
  matchday, red otherwise (next fixture, league table, headlines).

The display polls `ticker.json` over **plain HTTP**, not HTTPS — the Matrix
Portal's ESP32 co-processor doesn't handle installing a custom CA well. If
you put the backend behind your own reverse proxy/TLS, also expose an
unencrypted copy of `ticker.json` for the display to use.

## Repository layout

```
backend/     Docker container + poller.py — fetches data, writes ticker.json
firmware/    CircuitPython code for the Matrix Portal display
```

## Backend setup

Requirements: Docker and Docker Compose.

1. **Configure your team/league.**

   ```sh
   cd backend
   cp .env.example .env
   ```

   Edit `.env`:

   | Variable | Required | Notes |
   |---|---|---|
   | `TEAM_ID` | No | ESPN's numeric team id. Find it by opening `https://site.api.espn.com/apis/site/v2/sports/soccer/<LEAGUE>/scoreboard` and reading a competitor's `team.id`. Defaults to `364` (Liverpool FC). |
   | `LEAGUE` | No | ESPN's league slug, e.g. `eng.1`. Defaults to `eng.1`. |
   | `PUID` / `PGID` | No | UID/GID the container runs as — match the host user that should own the bind-mounted `data/` directory. Check with `id <your-user>`. Default to `1000`/`1000`. |
   | `KUMA_PUSH_URL` | No | Push-monitor URL (Uptime Kuma or compatible). Every successful cycle pings `status=up`; a failed cycle pings `status=down` before backing off. Omit to skip heartbeats entirely. |

2. **Run it.**

   ```sh
   # Local/dev
   docker compose up -d --build

   # Production (adds restart: unless-stopped and a fixed container name)
   docker compose -f docker-compose.prod.yml up -d --build
   ```

3. **Serve `ticker.json`.** It's written to the bind-mounted `data/`
   directory. Serve that directory (or just the file) over plain HTTP so
   the display can reach it — how (nginx, Caddy, etc.) is up to your own
   setup.

The poll interval adapts to the mode just written: 60s while a match is
live, 5 minutes on matchday, 15 minutes idle.

### Running tests

```sh
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest tests.test_poller
```

## Firmware setup

Hardware: an Adafruit Matrix Portal M4 driving a 64x32 HUB75 LED matrix
panel, running CircuitPython 10.2.1.

1. **Install CircuitPython 10.2.1** on the board (see Adafruit's Matrix
   Portal M4 guide), then copy onto the `CIRCUITPY` drive:
   - `firmware/code.py` → `code.py`
   - The `adafruit_display_text` and `adafruit_matrixportal` libraries (and
     their dependencies) from the Adafruit CircuitPython Bundle matching
     your installed CircuitPython version, into `lib/`.

2. **Copy `firmware/secrets.py.example` → `secrets.py`** on the `CIRCUITPY`
   drive and fill in:

   | Key | Required | Notes |
   |---|---|---|
   | `ssid` / `password` | Yes | Your WiFi network. |
   | `ticker_url` | Yes | The plain-HTTP URL to your backend's `ticker.json`, e.g. `http://your-ticker-host/ticker.json`. |
   | `utc_offset_minutes` | No | In minutes, not hours, so fractional-hour timezones are exact. Also shows kickoff times converted to local time alongside UTC. |
   | `timezone_label` | No | Label shown next to the converted local time, e.g. `"EDT"`. |

3. **Save.** CircuitPython auto-reloads and starts polling.

## Notes

- `secrets.py` and `.env` are both gitignored — never commit real
  credentials. Only the `.example` templates are tracked.
- Every team/league/network-specific value lives in `.env` (backend) or
  `secrets.py` (firmware) — the code itself has nothing team-specific baked
  in.
