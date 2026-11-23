#!/usr/bin/env python3
"""
receiver.py - the live display for Operation Antitelephone.

  python receiver.py              run the receiver   (Q quit, R refresh now, T test the alarm, A acknowledge)
  python receiver.py --demo       simulated messages, including a fake HIT after about 25 seconds
  python receiver.py --fps 2      fewer frames per second, for less CPU on an always-on screen (default 8)
  python receiver.py --allow-sleep   let Windows go to sleep while the receiver runs (by default it keeps the PC awake)
  python receiver.py --snapshot frame.html [--demo] [--size 160x48] [--at 12]    render one frame to an HTML file

Needs Python 3.11+ and a terminal with 24-bit colour (Windows Terminal, or most Mac/Linux terminals). Bigger windows get
bigger displays: 108x28 and up shows the LED panel, 120x40 adds the big title, 206x52 doubles the LEDs.
It only reads: the NIST beacon and the station's public GitHub issues (with your gh login if you have one).
"""
import datetime as dt
import html
import json
import math
import os
import random
import re
import shutil
import sys
import threading
import time

import station

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "receiver_state.json")
ERROR_LOG = os.path.join(BASE, "receiver_error.log")
UTC = dt.timezone.utc


def mono():
    return time.monotonic()


# ---------------------------------------------------------------- palette
BG_A, BG_B = (6, 6, 10), (9, 9, 15)                      # alternating rows: a faint CRT scanline feel
PANEL = (12, 12, 20)
STEEL, STEEL_HI, STEEL_LO = (92, 94, 112), (170, 174, 196), (48, 49, 62)
TEXT, DIM, FAINT = (210, 212, 225), (128, 130, 150), (84, 86, 104)
RED, RED_GHOST, RED_PLATE = (255, 52, 28), (46, 10, 8), (76, 15, 8)
GREEN, GREEN_GHOST, GREEN_PLATE = (60, 255, 110), (8, 40, 18), (18, 76, 33)
AMBER, AMBER_GHOST, AMBER_PLATE = (255, 176, 0), (44, 30, 2), (76, 52, 0)
CYAN, CYAN_DIM, CYAN_GHOST = (0, 229, 255), (0, 110, 128), (0, 34, 42)
MAGENTA = (255, 46, 136)
SCOPE_BG = (2, 18, 8)
FOOT_BG = (16, 16, 26)
GRADIENT = [(255, 106, 0), (255, 46, 136), (160, 60, 255), (0, 229, 255)]
VERDICT_COLOR = {"HIT": RED, "check by hand": AMBER, "pending": CYAN, "miss": DIM, "too late": DIM, "invalid": DIM,
                 "unreadable": DIM, "void": DIM, "new": GREEN}
ALARM_KINDS = ("HIT", "check by hand")


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


_dim_cache = {}


def dimmed(c, f):
    key = (c, f)
    if key not in _dim_cache:
        _dim_cache[key] = mix(c, (0, 0, 0), f)
    return _dim_cache[key]


def gradient(t):
    t = max(0.0, min(1.0, t)) * (len(GRADIENT) - 1)
    i = min(int(t), len(GRADIENT) - 2)
    return mix(GRADIENT[i], GRADIENT[i + 1], t - i)


def pingpong(t):
    """0..1..0 so a scrolling gradient never jumps from the last colour back to the first."""
    return 1 - abs(2 * (t % 1.0) - 1)


_NOISE = [random.Random(i).uniform(-0.9, 0.9) for i in range(4096)]     # fixed noise table for the scope
_SPIKE = [random.Random(i * 7 + 3).random() < 0.012 for i in range(4096)]
_SPIKE_DIR = [random.Random(i).choice([-4, 4]) for i in range(4096)]


# ---------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.ch = [[" "] * w for _ in range(h)]
        self.fg = [[TEXT] * w for _ in range(h)]
        self.bg = [[BG_A if y % 2 == 0 else BG_B] * w for y in range(h)]

    def put(self, x, y, s, fg=None, bg=None):
        if not 0 <= y < self.h:
            return
        for i, c in enumerate(s):
            xx = x + i
            if 0 <= xx < self.w:
                self.ch[y][xx] = c
                if fg is not None:
                    self.fg[y][xx] = fg
                if bg is not None:
                    self.bg[y][xx] = bg

    def fill(self, x, y, w, h, bg, scan=True):
        for yy in range(max(0, y), min(self.h, y + h)):
            col = mix(bg, (0, 0, 0), 0.25) if scan and yy % 2 else bg
            for xx in range(max(0, x), min(self.w, x + w)):
                self.ch[yy][xx] = " "
                self.bg[yy][xx] = col

    def pixels(self, x, y, pix):
        """Draw a pixel image (rows of colours or None) with half blocks: two pixels per character cell."""
        for r in range(0, len(pix), 2):
            top = pix[r]
            bot = pix[r + 1] if r + 1 < len(pix) else [None] * len(top)
            cy = y + r // 2
            if not 0 <= cy < self.h:
                continue
            for c in range(len(top)):
                cx = x + c
                if not 0 <= cx < self.w:
                    continue
                t, b = top[c], bot[c]
                if t is None and b is None:
                    continue
                if t is not None and b is not None:
                    self.ch[cy][cx], self.fg[cy][cx], self.bg[cy][cx] = "▀", t, b
                elif t is not None:
                    self.ch[cy][cx], self.fg[cy][cx] = "▀", t
                else:
                    self.ch[cy][cx], self.fg[cy][cx] = "▄", b

    def ansi_line(self, y):
        out, cur_fg, cur_bg = [], None, None
        chars, fgs, bgs = self.ch[y], self.fg[y], self.bg[y]
        for x in range(self.w):
            f, b, c = fgs[x], bgs[x], chars[x]
            if b != cur_bg:
                out.append("\x1b[48;2;%d;%d;%dm" % b)
                cur_bg = b
            if f != cur_fg and c != " ":
                out.append("\x1b[38;2;%d;%d;%dm" % f)
                cur_fg = f
            out.append(c)
        return "".join(out) + "\x1b[0m"

    def html(self, title="receiver"):
        rows = []
        for y in range(self.h):
            spans, run, key = [], [], None
            for x in range(self.w):
                k = (self.fg[y][x], self.bg[y][x])
                if k != key and run:
                    spans.append(span(key, "".join(run)))
                    run = []
                key = k
                run.append(self.ch[y][x])
            if run:
                spans.append(span(key, "".join(run)))
            rows.append("".join(spans))
        return ("<!doctype html><meta charset=utf-8><title>%s</title><body style='margin:0;background:#06060a'>"
                "<pre style='margin:0;font:15px/1.0 \"Cascadia Mono\",Consolas,monospace;letter-spacing:0'>%s</pre>"
                % (html.escape(title), "\n".join(rows)))


