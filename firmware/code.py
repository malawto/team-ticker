"""team-ticker display for Adafruit Matrix Portal M4 (64x32 HUB75 panel).

Polls the team-ticker backend's ticker.json over plain HTTP (not HTTPS —
this board's ESP32 co-processor doesn't handle installing a custom CA well,
so the backend also serves an unencrypted copy of the same file specifically
for this) and renders it as scrolling text, colour-coded by mode: green for
live, amber for matchday, red for idle.

Requires secrets.py on the CIRCUITPY drive (see secrets.py.example) with a
`secrets` dict containing "ssid", "password", and "ticker_url".
Optionally "utc_offset_minutes" and "timezone_label" to also show kickoff
times converted to local time alongside UTC.
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
# Both optional - see format_kickoff. In minutes, not hours, so real-world
# fractional-hour timezones (e.g. India UTC+5:30, Newfoundland UTC-3:30)
# are representable exactly rather than rounded.
UTC_OFFSET_MINUTES = secrets.get("utc_offset_minutes", 0)
TIMEZONE_LABEL = secrets.get("timezone_label", "local")

FETCH_INTERVAL = 60  # seconds between polls of the backend
SCROLL_FRAME_DELAY = 0.02  # seconds per scroll pixel-step
STICK_PAUSE_SECONDS = 1.0  # pause when the standings' vertical scroll centers your team
# Max rows rendered in a single vertical-scroll Label.text assignment (see
# build_screens' standings handling). Two competing failure modes observed
# live: too large in one block crashes outright (MemoryError, the full
# ~20-team table as one chunk), but too many small chunks per cycle also
# crashes - not from any single assignment's size, but from a real
# cross-cycle memory drop (~7.6KB/cycle observed at chunk_size=5, 4 chunks/
# cycle) that gc.collect() isn't fully recovering. 10 halves the chunk
# count (2 instead of 4) while staying well under the size that crashed
# outright - re-verify this doesn't just move the same leak, not assumed.
TABLE_CHUNK_SIZE = 10

# Our own diagnostic prints (screen contents, mode). Off by default so the
# shipped version isn't chatty; flip to True when debugging on serial.
DEBUG = False

COLOR_LIVE = 0x00CC00
COLOR_MATCHDAY = 0xCC7700
COLOR_IDLE = 0xCC0000
COLOR_STATUS = 0x666666  # connecting / error states

# Longest string we'll ever try to display - a single headline (~40-90
# chars observed) or one TABLE_CHUNK_SIZE-row standings chunk, both well
# under this. The full ~20-team standings table would be far longer, but is
# deliberately never rendered as one block - see build_screens' standings
# handling for why (a single that-large Label.text assignment reliably
# crashed with MemoryError, observed live). Text longer than this gets
# truncated before being assigned (see _set_label_text) rather than
# raising, as a backstop, not the primary defense.
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

# A second persistent Label (to render your team's standings row in a
# different colour from the rest) was tried and dropped - it measurably
# pushed this board's already-tight memory budget over the edge (observed
# live: a MemoryError on the very next screen after a cycle with the extra
# Label present, gc.mem_free() at ~13KB vs the usual 20-30KB). Standings
# rows all render in one colour via _label alone; see show_screen_vertical.

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
    """"2026-08-29T11:30Z" -> "08-29 11:30 UTC" (UTC_OFFSET_MINUTES unset/0)
    or "08-29 11:30 UTC  07:30 EDT" (configured). CircuitPython has no
    zoneinfo/full datetime arithmetic, so this only converts the clock time
    (hour:minute, wrapping within a day) via plain integer arithmetic - it
    deliberately doesn't attempt to roll the displayed date across a
    midnight boundary that a large offset might cross, since that needs
    real calendar math this board has no library for. The UTC date+time
    shown alongside stays the authoritative, unambiguous value either way.
    """
    if not iso_utc:
        return "TBD"
    try:
        date_part, time_part = iso_utc.split("T")
        hour_str, minute_str = time_part.rstrip("Z")[:5].split(":")
        utc_hour = int(hour_str)
        utc_minute = int(minute_str)
    except (ValueError, IndexError):
        return iso_utc

    utc_display = "{} {:02d}:{:02d} UTC".format(date_part[5:], utc_hour, utc_minute)

    if not UTC_OFFSET_MINUTES:
        return utc_display

    local_total_minutes = (utc_hour * 60 + utc_minute + UTC_OFFSET_MINUTES) % 1440
    local_hour = local_total_minutes // 60
    local_minute = local_total_minutes % 60
    return "{}  {:02d}:{:02d} {}".format(
        utc_display, local_hour, local_minute, TIMEZONE_LABEL
    )


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


def _h_screen(text, color):
    """A screen rendered as a single horizontally-scrolling line."""
    return {"kind": "h", "text": text, "color": color}


def _v_screen(rows, team_index, color):
    """A screen rendered as a vertically-scrolling stack of short rows,
    bottom-to-top. If team_index is not None, sticks with `rows[team_index]`
    centered for a moment before continuing off the top.
    """
    return {"kind": "v", "rows": rows, "team_index": team_index, "color": color}


def build_screens(data):
    """Turn a parsed ticker.json dict into a list of screens to show in
    sequence (see _h_screen/_v_screen). live/matchday produce a single
    screen; idle produces several (next fixture, standings, headlines) so
    they rotate distinctly rather than blurring into one continuous scroll.
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
        return [_h_screen(text, COLOR_LIVE)]

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
        return [_h_screen(text, COLOR_MATCHDAY)]

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
        screens.append(_h_screen(text, COLOR_IDLE))

        # Standings scroll vertically (bottom to top, one short row per
        # team, the whole table not just a window around your team) rather
        # than as one long horizontal line - "10.Liverpool 1pt"-style rows
        # are far wider than the 64px panel at any usable font size, but
        # ESPN's own short "abbreviation" code (e.g. "LIV") keeps each row
        # narrow without needing a smaller font at all.
        #
        # Rendered as several small chunks (one screen each), not one
        # continuous scroll through all ~20 teams - a single Label.text
        # assignment that large reliably crashed (observed live:
        # MemoryError inside Label._update_text, same failure class as the
        # joined-headlines crash this same project hit earlier). TABLE_CHUNK_SIZE
        # matches the old ±2-context window size, already proven safe.
        # Only the chunk containing your team gets the stick pause; other
        # chunks scroll straight through. (A second colour just for your
        # team's row was tried and dropped - see _label's definition - so
        # every row here renders the same COLOR_IDLE as the rest of idle
        # mode; the ">" marker is what identifies your row now.)
        table = idle.get("full_table") or []
        for chunk_start in range(0, len(table), TABLE_CHUNK_SIZE):
            chunk = table[chunk_start : chunk_start + TABLE_CHUNK_SIZE]
            rows = []
            team_index = None
            for index, row in enumerate(chunk):
                if row.get("is_team"):
                    team_index = index
                marker = ">" if row.get("is_team") else " "
                rows.append(
                    "{}{} {} {}p".format(
                        marker,
                        row.get("position", "?"),
                        row.get("abbreviation") or row.get("team", "?"),
                        row.get("points", "?"),
                    )
                )
            screens.append(_v_screen(rows, team_index, COLOR_IDLE))

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
            screens.append(_h_screen(headline, COLOR_IDLE))

        if not screens:
            screens.append(_h_screen("No data", COLOR_IDLE))
        return screens

    return [_h_screen("Unknown mode: {}".format(mode), COLOR_STATUS)]


