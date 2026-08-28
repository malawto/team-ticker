"""team-ticker display for Adafruit Matrix Portal M4 (64x32 HUB75 panel).

Polls the team-ticker backend's ticker.json over plain HTTP (not HTTPS —
this board's ESP32 co-processor doesn't handle installing a custom CA well,
so the backend also serves an unencrypted copy of the same file specifically
for this) and renders it as scrolling text, colour-coded by mode: green for
live, amber for matchday, red for idle.

Requires secrets.py on the CIRCUITPY drive (see secrets.py.example) with a
`secrets` dict containing "ssid", "password", and "ticker_url".
"""

import gc
import time

import board
import terminalio
from adafruit_display_text.label import Label
from adafruit_matrixportal.matrixportal import MatrixPortal

try:
    from secrets import secrets
except ImportError:
    print("WiFi/ticker settings are kept in secrets.py, please add them there!")
    raise

TICKER_URL = secrets["ticker_url"]

FETCH_INTERVAL = 60  # seconds between polls of the backend
SCROLL_FRAME_DELAY = 0.02  # seconds per scroll pixel-step

# Our own diagnostic prints (screen contents, mode). Off by default so the
# shipped version isn't chatty; flip to True when debugging on serial.
DEBUG = False

COLOR_LIVE = 0x00CC00
COLOR_MATCHDAY = 0xCC7700
COLOR_IDLE = 0xCC0000
COLOR_STATUS = 0x666666  # connecting / error states

# Longest string we'll ever try to display - now that headlines are shown
# one at a time (see build_screens) rather than joined, the table screen
# (~120 chars observed) is the longest realistic content; this leaves
# headroom above that. Text longer than this gets truncated before being
# assigned (see show_screen) rather than raising.
#
# On CircuitPython 6 / adafruit_display_text 2.x, this was also passed to
# Label's constructor as max_glyphs to pre-size its glyph buffer once up
# front, avoiding a reallocate-on-every-.text-assignment pattern that
# fragmented this board's small heap until an allocation failed outright
# (observed live). adafruit_display_text 5.x (this CircuitPython 10.x
# install) removed max_glyphs from Label's constructor entirely - its
# _set_text() still calls an internal _reset_text() on every assignment,
# so re-verify this crash doesn't recur under the new library rather than
# assume the newer allocator/GC makes the old workaround unnecessary.
MAX_GLYPHS = 200

matrixportal = MatrixPortal(status_neopixel=board.NEOPIXEL, bit_depth=6, debug=False)

# MatrixPortal.add_text()/set_text() create a brand-new Label object on
# every single call (confirmed in the installed adafruit_matrixportal
# source) - fine for a label that rarely changes, but this display updates
# its text 2-3+ times per poll cycle, and repeatedly allocating/discarding
# Label/TileGrid/palette objects fragments this board's small heap. Managing
# a single, reused Label directly and just mutating .text/.color/.x on it
# avoids that specific churn regardless of whether max_glyphs pre-sizing is
# available in the installed library version.
_label = Label(
    terminalio.FONT,
    text="Connecting...",
    color=COLOR_STATUS,
)
_label.y = matrixportal.display.height // 2 - 1
matrixportal.splash.append(_label)

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


def _is_ascii(text):
    for char in text:
        if ord(char) >= 128:
            return False
    return True


def ascii_safe(text):
    """Replace characters outside terminalio.FONT's charset with a legible
    ASCII equivalent where we have one, otherwise drop them (rather than
    leaving a run of "." for e.g. accented names).

    Headlines are the longest strings we ever handle (~400+ chars) and are
    exactly where free memory is tightest each cycle, so this avoids
    building a Python list of hundreds of one-character strings (observed
    live: MemoryError here on a real headline) - str.replace() handles the
    known substitutions in place without that per-character overhead, and
    the character-by-character rebuild only runs at all for the rare case
    of a genuinely unmapped character outside both ASCII and our table.
    """
    for bad, good in _ASCII_SUBSTITUTIONS.items():
        if bad in text:
            text = text.replace(bad, good)

    if _is_ascii(text):
        return text

    out = []
    for char in text:
        if ord(char) < 128:
            out.append(char)
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

        # One screen per headline, not one screen with all of them joined -
        # a ~400+ char joined string reliably crashed rendering (observed
        # live: MemoryError inside Label._update_text, on the very first
        # cycle with plenty of gc.mem_free() reported - the allocator can't
        # find one contiguous block that size even when total free memory
        # looks fine, and gc.collect() doesn't defragment/compact CircuitPython's
        # heap). Table (~120 chars) and next fixture (~40 chars) have run
        # reliably for many cycles; keeping each screen in that range avoids
        # the failure mode entirely instead of just hoping there's enough
        # contiguous memory each time.
        headlines = idle.get("headlines") or []
        for headline in headlines:
            screens.append((headline, COLOR_IDLE))

        if not screens:
            screens.append(("No data", COLOR_IDLE))
        return screens

    return [("Unknown mode: {}".format(mode), COLOR_STATUS)]


def show_screen(text, color):
    gc.collect()  # max headroom before the longest strings (headlines)

    text = ascii_safe(text)
    if len(text) > MAX_GLYPHS:
        text = text[:MAX_GLYPHS]

    _label.color = color
    _label.text = text

    display_width = matrixportal.display.width
    line_width = _label.bounding_box[2]
    _label.x = display_width
    while _label.x > -line_width:
        _label.x -= 1
        time.sleep(SCROLL_FRAME_DELAY)

    gc.collect()


def main():
    screens = [("Connecting...", COLOR_STATUS)]
    have_data = False
    last_fetch = None

    while True:
        due = last_fetch is None or (time.monotonic() - last_fetch) >= FETCH_INTERVAL
        if due:
            data = fetch_ticker()
            # Set *after* fetch_ticker() returns, not before it's called.
            # fetch_ticker() can block for a while (WiFi reconnect retries,
            # a slow/timed-out HTTP round trip) - timestamping before that
            # made the elapsed-time-since-last-fetch already look expired
            # the moment the fetch finished, which cut the screen rotation
            # below short (usually losing exactly the last screen -
            # headlines - since it's reached last).
            last_fetch = time.monotonic()

            gc.collect()
            print("gc.mem_free():", gc.mem_free())

            if data is not None:
                try:
                    screens = build_screens(data)
                    have_data = True
                    if DEBUG:
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
            elif not have_data:
                # Never had good data yet - keep showing "Connecting...";
                # once we do have a good render, a later failed fetch just
                # holds the last good screens instead of blanking them.
                screens = [("Connecting...", COLOR_STATUS)]
            data = None  # drop the reference so gc can reclaim it promptly

        # Always play the full rotation - no early exit part-way through,
        # so every screen (including headlines, last in the list) reliably
        # gets its turn instead of being cut off by a stale time check.
        for text, color in screens:
            show_screen(text, color)


main()