def span(key, text):
    (fr, fg_, fb), (br, bg_, bb) = key
    return "<span style='color:rgb(%d,%d,%d);background:rgb(%d,%d,%d)'>%s</span>" % (
        fr, fg_, fb, br, bg_, bb, html.escape(text))


# ---------------------------------------------------------------- LED fonts
SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc",
            "8": "abcdefg", "9": "abcdfg", "-": "g", " ": ""}
SEG_PIXELS = {"a": [(x, 0) for x in range(1, 5)], "b": [(5, 1), (5, 2)], "c": [(5, 4), (5, 5)],
              "d": [(x, 6) for x in range(1, 5)], "e": [(0, 4), (0, 5)], "f": [(0, 1), (0, 2)],
              "g": [(x, 3) for x in range(1, 5)]}
SEG_W = 6                                                # each digit: 6 columns x 4 rows (7 pixels tall), times s


def scale_pix(pix, s):
    if s == 1:
        return pix
    out = []
    for row in pix:
        wide = [c for c in row for _ in range(s)]
        out.extend(list(wide) for _ in range(s))
    return out


def seg_digit(ch, lit, ghost, s=1):
    pix = [[None] * SEG_W for _ in range(8)]
    for name, pts in SEG_PIXELS.items():
        for x, y in pts:
            pix[y][x] = lit if name in SEGMENTS.get(ch, "") else ghost
    return scale_pix(pix, s)


DOT_FONT = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "R": "11110 10001 10001 11110 10100 10010 10001", "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100", "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100", "W": "10001 10001 10001 10101 10101 10101 01010",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "-": "00000 00000 00000 11111 00000 00000 00000",
    " ": "00000 00000 00000 00000 00000 00000 00000", "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110", "!": "00100 00100 00100 00100 00100 00000 00100",
    "#": "11111 11111 11111 11111 11111 11111 11111",        # every dot lit (lamp test)
}


def dot_char(ch, lit, ghost, colfn=None, s=1):
    rows = DOT_FONT.get(ch, DOT_FONT[" "]).split()
    pix = [[None] * 5 for _ in range(8)]
    for y, row in enumerate(rows):
        for x, bit in enumerate(row):
            pix[y][x] = (colfn(x) if colfn else lit) if bit == "1" else ghost
    return scale_pix(pix, s)


def draw_dots(cv, x, y, text, lit, ghost, colfn=None, s=1):
    for i, ch in enumerate(text):
        f = (lambda px, i=i: colfn(i * 6 + px)) if colfn else None
        cv.pixels(x + i * 6 * s, y, dot_char(ch, lit, ghost, f, s))
    return len(text) * 6 * s


def draw_digits(cv, x, y, text, lit, ghost, s=1):
    for i, ch in enumerate(text):
        cv.pixels(x + i * (SEG_W + 1) * s, y, seg_digit(ch, lit, ghost, s))
    return len(text) * (SEG_W + 1) * s


def draw_colon(cv, x, y, color, s=1):
    pix = [[None, None] for _ in range(8)]
    pix[2][0] = pix[4][0] = color
    cv.pixels(x, y, scale_pix(pix, s))


# ---------------------------------------------------------------- data
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def parse_target(body):
    text = station.normalize(body)
    starts = station.target_starts(text)
    if len(starts) != 1:
        return None
    g = station.TARGET_LINE.match(text, starts[0])
    if not g:
        return None
    try:
        return dt.datetime(int(g["y"]), int(g["mo"]), int(g["d"]), int(g["h"]), int(g["mi"]), tzinfo=UTC)
    except ValueError:
        return None


def verdict_of(labels):
    for v in ("HIT", "check by hand", "miss", "too late", "invalid", "unreadable", "void", "pending"):
        if f"station: {v}" in labels:
            return v
    return "new"


def message_from_issue(it):
    labels = {l["name"] for l in it.get("labels", [])}
    if "not a message" in labels:
        return None
    return {"number": it["number"], "created": station.parse_gh_time(it["created_at"]),
            "target": parse_target(it.get("body")), "verdict": verdict_of(labels)}


class State:
    def __init__(self, repo, demo=False):
        self.lock = threading.Lock()
        self.repo, self.demo = repo, demo
        self.started = mono()
        self.nist = {"ok": None, "index": None, "time": None, "value": None, "changed": None, "err": ""}
        self.gh = {"ok": None, "published": None, "messages": [], "robot": None, "good": None, "err": "",
                   "token": False}
        self.alarm = None
        self.acked = set()
        self.refresh = threading.Event()
        self.last_refresh = -1e9
        self.running = True
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                self.acked = set(json.load(f).get("acked", []))
        except Exception:
            pass

    def ack(self):
        with self.lock:
            a = self.alarm
            if a and a.get("number") is not None and not a.get("test"):
                self.acked.add(a["number"])                       # also in demo, but only in memory there
                if not self.demo:
                    tmp = STATE_FILE + ".tmp"
                    try:
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump({"acked": sorted(self.acked)}, f)
                        os.replace(tmp, STATE_FILE)
                    except Exception:
                        pass
            self.alarm = None

    def check_alarm(self):
        """Raise the most important unacknowledged alarm (HIT before CHECK); drop one the robot withdrew."""
        by_num = {m["number"]: m for m in self.gh["messages"]}
        a = self.alarm
        if a and not a.get("test") and a["number"] in by_num and by_num[a["number"]]["verdict"] not in ALARM_KINDS:
            self.alarm = a = None
        cands = sorted((m for m in by_num.values() if m["verdict"] in ALARM_KINDS and m["number"] not in self.acked),
                       key=lambda m: (m["verdict"] != "HIT", -m["number"]))
        if cands:
            m = cands[0]
            if not a or a.get("test") or (a["number"], a["kind"]) != (m["number"], m["verdict"]):
                self.alarm = {"kind": m["verdict"], "number": m["number"], "target": m["target"], "test": False,
                              "since": mono()}

    def request_refresh(self):
        if mono() - self.last_refresh > 20:                       # protect the hourly GitHub limit
            self.last_refresh = mono()
            self.refresh.set()


def log_error(where, e):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {where}: {type(e).__name__}: {e}\n")
    except Exception:
        pass


def nist_loop(st):
    failures = 0
    while st.running:
        try:
            p = station.get_json(station.BEACON_LAST)["pulse"]
            val = p.get("outputValue") or ""
            if not re.fullmatch(r"[0-9A-Fa-f]{128}", val):
                raise ValueError("NIST outputValue is not 128 hex characters")
            ts = station.parse_gh_time(p["timeStamp"])
            with st.lock:
                if p["pulseIndex"] != st.nist["index"]:
                    st.nist.update(index=p["pulseIndex"], time=ts, value=val.upper(), changed=mono())
                st.nist.update(ok=True, err="")
            failures = 0
            age = (station.now_utc() - ts).total_seconds()     # pulse T is posted about 70-90 s after T
            wait = (135 - age) if age < 135 else 5.0 if age < 300 else min(60.0, age / 10)
            wait = max(5.0, wait)
        except Exception as e:
            failures += 1
            with st.lock:
                st.nist.update(ok=False, err=type(e).__name__)
            wait = min(60.0, 15.0 * failures)
        st_sleep(st, wait, use_refresh=False)


