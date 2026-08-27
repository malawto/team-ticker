"""team-ticker display for Adafruit Matrix Portal M4 (64x32 HUB75 panel).

Polls the team-ticker backend's ticker.json over plain HTTP (not HTTPS —
this board's ESP32 co-processor doesn't handle installing a custom CA well,
so the backend also serves an unencrypted copy of the same file specifically
for this) and renders it as scrolling text, colour-coded by mode: green for
live, amber for matchday, red for idle.

Requires secrets.py on the CIRCUITPY drive (see secrets.py.example) with a
`secrets` dict containing "ssid", "password", and "ticker_url".
"""

import time

import board
from adafruit_matrixportal.matrixportal import MatrixPortal

try:
    from secrets import secrets
except ImportError:
    print("WiFi/ticker settings are kept in secrets.py, please add them there!")
    raise

TICKER_URL = secrets["ticker_url"]

FETCH_INTERVAL = 60  # seconds between polls of the backend
SCROLL_FRAME_DELAY = 0.02  # seconds per scroll pixel-step

COLOR_LIVE = 0x00CC00
COLOR_MATCHDAY = 0xCC7700
COLOR_IDLE = 0xCC0000
COLOR_STATUS = 0x666666  # connecting / error states

matrixportal = MatrixPortal(status_neopixel=board.NEOPIXEL, bit_depth=6, debug=False)
matrixportal.add_text(
    text_position=(0, matrixportal.display.height // 2 - 1),
    text_color=COLOR_STATUS,
    scrolling=True,
)

# terminalio.FONT only covers a roughly US-keyboard character set; anything
# outside it renders as a stray "." rather than raising, but football news
# headlines routinely include a few characters worth mapping to something
# legible instead (transfer fees use £ constantly, headlines use en/em
# dashes and curly quotes).
_ASCII_SUBSTITUTIONS = {
    "£": "GBP",  # £
    "–": "-",  # en dash
    "—": "-",  # em dash
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
}


def ascii_safe(text):
    """Replace characters outside terminalio.FONT's charset with a legible
    ASCII equivalent where we have one, otherwise drop them (rather than
    leaving a run of "." for e.g. accented names).
    """
    out = []
    for char in text:
        if ord(char) < 128:
            out.append(char)
        elif char in _ASCII_SUBSTITUTIONS:
            out.append(_ASCII_SUBSTITUTIONS[char])
        # else: drop it
    return "".join(out)


def format_kickoff(iso_utc):
    """"2026-08-29T11:30Z" -> "08-29 11:30 UTC". No timezone conversion —
    CircuitPython has no zoneinfo, so this stays in UTC rather than
    silently showing the wrong local time.
    """
    if not iso_utc:
        return "TBD"
    try:
        date_part, time_part = iso_utc.split("T")
        return "{} {} UTC".format(date_part[5:], time_part.rstrip("Z")[:5])
    except (ValueError, IndexError):
        return iso_utc


def fetch_ticker():
    """Fetch and parse ticker.json. Returns a dict, or None on any failure
    (network down, endpoint unreachable, malformed JSON) — never raises.
    """
    try:
        response = matrixportal.network.fetch(TICKER_URL, timeout=10)
        return response.json()
    except Exception as error:  # pylint: disable=broad-except
        print("Fetch/parse failed:", error)
        return None


def build_screens(data):
    """Turn a parsed ticker.json dict into a list of (text, color) screens
    to show in sequence. live/matchday produce a single screen; idle
    produces up to three (next fixture, table slice, headlines) so they
    rotate distinctly rather than blurring into one continuous scroll.
    """
    mode = data.get("mode")

    if mode == "live":
        live = data.get("live") or {}
        vs = "vs" if live.get("home_away") == "home" else "@"
        score = live.get("score") or {}
        text = "LIVE {} {}  {}-{}  {}".format(
            vs,
            live.get("opponent", "?"),
            score.get("team", "?"),
            score.get("opponent", "?"),
            live.get("clock") or "",
        )
        return [(text, COLOR_LIVE)]

    if mode == "matchday":
        matchday = data.get("matchday") or {}
        vs = "vs" if matchday.get("home_away") == "home" else "@"
        opponent = matchday.get("opponent", "?")
        if "final_score" in matchday:
            final = matchday["final_score"] or {}
            text = "FT {} {}  {}-{}".format(
                vs, opponent, final.get("team", "?"), final.get("opponent", "?")
            )
        else:
            text = "{} {}  {}".format(
                vs, opponent, format_kickoff(matchday.get("kickoff_utc"))
            )
        return [(text, COLOR_MATCHDAY)]

    if mode == "idle":
        idle = data.get("idle") or {}
        screens = []

        next_fixture = idle.get("next_fixture") or {}
        if next_fixture.get("opponent"):
            vs = "vs" if next_fixture.get("home_away") == "home" else "@"
            text = "NEXT: {} {}  {}".format(
                vs,
                next_fixture["opponent"],
                format_kickoff(next_fixture.get("kickoff_utc")),
            )
        else:
            text = "NEXT: TBD"
        screens.append((text, COLOR_IDLE))

        table = idle.get("table") or []
        if table:
            rows = []
            for row in table:
                marker = ">" if row.get("is_team") else ""
                rows.append(
                    "{}{}.{} {}pt".format(
                        marker,
                        row.get("position", "?"),
                        row.get("team", "?"),
                        row.get("points", "?"),
                    )
                )
            screens.append(("  |  ".join(rows), COLOR_IDLE))

        headlines = idle.get("headlines") or []
        if headlines:
            screens.append(("  //  ".join(headlines), COLOR_IDLE))

        if not screens:
            screens.append(("No data", COLOR_IDLE))
        return screens

    return [("Unknown mode: {}".format(mode), COLOR_STATUS)]


def show_screen(text, color):
    matrixportal.set_text_color(color, index=0)
    matrixportal.set_text(ascii_safe(text), index=0)
    matrixportal.scroll_text(SCROLL_FRAME_DELAY)


def main():
    screens = [("Connecting...", COLOR_STATUS)]
    last_fetch = None

    while True:
        now = time.monotonic()
        if last_fetch is None or (now - last_fetch) >= FETCH_INTERVAL:
            data = fetch_ticker()
            if data is not None:
                try:
                    screens = build_screens(data)
                    print(
                        "Rendering mode={} ({} screen(s))".format(
                            data.get("mode"), len(screens)
                        )
                    )
                    for screen_text, _ in screens:
                        print("  ", screen_text)
                except Exception as error:  # pylint: disable=broad-except
                    print("Building screens failed:", error)
                    screens = [("Data error", COLOR_STATUS)]
            elif last_fetch is None:
                # Never had good data yet - keep showing "Connecting...";
                # once we do have a good render, a later failed fetch just
                # holds the last good screens instead of blanking them.
                screens = [("Connecting...", COLOR_STATUS)]
            last_fetch = now

        for text, color in screens:
            show_screen(text, color)
            if time.monotonic() - last_fetch >= FETCH_INTERVAL:
                break


main()