def _set_label_text(text):
    text = ascii_safe(text)
    if len(text) > MAX_GLYPHS:
        text = text[:MAX_GLYPHS]
    _label.text = text
    return text


def show_screen_horizontal(text, color):
    """Scroll a single line right-to-left across the panel."""
    gc.collect()  # max headroom before the longest strings (headlines)

    # Hidden for the whole setup: .text assignment renders immediately at
    # whatever position the label is currently sitting at (leftover from
    # the previous screen), and that briefly-visible stale-position render
    # is exactly the "created before the scroll begins" flash - hiding
    # until it's positioned at the correct off-screen start point means
    # that intermediate render never reaches the panel at all.
    _label.hidden = True
    _label.color = color
    _set_label_text(text)
    # A vertical screen may have left .y off in the weeds (see
    # show_screen_vertical) - a single-line screen always renders at a
    # fixed vertical center, so restore it explicitly rather than
    # inheriting wherever the last screen happened to leave it.
    _label.y = matrixportal.display.height // 2 - 1

    display_width = matrixportal.display.width
    line_width = _label.bounding_box[2]
    _label.x = display_width
    _label.hidden = False

    while _label.x > -line_width:
        _label.x -= 1
        time.sleep(SCROLL_FRAME_DELAY)

    gc.collect()