def github_loop(st):
    token = station.gh_token()
    with st.lock:
        st.gh["token"] = bool(token)
    known, since = {}, None
    while st.running:
        interval = 90 if token else 180
        try:
            page, newest = 1, since
            while True:                                  # sync everything that changed since the last poll
                path = (f"/repos/{st.repo}/issues?state=all&sort=updated&direction=asc&per_page=100&page={page}"
                        + (f"&since={since}" if since else ""))
                batch = station.gh("GET", path, token=token) or []
                for it in batch:
                    if "pull_request" in it:
                        continue
                    m = message_from_issue(it)
                    if m:
                        known[it["number"]] = m
                    else:
                        known.pop(it["number"], None)
                    newest = max(newest or "", it.get("updated_at") or "")
                if len(batch) < 100 or page >= 50:
                    break
                page += 1
            since = newest or since
            robot = None
            try:
                runs = station.gh("GET", f"/repos/{st.repo}/actions/workflows/robot.yml/runs?per_page=1", token=token)
                r = (runs or {}).get("workflow_runs") or []
                if r and r[0].get("updated_at"):
                    robot = {"when": station.parse_gh_time(r[0]["updated_at"]), "status": r[0].get("status"),
                             "conclusion": r[0].get("conclusion")}
            except Exception:
                pass
            msgs = sorted(known.values(), key=lambda m: m["number"], reverse=True)
            with st.lock:
                st.gh.update(ok=True, published=True, messages=msgs, robot=robot, good=mono(), err="")
                st.check_alarm()
        except station.CheckLater as e:
            s = str(e)
            if "HTTP 401" in s and token:
                token = None                              # the token was rejected; the repository is public anyway
            short = ("TOKEN REJECTED, USING PUBLIC ACCESS" if "HTTP 401" in s else
                     "RATE LIMITED, WAITING" if ("HTTP 403" in s or "HTTP 429" in s) else
                     "NOT FOUND" if "HTTP 404" in s else "NO CONNECTION" if "reach" in s else s)
            with st.lock:
                st.gh.update(ok=False, err=short)
                if "HTTP 404" in s:
                    st.gh["published"] = False
        except Exception as e:                           # never let the poller die quietly
            log_error("github", e)
            with st.lock:
                st.gh.update(ok=False, err=f"INTERNAL {type(e).__name__}")
        st_sleep(st, interval)


def st_sleep(st, seconds, use_refresh=True):
    end = mono() + seconds
    while st.running and mono() < end:
        if use_refresh and st.refresh.is_set():
            st.refresh.clear()
            return
        time.sleep(0.2)


# ---------------------------------------------------------------- demo data
def demo_messages(t, now):
    """A believable inbox that evolves: a new message every 15 s, and a fake HIT after 25 s."""
    rnd = random.Random(7)
    msgs = []
    base = now - dt.timedelta(days=3)
    for n in range(1, 9):
        created = base + dt.timedelta(hours=n * 8, minutes=rnd.randint(0, 59))
        target = created + dt.timedelta(hours=rnd.randint(2, 30) + (40 if n >= 7 else 0))
        verdict = "miss" if target < now else "pending"
        if n == 4:
            verdict = "too late"
        if n == 6:
            verdict, target = "unreadable", None
        msgs.append({"number": n, "created": created, "target": target, "verdict": verdict})
    extra = int(t // 15)
    for k in range(extra):
        msgs.append({"number": 9 + k, "created": now - dt.timedelta(seconds=t - 15 * (k + 1)),
                     "target": now + dt.timedelta(hours=3 + k, minutes=17),
                     "verdict": "new" if k == extra - 1 else "pending"})
    if t >= 25:
        msgs.append({"number": 99, "created": now - dt.timedelta(hours=2), "target": now - dt.timedelta(minutes=1),
                     "verdict": "HIT"})
    return sorted(msgs, key=lambda m: m["number"], reverse=True)


def demo_tick(st, t):
    with st.lock:
        now = dt.datetime.now(UTC)
        st.gh.update(ok=True, published=True, messages=demo_messages(t, now), good=mono(), err="",
                     robot={"when": now - dt.timedelta(minutes=4), "status": "completed", "conclusion": "success"})
        if st.nist["value"] is None:
            rnd = random.Random(int(time.time() // 60))
            st.nist.update(ok=True, index=2040000 + int(time.time() // 60) % 1000,
                           time=now.replace(second=0, microsecond=0) - dt.timedelta(seconds=60),
                           value="".join(rnd.choice("0123456789ABCDEF") for _ in range(128)), changed=mono())
        st.check_alarm()


# ---------------------------------------------------------------- drawing helpers
def frame_box(cv, x, y, w, h, title=None, color=STEEL, title_color=None, lo=None):
    lo = lo or STEEL_LO
    cv.put(x, y, "╭" + "─" * (w - 2) + "╮", fg=color)
    for yy in range(y + 1, y + h - 1):
        cv.put(x, yy, "│", fg=color)
        cv.put(x + w - 1, yy, "│", fg=lo)
    cv.put(x, y + h - 1, "╰" + "─" * (w - 2) + "╯", fg=lo)
    if title:
        title = title[: max(0, w - 8)]
        cv.put(x + 2, y, "┤ ", fg=color)
        cv.put(x + 4, y, title, fg=title_color or STEEL_HI)
        cv.put(x + 4 + len(title), y, " ├", fg=color)


def plate(cv, x, y, w, text, color, ink):
    cv.put(x, y, " " * w, bg=color)
    text = text[:w]
    cv.put(x + (w - len(text)) // 2, y, text, fg=ink, bg=color)


def row_width(s=1):
    return 98 * s - s                                    # YEAR MON DAY  HOUR:MIN, without the last digit's gap


def time_row(cv, x, y, when, lit, ghost, plate_color, label, blink=False, lamp=False, s=1):
    """One LED row: YEAR MON DAY  HH:MM (24-hour, UTC), then a label plate underneath.
    lamp=True lights every segment and dot, like a display's power-on lamp test."""
    if lamp:
        year, mon, day, hour, minute = "8888", "###", "88", "88", "88"
    elif when:
        year, mon, day = "%04d" % when.year, MONTHS[when.month - 1], "%02d" % when.day
        hour, minute = "%02d" % when.hour, "%02d" % when.minute
    else:
        year, mon, day, hour, minute = "----", "---", "--", "--", "--"
    cx = x
    cx += draw_digits(cv, cx, y, year, lit, ghost, s) + 2 * s
    cx += draw_dots(cv, cx, y, mon, lit, ghost, s=s) + 2 * s
    cx += draw_digits(cv, cx, y, day, lit, ghost, s) + 4 * s
    cx += draw_digits(cv, cx, y, hour, lit, ghost, s)
    on = lit if (lamp or not blink or int(time.time() * 2) % 2 == 0) else ghost
    draw_colon(cv, cx, y, on if (when or lamp) else ghost, s)
    cx += 2 * s
    draw_digits(cv, cx, y, minute, lit, ghost, s)
    plate(cv, x, y + 4 * s, row_width(s), label, plate_color, mix(lit, (255, 255, 255), 0.35))


def circuits_size(s=1):
    return row_width(s) + 7, 3 + 3 * (4 * s + 2)        # 104 x 21 (s=1), 201 x 33 (s=2)


def hits_reported(st):
    return sum(1 for m in st.gh["messages"] if m["verdict"] == "HIT")


def draw_title(cv, x, y, w, st, t):
    shift = t * 0.05
    tw = draw_dots(cv, x, y, "ANTITELEPHONE", (0, 0, 0), None,
                   colfn=lambda px: gradient(pingpong(px / 156 + shift)))
    room = w - tw - 2                                     # space to the right of the big title
    status = "DEMO MODE  ·  SIMULATED DATA" if st.demo else "RECEIVER ONLINE"
    sub = "OPERATION ANTITELEPHONE  ·  " + status
    if len(sub) > room:
        sub = status if len(status) <= room else ("DEMO MODE" if st.demo else "ONLINE")
    repo = "github.com/" + st.repo
    if len(repo) > room:
        repo = st.repo if len(st.repo) <= room else ""
    cv.put(x + tw + 2, y + 1, sub[: max(0, room)], fg=AMBER if st.demo else TEXT)
    cv.put(x + tw + 2, y + 2, repo, fg=DIM)
    hits = hits_reported(st)
    label = "HITS REPORTED"
    cx = x + w - 3 * (SEG_W + 1)
    if cx > x + tw + 2 + max(len(sub), len(repo)) + 2:
        draw_digits(cv, cx, y, "%03d" % min(hits, 999), RED if hits else mix(RED, RED_GHOST, 0.55), RED_GHOST)
        cv.put(cx + 20 - len(label), y + 4, label, fg=DIM)


def draw_title_line(cv, x, y, w, st, t):
    """One-row title for medium windows."""
    name = "ANTITELEPHONE"
    for i, c in enumerate(name):
        cv.put(x + i * 2, y, c, fg=gradient(pingpong(i / 22 + t * 0.05)))
    sub = "  OPERATION ANTITELEPHONE  ·  " + ("DEMO MODE" if st.demo else "RECEIVER ONLINE")
    cv.put(x + len(name) * 2, y, sub, fg=AMBER if st.demo else TEXT)
    hits = "HITS REPORTED %03d" % min(hits_reported(st), 999)
    cv.put(x + w - len(hits), y, hits, fg=RED if hits_reported(st) else DIM)


def draw_circuits(cv, x, y, st, now, t, s=1):
    w, h = circuits_size(s)
    cv.fill(x, y, w, h, PANEL, scan=False)
    frame_box(cv, x, y, w, h, "TEMPORAL DISPLAY", color=STEEL)
    hx = x + 3
    heads = [("YEAR", 28 * s, 2 * s), ("MONTH", 18 * s, 2 * s), ("DAY", 14 * s, 4 * s), ("HOUR", 14 * s, 0),
             ("", 2 * s, 0), ("MIN", 14 * s, 0)]
    cx = hx
    for name, width, gap in heads:
        cv.put(cx + (width - len(name)) // 2, y + 1, name, fg=DIM, bg=PANEL)
        cx += width + gap
    upcoming = sorted(m["target"] for m in st.gh["messages"]
                      if m["target"] and m["target"] > now and m["verdict"] in ("pending", "new"))
    nxt = upcoming[0] if upcoming else None
    last = max((m["created"] for m in st.gh["messages"]), default=None)
    boot = t < 1.4                                        # lamp test: every segment lit for a moment
    if boot:
        labels = ["SELF TEST"] * 3
    else:
        labels = ["NEXT TARGET  ·  UTC" if nxt else "NO UPCOMING TARGETS",
                  "STATION CLOCK  ·  UTC  ·  %02d s" % now.second,
                  "LAST MESSAGE RECEIVED  ·  UTC" if last else "NO MESSAGES YET"]
    step = 4 * s + 2
    time_row(cv, hx, y + 2, nxt, RED, RED_GHOST, RED_PLATE, labels[0], lamp=boot, s=s)
    time_row(cv, hx, y + 2 + step, now, GREEN, GREEN_GHOST, GREEN_PLATE, labels[1], blink=True, lamp=boot, s=s)
    time_row(cv, hx, y + 2 + 2 * step, last, AMBER, AMBER_GHOST, AMBER_PLATE, labels[2], lamp=boot, s=s)
    return w, h


BEACON_H = 10


def beacon_timing(st):
    """(seconds until the next pulse is expected, overdue?) from the pulse's own timestamp."""
    n = st.nist
    if not n["time"]:
        return None, False
    age = (station.now_utc() - n["time"]).total_seconds()
    left = 135 - age                                      # next pulse: 60 s later, posted about 75 s after its time
    return max(0, left), left < -25


def draw_beacon(cv, x, y, w, st, t, h=BEACON_H):
    cv.fill(x, y, w, h, PANEL, scan=False)
    n = st.nist
    idx = "#{:,}".format(n["index"]) if n["index"] else "----"
    frame_box(cv, x, y, w, h, f"NIST RANDOMNESS BEACON  ·  PULSE {idx}", color=STEEL, title_color=CYAN)
    val = n["value"] or ""
    age = mono() - n["changed"] if n["changed"] is not None else 99
    rnd = random.Random(int(t * 12))
    reveal = 128 if age > 1.6 else int(age / 1.6 * 128)
    tall = h >= BEACON_H
    hex_rows = 4 if tall else max(0, min(4, h - 3))
    r0 = 2 if tall else 1
    for row in range(hex_rows):
        line_x = x + 3
        for g in range(4):
            for k in range(8):
                i = row * 32 + g * 8 + k
                if line_x < x + w - 2:
                    if val and i < reveal:
                        cv.put(line_x, y + r0 + row, val[i], fg=CYAN, bg=PANEL)
                    elif val:
                        cv.put(line_x, y + r0 + row, rnd.choice("0123456789ABCDEF"), fg=CYAN_DIM, bg=PANEL)
                    else:
                        cv.put(line_x, y + r0 + row, "·", fg=FAINT, bg=PANEL)
                line_x += 1
            line_x += 1
    fx = x + 3 + 36 + 2
    if tall and val and fx + 32 <= x + w - 2:            # the 512 bits as an entropy field
        bits = bin(int(val, 16))[2:].zfill(512)
        pix = [[(CYAN if bits[r * 32 + c] == "1" and (r * 32 + c) < reveal * 4 else CYAN_GHOST) for c in range(32)]
               for r in range(16)]
        cv.pixels(fx, y + 1, pix)
    left, overdue = beacon_timing(st)
    if n["ok"] is False:
        status, col = "LINK DOWN (%s) " % n["err"][:14], AMBER
    elif overdue:
        status, col = "PULSE OVERDUE ", AMBER
    elif left is not None:
        status, col = "NEXT PULSE ~%2ds " % left, TEXT
    else:
        status, col = "LINKING... ", DIM
    sy = y + 7 if tall else y + h - 2
    room = min(36, w - 5)
    bar_w = max(0, room - len(status) - 2)
    done = int(bar_w * (1 - (left or 0) / 60)) if left is not None and not overdue else (bar_w if overdue else 0)
    done = max(0, min(bar_w, done))
    cv.put(x + 3, sy, status[:room], fg=col, bg=PANEL)
    if bar_w >= 4:
        cv.put(x + 3 + len(status), sy, "▕" + "█" * done + "░" * (bar_w - done) + "▏",
               fg=AMBER if overdue else CYAN_DIM, bg=PANEL)
    if tall:
        when = n["time"].strftime("%Y-%m-%d %H:%M UTC") if n["time"] else "--"
        cv.put(x + 3, y + 8, f"pulse time {when}"[:room], fg=DIM, bg=PANEL)
        extra = ["a new random value every 60 seconds", "nobody can know it in advance",
                 "the code a future sender must quote", "signed and chained by NIST"]
        for i, s in enumerate(extra[: max(0, h - BEACON_H)]):
            cv.put(x + 3, y + 9 + i, s[:room], fg=FAINT, bg=PANEL)


def draw_scope(cv, x, y, w, st, t, h=7):
    cv.fill(x, y, w, h, SCOPE_BG, scan=False)
    frame_box(cv, x, y, w, h, "TEMPORAL INTERFERENCE MONITOR", color=STEEL, title_color=GREEN)
    cw, ch_ = w - 4, max(1, h - 3)
    pw, ph = cw * 2, ch_ * 4
    grid = [[0] * cw for _ in range(ch_)]
    a = st.alarm
    hit = bool(a and a.get("kind") == "HIT")
    amp = (6.5 if hit else 1.6) * max(1.0, ph / 24)
    prev = None
    for px in range(pw):
        u = px + t * 22
        v = (math.sin(u * 0.21) * 0.6 + math.sin(u * 0.047 + 1.3) * 0.9 + math.sin(u * 0.83) * 0.25) * amp
        k = int(u) % 4096
        v += _NOISE[k] * max(1.0, ph / 24)
        if _SPIKE[k]:
            v += _SPIKE_DIR[k] * max(1.0, ph / 24)
        yv = max(0, min(ph - 1, int(round(ph / 2 + v))))
        ys = [yv] if prev is None else range(min(prev, yv), max(prev, yv) + 1)
        for yy in ys:
            bit = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]][yy % 4][px % 2]
            grid[yy // 4][px // 2] |= bit
        prev = yv
    color = RED if hit else GREEN
    for r in range(ch_):
        for c in range(cw):
            b = grid[r][c]
            if b:
                cv.put(x + 2 + c, y + 1 + r, chr(0x2800 + b), fg=color, bg=SCOPE_BG)
            elif (c % 8 == 0 and r % 2 == 1) or (r == ch_ // 2 and c % 2 == 0):
                cv.put(x + 2 + c, y + 1 + r, "·", fg=(18, 84, 38), bg=SCOPE_BG)
    g = st.gh
    if hit:
        msg, col = "!!! SIGNAL MATCH REPORTED !!!", RED
    elif g["published"] is False:
        msg, col = "STANDING BY  ·  THE STATION IS NOT ONLINE YET", AMBER
    elif g["ok"] is False or (g["good"] is not None and mono() - g["good"] > 600 and not st.demo):
        msg, col = "NO FRESH DATA  ·  GITHUB LINK DOWN", AMBER
    else:
        msg, col = "NO SIGNAL FROM THE FUTURE DETECTED  ·  BACKGROUND NOMINAL", mix(GREEN, (0, 0, 0), 0.25)
        if len(msg) > w - 6:
            msg = "NO FUTURE SIGNAL  ·  NOMINAL"
    cv.put(x + 3, y + h - 2, msg[: w - 6], fg=col, bg=SCOPE_BG)


def draw_station(cv, x, y, w, h, st, now):
    def p(xx, yy, text, **kw):                            # never draw past the panel's right border or bottom
        if yy < y + h - 1:
            cv.put(xx, yy, text[: max(0, x + w - 2 - xx)], **kw)

    cv.fill(x, y, w, h, PANEL, scan=False)
    frame_box(cv, x, y, w, h, "INCOMING TRANSMISSIONS", color=STEEL, title_color=AMBER)
    g = st.gh
    msgs = g["messages"]
    line = y + 1
    if g["published"] is False:
        p(x + 3, line, "STATION NOT PUBLISHED YET", fg=AMBER, bg=PANEL)
        p(x + 3, line + 1, "waiting for the repository to go online", fg=DIM, bg=PANEL)
        p(x + 3, line + 2, "clocks and beacon keep running", fg=DIM, bg=PANEL)
        return
    if g["ok"] is None and not msgs:
        p(x + 3, line, "CONTACTING GITHUB...", fg=DIM, bg=PANEL)
        return
    counts = {}
    for m in msgs:
        counts[m["verdict"]] = counts.get(m["verdict"], 0) + 1
    stats = [("RECEIVED", len(msgs), TEXT), ("HITS", counts.get("HIT", 0), RED if counts.get("HIT") else DIM),
             ("PENDING", counts.get("pending", 0) + counts.get("new", 0), CYAN),
             ("MISSES", sum(counts.get(k, 0) for k in ("miss", "too late", "invalid", "unreadable", "void")), DIM)]
    cx = x + 3
    for name, val, col in stats:
        if cx + len(name) + len(str(val)) + 1 > x + w - 2:
            break
        p(cx, line, name, fg=DIM, bg=PANEL)
        p(cx + len(name) + 1, line, str(val), fg=col, bg=PANEL)
        cx += len(name) + len(str(val)) + 4
    age = mono() - g["good"] if g["good"] is not None else None
    if g["ok"] is False:
        p(x + 3, line + 1, "GITHUB: " + g["err"], fg=AMBER, bg=PANEL)
    elif age is not None and age > 600 and not st.demo:
        p(x + 3, line + 1, f"DATA IS {int(age // 60)} MIN OLD", fg=AMBER, bg=PANEL)
    elif g["robot"]:
        r = g["robot"]
        mins = int((now - r["when"]).total_seconds() // 60)
        span_ = f"{mins} min" if mins < 120 else (f"{mins // 60} h" if mins < 2880 else f"{mins // 1440} days")
        stale = mins > 130                                # hourly runs plus GitHub's delays
        ok = r["conclusion"] in ("success", None) and not stale
        mark = "✔" if ok else "✘"
        text = f"SILENT FOR {span_}: check the Actions tab" if stale else \
            f"last run {span_} ago  {mark} {r['conclusion'] or r['status']}"
        p(x + 3, line + 1, "ROBOT", fg=DIM, bg=PANEL)
        p(x + 9, line + 1, text, fg=GREEN if ok else AMBER, bg=PANEL)
    p(x + 3, line + 2, "─" * (w - 6), fg=STEEL_LO, bg=PANEL)
    iw = w - 6
    wide, tiny = iw >= 58, iw < 43                        # tiny: drop the SENT column so RESULT always fits
    tfmt, dash = ("%Y-%m-%d %H:%M", "       --       ") if wide else ("%m-%d %H:%M", "    --     ")
    arrow = "  →  " if wide else " → "
    col0 = 6
    col1 = 6 if tiny else 6 + len(dash) + len(arrow)
    vx = col1 + len(dash) + (1 if tiny else 2)
    p(x + 3, line + 3, "NO.", fg=DIM, bg=PANEL)
    if not tiny:
        p(x + 3 + col0, line + 3, "SENT (UTC)", fg=DIM, bg=PANEL)
    p(x + 3 + col1, line + 3, "TARGET" if tiny else "TARGET (UTC)", fg=DIM, bg=PANEL)
    p(x + 3 + vx, line + 3, "RESULT", fg=DIM, bg=PANEL)
    short = {"check by hand": "CHECK", "too late": "LATE", "unreadable": "NO TARGET"}
    for i, m in enumerate(msgs[: max(0, h - 6)]):
        yy = line + 4 + i
        tgt = m["target"].strftime(tfmt) if m["target"] else dash
        verdict = m["verdict"].upper() if wide else short.get(m["verdict"], m["verdict"].upper())
        row = "#%-4d %s" % (m["number"], tgt) if tiny else \
            "#%-4d %s%s%s" % (m["number"], m["created"].strftime(tfmt), arrow, tgt)
        p(x + 3, yy, row, fg=TEXT if m["verdict"] in ("new", "pending", "HIT") else DIM, bg=PANEL)
        p(x + 3 + vx, yy, verdict, fg=VERDICT_COLOR.get(m["verdict"], DIM), bg=PANEL)
    if not msgs:
        p(x + 3, line + 4, "no messages yet. the channel is open.", fg=DIM, bg=PANEL)


def draw_footer(cv, y, st, t):
    w = cv.w
    cv.put(0, y, " " * w, bg=FOOT_BG)
    dot = "●" if int(t * 2) % 2 == 0 else "○"
    up = int(mono() - st.started)
    _, overdue = beacon_timing(st)
    nist_ok = st.nist["ok"] and not overdue
    g = st.gh
    gh_ok = g["ok"] and (st.demo or (g["good"] is not None and mono() - g["good"] < 600))
    items = [(f" {dot} RECEIVER ONLINE", GREEN), ("   NIST ", DIM), ("●", GREEN if nist_ok else AMBER),
             ("   GITHUB ", DIM), ("●", GREEN if gh_ok else (AMBER if g["ok"] is not None else DIM)),
             ("   UPTIME %02d:%02d:%02d" % (up // 3600, up // 60 % 60, up % 60), DIM),
             ("   LOCAL " + dt.datetime.now().strftime("%H:%M:%S"), DIM)]
    keys = "[Q] QUIT  [R] REFRESH  [T] TEST ALARM "
    while items and sum(len(tx) for tx, _ in items) + len(keys) + 2 > w:
        items.pop()
    cx = 0
    for text, col in items:
        cv.put(cx, y, text, fg=col, bg=FOOT_BG)
        cx += len(text)
    if cx + len(keys) + 2 <= w:
        cv.put(w - len(keys), y, keys, fg=DIM, bg=FOOT_BG)


def draw_alarm(cv, st, t):
    a = st.alarm
    hit = a["kind"] == "HIT"
    flash = int(t * 2.5) % 2 == 0
    hot = RED if hit else AMBER
    bg = (120, 0, 0) if (hit and flash) else ((90, 60, 0) if flash else (24, 4, 4))
    for yy in range(cv.h):                                # dim everything behind the alarm
        cv.fg[yy] = [dimmed(c, 0.7) for c in cv.fg[yy]]
        cv.bg[yy] = [dimmed(c, 0.6) for c in cv.bg[yy]]
    bw = min(cv.w - 2, max(96, cv.w * 2 // 3))
    bh = min(cv.h - 2, max(14, cv.h // 2))
    x, y = (cv.w - bw) // 2, max(0, (cv.h - bh) // 2)
    cv.fill(x, y, bw, bh, bg, scan=False)
    edge = (255, 255, 255) if flash else hot
    frame_box(cv, x, y, bw, bh, color=edge, lo=edge)
    shift = int(t * 6)                                    # marching warning tape along the top and bottom
    for yy in (y + 1, y + bh - 2):
        for xx in range(x + 1, x + bw - 1):
            cv.put(xx, yy, " ", bg=hot if ((xx + shift) // 3) % 2 == 0 else (0, 0, 0))
    lines = []
    if st.demo:
        lines.append("DEMO MODE  ·  SIMULATED DATA  ·  NOT A REAL SIGNAL")
    if a.get("test"):
        lines += ["ALARM TEST  ·  NOT A REAL SIGNAL", "THIS IS WHAT A REPORTED HIT WILL LOOK AND SOUND LIKE"]
    else:
        if a.get("number") is not None:
            lines.append(f"MESSAGE #{a['number']}" + (f"  ·  TARGET {a['target'].strftime('%Y-%m-%d %H:%M')} UTC"
                                                      if a.get("target") else ""))
        lines.append("THE ROBOT REPORTS THAT THE CODE MATCHES THE BEACON" if hit else
                     "A MESSAGE BREAKS A RULE, BUT ITS CODE MATCHES THE BEACON")
        if not st.demo:
            lines.append(f"verify by hand:  python station.py verify {a['number']}")
    lines.append("[A] ACKNOWLEDGE")
    head = "FUTURE SIGNAL" if hit else "CHECK BY HAND"
    if len(head) * 6 > bw - 4:
        head = "SIGNAL" if hit else "CHECK"
    s = 2 if (len(head) * 12 <= bw - 4 and bh >= 26) else 1
    head_h = 4 * s if len(head) * 6 * s <= bw - 4 else 1
    top = y + 3 + max(0, (bh - 6 - head_h - 1 - len(lines)) // 2)
    if head_h > 1:
        draw_dots(cv, x + (bw - len(head) * 6 * s) // 2, top, head, (255, 255, 255) if hit else AMBER, None, s=s)
    else:
        cv.put(x + (bw - len(head)) // 2, top, head, fg=(255, 255, 255), bg=bg)
    for i, s_ in enumerate(lines):
        s_ = s_[: bw - 4]
        cv.put(x + (bw - len(s_)) // 2, top + head_h + 1 + i, s_, fg=(255, 255, 255), bg=bg)


# ---------------------------------------------------------------- layouts
def render(st, w, h, t, now=None):
    now = now or dt.datetime.now(UTC)
    cv = Canvas(w, h)
    with st.lock:
        if st.alarm and st.alarm.get("test") and mono() - st.alarm["since"] > 15:
            st.alarm = None                               # a test alarm switches itself off
            st.check_alarm()
        if w >= 206 and h >= 52:
            render_big(cv, st, now, t)
        elif w >= 120 and h >= 40:
            render_full(cv, st, now, t)
        elif w >= 108 and h >= 28:
            render_mid(cv, st, now, t)
        else:
            render_compact(cv, st, now, t)
        if st.alarm:
            draw_alarm(cv, st, t)
    return cv


def lower_row(cv, st, now, t, y, lh, with_station):
    """Beacon, signal monitor and (optionally) transmissions side by side along the bottom."""
    w = cv.w
    bw = min(78, w - 4)
    draw_beacon(cv, 2, y, bw, st, t, h=lh)
    rest_x = 2 + bw + 2
    rest_w = w - 2 - rest_x
    if with_station:
        sw = max(52, rest_w // 2) if rest_w >= 52 + 2 + 30 else rest_w
        if sw >= 30:
            draw_station(cv, rest_x, y, sw, lh, st, now)
        rest_x, rest_w = rest_x + sw + 2, rest_w - sw - 2
    if rest_w >= 30:
        draw_scope(cv, rest_x, y, rest_w, st, t, h=lh)


def render_big(cv, st, now, t):
    w, h = cv.w, cv.h
    cw, ch = circuits_size(2)
    lh = max(BEACON_H, min(16, h - 42))
    oy = max(0, (h - 1 - (40 + lh)) // 2)
    draw_title(cv, 2, 1 + oy, w - 4, st, t)
    side = w - (2 + cw + 2) - 2
    draw_circuits(cv, 2, 6 + oy, st, now, t, s=2)
    if side >= 34:
        draw_station(cv, 2 + cw + 2, 6 + oy, side, ch, st, now)
        lower_row(cv, st, now, t, 40 + oy, lh, with_station=False)
    else:
        lower_row(cv, st, now, t, 40 + oy, lh, with_station=True)
    draw_footer(cv, h - 1, st, t)


def render_full(cv, st, now, t):
    w, h = cv.w, cv.h
    cw, ch = circuits_size(1)
    lh = max(BEACON_H, min(14, h - 30))
    oy = max(0, (h - 1 - (28 + lh)) // 2)
    draw_title(cv, 2, 1 + oy, w - 4, st, t)
    draw_circuits(cv, 2, 6 + oy, st, now, t)
    side = w - (2 + cw + 2) - 2
    if side >= 30:
        draw_station(cv, 2 + cw + 2, 6 + oy, side, ch, st, now)
        lower_row(cv, st, now, t, 28 + oy, lh, with_station=False)
    else:
        lower_row(cv, st, now, t, 28 + oy, max(lh, h - 29 - oy), with_station=True)
    draw_footer(cv, h - 1, st, t)


def render_mid(cv, st, now, t):
    w, h = cv.w, cv.h
    cw, ch = circuits_size(1)
    draw_title_line(cv, 2, 0, w - 4, st, t)
    draw_circuits(cv, 2, 1, st, now, t)
    side = w - (2 + cw + 2) - 2
    lh = h - 23
    if side >= 30:
        draw_station(cv, 2 + cw + 2, 1, side, ch, st, now)
        lower_row(cv, st, now, t, 22, lh, with_station=False)
    else:
        lower_row(cv, st, now, t, 22, lh, with_station=True)
    draw_footer(cv, h - 1, st, t)


def render_compact(cv, st, now, t):
    w, h = cv.w, cv.h
    cv.put(2, 1, "ANTITELEPHONE RECEIVER", fg=MAGENTA)
    cv.put(24, 1, "(enlarge the window to at least 108 x 28 for the LED display)"[: max(0, w - 26)], fg=FAINT)
    upcoming = sorted(m["target"] for m in st.gh["messages"] if m["target"] and m["target"] > now
                      and m["verdict"] in ("pending", "new"))
    last = max((m["created"] for m in st.gh["messages"]), default=None)
    fmt = lambda d: d.strftime("%Y %b %d  %H:%M").upper() if d else "---- --- --  --:--"
    rows = [("NEXT TARGET", upcoming[0] if upcoming else None, RED), ("STATION CLOCK", now, GREEN),
            ("LAST MESSAGE RECEIVED", last, AMBER)]
    for i, (label, d, col) in enumerate(rows):
        cv.put(2, 3 + i * 2, fmt(d), fg=col)
        cv.put(24, 3 + i * 2, label + "  (UTC)", fg=DIM)
    n = st.nist
    cv.put(2, 10, ("BEACON  " + ("#{:,}  ".format(n["index"]) + (n["value"] or "")[:32]) if n["index"]
                   else "BEACON  linking...")[: max(0, w - 4)], fg=CYAN)
    y = 12
    if st.gh["published"] is False:
        cv.put(2, y, "STATION NOT PUBLISHED YET  ·  waiting for the repository"[: max(0, w - 4)], fg=AMBER)
    elif st.gh["ok"] is False:
        cv.put(2, y, ("GITHUB: " + st.gh["err"])[: max(0, w - 4)], fg=AMBER)
    for m in st.gh["messages"][: max(0, h - 14)]:
        tgt = m["target"].strftime("%Y-%m-%d %H:%M") if m["target"] else "--"
        cv.put(2, y, ("#%-4d %s -> %s  %s" % (m["number"], m["created"].strftime("%m-%d %H:%M"), tgt,
                                              m["verdict"].upper()))[: max(0, w - 4)],
               fg=VERDICT_COLOR.get(m["verdict"], DIM))
        y += 1
    draw_footer(cv, h - 1, st, t)


def error_canvas(w, h, st, e):
    cv = Canvas(w, h)
    cv.put(2, 1, f"DISPLAY ERROR ({type(e).__name__})  ·  STILL LISTENING  ·  see receiver_error.log", fg=AMBER)
    a = st.alarm
    if a:
        cv.put(2, 3, f"!!! ALARM: {a['kind'].upper()}  MESSAGE #{a.get('number')}  [A] ACKNOWLEDGE !!!", fg=RED)
    return cv


# ---------------------------------------------------------------- terminal plumbing
class Console:
    """Windows console set-up: colours (VT mode), no QuickEdit pauses, keep the PC awake. Restored on exit."""

    def __init__(self, keep_awake=True):
        self.keep_awake, self.saved = keep_awake, []

    def __enter__(self):
        if os.name == "nt":
            try:
                import ctypes
                k = ctypes.windll.kernel32
                hout, hin = k.GetStdHandle(-11), k.GetStdHandle(-10)
                for handle, add, remove in ((hout, 0x0004, 0), (hin, 0x0080, 0x0040)):
                    mode = ctypes.c_uint32()
                    if k.GetConsoleMode(handle, ctypes.byref(mode)):
                        self.saved.append((handle, mode.value))
                        k.SetConsoleMode(handle, (mode.value | add) & ~remove)
                if self.keep_awake:                        # per-process request: no idle sleep while this runs
                    k.SetThreadExecutionState(0x80000000 | 0x00000001)
            except Exception:
                pass
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return self

    def __exit__(self, *a):
        if os.name == "nt":
            try:
                import ctypes
                k = ctypes.windll.kernel32
                for handle, mode in self.saved:
                    k.SetConsoleMode(handle, mode)
                k.SetThreadExecutionState(0x80000000)
            except Exception:
                pass


class Keys:
    def __enter__(self):
        self.old = None
        if os.name != "nt" and sys.stdin.isatty():
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def get(self):
        try:
            if os.name == "nt":
                import msvcrt
                if not msvcrt.kbhit():
                    return None
                c = msvcrt.getwch()
                if c in ("\x00", "\xe0"):                  # arrow / F-key / PgDn prefix: swallow its scan code
                    msvcrt.getwch()
                    return None
                return c.lower()
            import select
            if self.old is not None and select.select([sys.stdin], [], [], 0)[0]:
                c = sys.stdin.read(1)
                if c == "\x1b":                            # escape sequences (arrows etc.): drain and ignore
                    while select.select([sys.stdin], [], [], 0)[0]:
                        sys.stdin.read(1)
                    return None
                return c.lower()
        except Exception:
            return None
        return None

    def __exit__(self, *a):
        if self.old is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def beep_pattern(st, key, cycles=6):
    def run():
        for _ in range(cycles):
            with st.lock:
                a = st.alarm
                if not a or (a.get("number"), a.get("kind"), a.get("test")) != key:
                    return
            try:
                if os.name == "nt":
                    import winsound
                    winsound.Beep(1760, 160)
                    winsound.Beep(1320, 160)
                else:
                    sys.stdout.write("\a")
                    sys.stdout.flush()
            except Exception:
                pass
            time.sleep(0.6)
    threading.Thread(target=run, daemon=True).start()


def run(demo=False, fps=8.0, keep_awake=True):
    repo = station.station_repo() or "unknown/unknown"
    st = State(repo, demo)
    threading.excepthook = lambda a: log_error(f"thread {a.thread.name if a.thread else '?'}", a.exc_value)
    threading.Thread(target=nist_loop, args=(st,), daemon=True, name="nist").start()
    if not demo:
        threading.Thread(target=github_loop, args=(st,), daemon=True, name="github").start()
    out = sys.stdout
    with Console(keep_awake):
        out.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        prev, size, alarm_key, last_beep, last_full = [], None, None, 0.0, mono()
        t0 = mono()
        try:
            with Keys() as keys:
                while True:
                    t = mono() - t0
                    k = keys.get()
                    if k == "q":
                        break
                    if k == "r":
                        st.request_refresh()
                    if k == "t":
                        with st.lock:
                            if not st.alarm:                    # never push a real alarm aside
                                st.alarm = {"kind": "HIT", "number": None, "target": None, "test": True,
                                            "since": mono()}
                    if k == "a":
                        st.ack()
                    if demo:
                        demo_tick(st, t)
                    with st.lock:
                        a = st.alarm
                        key = (a.get("number"), a.get("kind"), a.get("test")) if a else None
                    if key and key != alarm_key:
                        beep_pattern(st, key, cycles=6 if a["kind"] == "HIT" else 1)
                        last_beep = mono()
                    elif key and a["kind"] == "HIT" and not a.get("test") and mono() - last_beep > 300:
                        beep_pattern(st, key)                 # remind every 5 minutes until acknowledged
                        last_beep = mono()
                    alarm_key = key
                    w, h = shutil.get_terminal_size((120, 40))
                    w, h = max(20, w), max(5, h)
                    if (w, h) != size or mono() - last_full > 30:   # repaint fully now and then: heals stray output
                        size, prev, last_full = (w, h), [], mono()
                    try:
                        cv = render(st, w, h, t)
                    except Exception as e:
                        log_error("render", e)
                        cv = error_canvas(w, h, st, e)
                    lines = [cv.ansi_line(y) for y in range(h)]
                    buf = ["\x1b[%d;1H" % (y + 1) + line for y, line in enumerate(lines)
                           if y >= len(prev) or prev[y] != line]
                    prev = lines
                    if buf:
                        out.write("".join(buf))
                        out.flush()
                    time.sleep(max(0.02, 1.0 / fps - (mono() - t0 - t)))
        except KeyboardInterrupt:
            pass
        finally:
            st.running = False
            out.write("\x1b[0m\x1b[?25h\x1b[?1049l")
            out.flush()


def snapshot(path, demo, size, at):
    w, h = size
    st = State(station.station_repo() or "unknown/unknown", demo)
    st.started = mono() - 4321
    if demo:
        demo_tick(st, at)
    else:
        try:
            p = station.get_json(station.BEACON_LAST)["pulse"]
            st.nist.update(ok=True, index=p["pulseIndex"], time=station.parse_gh_time(p["timeStamp"]),
                           value=p["outputValue"].upper())
        except Exception:
            pass
    with st.lock:
        st.nist["changed"] = mono() - 23
    cv = render(st, w, h, max(at, 2.0))
    with open(path, "w", encoding="utf-8") as f:
        f.write(cv.html("receiver %dx%d t=%.0f" % (w, h, at)))
    print(f"wrote {path} ({w}x{h}, t={at})")


def main(argv):
    demo = "--demo" in argv
    if "--snapshot" in argv:
        path = argv[argv.index("--snapshot") + 1]
        size = (160, 48)
        if "--size" in argv:
            a, b = argv[argv.index("--size") + 1].lower().split("x")
            size = (int(a), int(b))
        at = float(argv[argv.index("--at") + 1]) if "--at" in argv else 12.0
        snapshot(path, demo, size, at)
        return
    fps = 8.0
    if "--fps" in argv:
        try:
            fps = max(1.0, min(20.0, float(argv[argv.index("--fps") + 1])))
        except (IndexError, ValueError):
            sys.exit("--fps needs a number, for example --fps 2")
    run(demo, fps, keep_awake="--allow-sleep" not in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