def show_screen_vertical(rows, team_index, color):
    """Scroll a stack of short rows (one chunk of the standings - see
    build_screens' TABLE_CHUNK_SIZE) bottom-to-top, all in one colour. If
    team_index is not None, pauses with `rows[team_index]` centered for
    STICK_PAUSE_SECONDS before continuing off the top; if None (this chunk
    doesn't contain your team), scrolls straight through with no pause.

    Row/line height is measured from the Label's own rendered bounding_box
    rather than assumed, since exact font metrics have proven unreliable to
    hardcode across CircuitPython/adafruit_display_text versions in this
    project (see MAX_GLYPHS's history) - this stays correct regardless of
    the installed font's actual pixel dimensions.
    """
    gc.collect()

    # See show_screen_horizontal for why: hidden until positioned at the
    # correct off-screen start point, so the "created before the scroll
    # begins" flash never reaches the panel.
    _label.hidden = True
    sanitized = [_set_label_text_line(row) for row in rows]
    _label.color = color
    _label.x = 0
    _label.text = "\n".join(sanitized)

    display_height = matrixportal.display.height
    total_height = _label.bounding_box[3]
    if total_height <= 0 or not rows:
        _label.hidden = False
        return

    row_height = total_height / len(rows)
    start_y = display_height
    end_y = -total_height

    if team_index is None:
        stick_y = None
    else:
        team_center_offset = team_index * row_height + row_height / 2
        stick_y = (display_height / 2) - team_center_offset

    if DEBUG:
        print(
            "vscroll: rows={} widest_line_px={} total_h={} row_h={} "
            "team_idx={} stick_y={} start_y={} end_y={}".format(
                len(rows),
                _label.bounding_box[2],
                total_height,
                row_height,
                team_index,
                stick_y,
                start_y,
                end_y,
            )
        )

    _label.y = start_y
    _label.hidden = False

    if stick_y is not None:
        while _label.y > stick_y:
            _label.y -= 1
            time.sleep(SCROLL_FRAME_DELAY)
        time.sleep(STICK_PAUSE_SECONDS)

    while _label.y > end_y:
        _label.y -= 1
        time.sleep(SCROLL_FRAME_DELAY)

    gc.collect()


def _set_label_text_line(text):
    """Like ascii_safe(), but for one row of a vertical-scroll screen -
    truncated to a per-line budget rather than the whole-label MAX_GLYPHS,
    since MAX_GLYPHS is sized for a single long horizontal line.
    """
    text = ascii_safe(text)
    return text[:40]


def show_screen(screen):
    if screen["kind"] == "v":
        show_screen_vertical(screen["rows"], screen["team_index"], screen["color"])
    else:
        show_screen_horizontal(screen["text"], screen["color"])


def main():
    screens = [_h_screen("Connecting...", COLOR_STATUS)]
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
                        for screen in screens:
                            if screen["kind"] == "v":
                                print("   [v]", screen["rows"])
                            else:
                                print("   [h]", screen["text"])
                except Exception as error:  # pylint: disable=broad-except
                    print("Building screens failed:", error)
                    screens = [_h_screen("Data error", COLOR_STATUS)]
            elif not have_data:
                # Never had good data yet - keep showing "Connecting...";
                # once we do have a good render, a later failed fetch just
                # holds the last good screens instead of blanking them.
                screens = [_h_screen("Connecting...", COLOR_STATUS)]
            data = None  # drop the reference so gc can reclaim it promptly

        # Always play the full rotation - no early exit part-way through,
        # so every screen (including headlines, last in the list) reliably
        # gets its turn instead of being cut off by a stale time check.
        for screen in screens:
            show_screen(screen)


main()
