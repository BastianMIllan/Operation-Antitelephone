#!/usr/bin/env python3
"""
make_banner.py - draws assets/banner.svg, the header image of the Operation Antitelephone README.

    python tools/make_banner.py                     # writes ../assets/banner.svg (next to this script's folder)
    python tools/make_banner.py out.svg             # or wherever you like
    python tools/make_banner.py --frame 3.5 x.svg   # preview: the animation frozen 3.5 s in
    python tools/make_banner.py --still x.svg       # preview: what prefers-reduced-motion viewers see

The name comes from physics. The "tachyonic antitelephone" (Tolman, 1917) is the thought experiment in
which a faster-than-light signal lets you send a reply into your own past. This repository is the
receiving end of such a line, so the banner is drawn as one: an instrument panel whose identity is a
handset with its signal arcs running to the left, backwards along the time axis.

Python 3 standard library only. Every pixel is generated here: the dot-matrix title, the seven-segment
readouts, the beacon hex stream and the CH1 trace. The LED fonts (DOT_FONT, SEGMENTS, SEG_PIXELS) are read
straight out of receiver.py with `ast` (never copied by hand), so the banner and the live receiver screen
are the same instrument; the few glyphs the receiver never needs are added from a small local supplement.

GitHub shows README SVGs as images, so the file has no scripts, no external resources and no fonts for
the title. Motion is plain CSS @keyframes, it stops under prefers-reduced-motion, and the first frame is a
complete picture on its own. Every <text> is at least 13 px, so it stays legible at GitHub's ~880 px.
"""
import ast
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECEIVER = HERE.parent / "receiver.py"
OUT = HERE.parent / "assets" / "banner.svg"

W, H = 1280, 400
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
MIN_TEXT = 13                                            # smallest font size allowed anywhere (viewBox px)

# ------------------------------------------------------------------ palette (the receiver's colours)
BG_A, PANEL = (6, 6, 10), (12, 12, 20)
STEEL, STEEL_HI, STEEL_LO = (92, 94, 112), (170, 174, 196), (48, 49, 62)
TEXT, DIM, FAINT = (210, 212, 225), (136, 138, 158), (100, 102, 122)
RED, RED_GHOST = (255, 52, 28), (46, 10, 8)
GREEN, GREEN_GHOST = (60, 255, 110), (8, 40, 18)
AMBER, AMBER_GHOST = (255, 176, 0), (44, 30, 2)
CYAN, CYAN_GHOST = (0, 229, 255), (0, 34, 42)
MAGENTA, PURPLE, ORANGE = (255, 46, 136), (160, 60, 255), (255, 106, 0)
SCOPE_BG = (2, 18, 8)
GRADIENT = [ORANGE, MAGENTA, PURPLE, CYAN]               # the receiver's title gradient


# ------------------------------------------------------------------ LED fonts, read from receiver.py
def _literal(node, env):
    """Evaluate the small, data-only subset of Python the font tables are written in: literals, names bound
    by a comprehension, range(...) and single-loop list comprehensions. Anything else is refused."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return {_literal(k, env): _literal(v, env) for k, v in zip(node.keys, node.values)}
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_literal(e, env) for e in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_literal(node.operand, env)
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range"
            and not node.keywords):
        return range(*(_literal(a, env) for a in node.args))
    if isinstance(node, ast.ListComp) and len(node.generators) == 1:
        gen = node.generators[0]
        if isinstance(gen.target, ast.Name) and not gen.ifs:
            return [_literal(node.elt, {**env, gen.target.id: v}) for v in _literal(gen.iter, env)]
    raise ValueError(f"{RECEIVER.name} line {getattr(node, 'lineno', '?')}: not a plain data expression")


def read_fonts(path=RECEIVER, names=("DOT_FONT", "SEGMENTS", "SEG_PIXELS")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in names):
            found[node.targets[0].id] = _literal(node.value, {})
    missing = [nm for nm in names if nm not in found]
    if missing:
        sys.exit(f"{path}: could not find {', '.join(missing)}")
    return found["DOT_FONT"], found["SEGMENTS"], found["SEG_PIXELS"]


DOT_FONT, SEGMENTS, SEG_PIXELS = read_fonts()

# Glyphs the receiver's own screen never shows. They only fill gaps: receiver.py stays the source of truth.
SEG_SUPPLEMENT = {"A": "abcefg", "B": "cdefg", "C": "adef", "D": "bcdeg", "E": "adefg", "F": "aefg"}  # hex A b C d E F
DOT_SUPPLEMENT = {}
for _k, _v in SEG_SUPPLEMENT.items():
    SEGMENTS.setdefault(_k, _v)
for _k, _v in DOT_SUPPLEMENT.items():
    DOT_FONT.setdefault(_k, _v)


# ------------------------------------------------------------------ small helpers
def n(v):
    """Compact number for SVG output."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def hexc(c):
    return "#%02x%02x%02x" % c


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_w(s, size, track=0.0):
    return len(s) * size * 0.6 + (len(s) - 1) * track * size


def text(x, y, s, size, track=0.0, cls="", anchor="start", attrs="", body=None):
    """<text> whose width is pinned with textLength, so the layout is identical whichever monospace
    font the viewer has (advance = 0.6 em per character plus `track` em of letter spacing)."""
    assert size >= MIN_TEXT, f"text {s!r} is {size}px, below the {MIN_TEXT}px minimum"
    c = f' class="{cls}"' if cls else ""
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{n(x)}" y="{n(y)}"{c}{a} font-size="{n(size)}" textLength="{n(text_w(s, size, track))}" '
            f'lengthAdjust="spacing"{(" " + attrs) if attrs else ""}>{body if body is not None else esc(s)}</text>')


def dot_text(s, x0, y0, pitch):
    """Dot centres of `s` in the 5x7 font: (lit, ghost). (x0, y0) is the top-left dot centre."""
    lit, ghost = [], []
    for i, ch in enumerate(s):
        if ch not in DOT_FONT:
            raise KeyError(f"no dot-matrix glyph for {ch!r}; add it to DOT_SUPPLEMENT")
        for r, row in enumerate(DOT_FONT[ch].split()):
            for c, bit in enumerate(row):
                (lit if bit == "1" else ghost).append((x0 + (i * 6 + c) * pitch, y0 + r * pitch))
    return lit, ghost


def dots_d(pts):
    """Each dot is a 0.01 px stub; with a round cap it renders as a perfect disc in every renderer
    (true zero-length subpaths are dropped by some)."""
    return "".join(f"M{n(x)} {n(y)}h.01" for x, y in pts)


SKEW = math.tan(math.radians(6.5))


def seg_polys(ch, ox, oy, u, thick=0.86, gap=0.08):
    """Seven-segment glyph built from SEG_PIXELS: each pixel run becomes a bevelled bar.
    The cell is 6u wide and 7u tall, leaning forward a few degrees like a real LED digit."""
    if ch not in SEGMENTS:
        raise KeyError(f"no seven-segment glyph for {ch!r}; add it to SEG_SUPPLEMENT")
    on = SEGMENTS[ch]
    h, g = thick * u / 2, gap * u
    lit, ghost = [], []
    for name, pts in SEG_PIXELS.items():
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if len(set(ys)) == 1:                                        # horizontal bar
            yc, a, b = (ys[0] + .5) * u, (min(xs) - .5) * u + g, (max(xs) + 1.5) * u - g
            poly = [(a, yc), (a + h, yc - h), (b - h, yc - h), (b, yc), (b - h, yc + h), (a + h, yc + h)]
        else:                                                        # vertical bar
            xc, a, b = (xs[0] + .5) * u, (min(ys) - .5) * u + g, (max(ys) + 1.5) * u - g
            poly = [(xc, a), (xc + h, a + h), (xc + h, b - h), (xc, b), (xc - h, b - h), (xc - h, a + h)]
        poly = [(ox + x + SKEW * (7 * u - y), oy + y) for x, y in poly]
        (lit if name in on else ghost).append(poly)
    return lit, ghost


def polys_d(polys):
    return "".join("M" + " ".join(f"{n(x)} {n(y)}" for x, y in p) + "Z" for p in polys)


def seg_text(s, ox, oy, u, pitch=None):
    pitch = pitch or 7 * u
    lit, ghost = [], []
    for i, ch in enumerate(s):
        a, b = seg_polys(ch, ox + i * pitch, oy, u)
        lit += a
        ghost += b
    return polys_d(lit), polys_d(ghost)


def seg_width(s, u, pitch=None):
    """Ink width of a seven-segment string (last cell is 6u wide, plus the forward lean)."""
    pitch = pitch or 7 * u
    return (len(s) - 1) * pitch + 6 * u + SKEW * 7 * u


def arc_d(cx, cy, r, a0, a1):
    """Circular arc from angle a0 to a1 (degrees, SVG orientation: 0 = right, 90 = down)."""
    x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
    x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
    large = 1 if abs(a1 - a0) > 180 else 0
    sweep = 1 if a1 > a0 else 0
    return f"M{n(x0)} {n(y0)}A{n(r)} {n(r)} 0 {large} {sweep} {n(x1)} {n(y1)}"


# ------------------------------------------------------------------ the picture
DX, DY, DW, DH = 40, 54, 1200, 144                       # main display window
TY = 236                                                 # tagline baseline
MY, MH = 278, 88                                         # readout modules: top and height
MODULES = [  # x, width, label, lamp colour, note on the right
    (40, 270, "SIGNALS FROM THE FUTURE", RED, ""),
    (326, 262, "RECEIVER", GREEN, "AT-1"),
    (604, 292, "NIST RANDOMNESS BEACON", CYAN, "60 s"),
    (912, 328, "CH1 INCOMING", GREEN, "TRIG READY"),
]
TITLE = "OPERATION ANTITELEPHONE"
TAGLINE = "A listening station for messages from the future"


def handset(cx, cy, col_body, col_wave):
    """The station mark: a telephone handset seen from the side, its signal arcs running to the LEFT,
    i.e. backwards along the time axis. Drawn from plain geometry, about 34 x 26 px."""
    rot = 28                                              # handset tilt (degrees, clockwise)
    hx = cx + 7                                           # handset centre
    body = (f'<g transform="translate({n(hx)} {n(cy)}) rotate({rot})">'
            f'<path d="M-.6 -7.4C4.6 -5 4.6 5 -.6 7.4" fill="none" stroke="{col_body}" stroke-width="3.3" '
            'stroke-linecap="round"/>'
            f'<rect x="-6.8" y="-11.2" width="8.6" height="5.4" rx="2.2" fill="{col_body}"/>'
            f'<rect x="-6.8" y="5.8" width="8.6" height="5.4" rx="2.2" fill="{col_body}"/>'
            '</g>')
    # arcs centred on the earpiece/mouthpiece face, opening to the left
    fx, fy = hx - 4.5, cy - 1.0
    waves = []
    for i, (r, op) in enumerate(((6.5, 1), (10.5, .72), (14.5, .45))):
        waves.append(f'<path class="wv" style="animation-delay:{n(i * .28)}s" d="{arc_d(fx, fy, r, 145, 215)}" '
                     f'fill="none" stroke="{col_wave}" stroke-opacity="{n(op)}" stroke-width="1.9" '
                     'stroke-linecap="round"/>')
    return body + "".join(waves)


def build(frame=None, still=False):
    rnd = random.Random(1917)          # deterministic: the same SVG on every run (Tolman's year)
    o, d, css = [], [], []             # body, <defs>, <style>

    # ---------------- title geometry: 23 characters on one line, as large as the window allows
    cols = len(TITLE) * 6 - 1
    P = 8.4                                             # dot pitch
    DOT = round(P * .77, 2)                             # dot diameter
    assert (cols - 1) * P + DOT <= DW - 44, "title does not fit the display"
    tx0 = W / 2 - (cols - 1) * P / 2                    # first dot centre
    ty0 = DY + DH / 2 - 3 * P
    t_left, t_right = tx0 - DOT, tx0 + (cols - 1) * P + DOT
    LEG = t_right - t_left                              # one orange -> cyan leg spans the whole title
    lit, ghost = dot_text(TITLE, tx0, ty0, P)

    # ---------------- defs
    def lin(id_, stops, x2=0, y2=1, extra=""):
        st = "".join(f'<stop offset="{off}" stop-color="{col}"{"" if op is None else f" stop-opacity={chr(34)}{op}{chr(34)}"}/>'
                     for off, col, op in stops)
        return f'<linearGradient id="{id_}" x1="0" y1="0" x2="{x2}" y2="{y2}"{extra}>{st}</linearGradient>'

    d.append(lin("bg", [(0, hexc(PANEL), None), (1, hexc(BG_A), None)]))
    d.append(lin("steel", [(0, hexc(STEEL_HI), None), (.5, hexc(STEEL), None), (1, hexc(STEEL_LO), None)]))
    d.append(lin("well", [(0, "#000", None), (.55, "#14151d", None), (1, hexc(mix(STEEL_LO, STEEL, .6)), None)]))
    d.append(lin("gloss", [(0, "#fff", .075), (.47, "#fff", .018), (.5, "#fff", 0)]))
    d.append(lin("lip", [(0, "#000", .75), (1, "#000", 0)]))
    d.append(lin("pulseg", [(0, "#fff", 0), (.62, "#fff", .55), (.8, "#fff", .95), (1, "#fff", 0)], x2=1, y2=0))
    d.append(lin("pulsew", [(0, "#d8f6ff", 0), (.7, "#d8f6ff", .1), (1, "#d8f6ff", 0)], x2=1, y2=0))
    d.append('<radialGradient id="toplight" cx=".5" cy="0" r=".7"><stop offset="0" stop-color="#fff" stop-opacity=".05"/>'
             '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>')
    d.append('<radialGradient id="glass" cx=".5" cy=".45" r=".75"><stop offset="0" stop-color="#0f0d18"/>'
             '<stop offset=".7" stop-color="#07070b"/><stop offset="1" stop-color="#030305"/></radialGradient>')
    stops = "".join(f'<stop offset="{n(i / (len(GRADIENT) - 1))}" stop-color="{hexc(c)}"/>' for i, c in enumerate(GRADIENT))
    d.append(f'<linearGradient id="spectrum" gradientUnits="userSpaceOnUse" x1="{n(t_left)}" y1="0" '
             f'x2="{n(t_left + LEG)}" y2="0" spreadMethod="reflect">{stops}</linearGradient>')
    d.append(f'<radialGradient id="screw" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="{hexc(STEEL_HI)}"/>'
             f'<stop offset=".55" stop-color="{hexc(STEEL)}"/><stop offset="1" stop-color="{hexc(STEEL_LO)}"/></radialGradient>')
    d.append(f'<radialGradient id="lamp" cx=".42" cy=".38" r=".62"><stop offset="0" stop-color="#effff3"/>'
             f'<stop offset=".35" stop-color="{hexc(GREEN)}"/><stop offset="1" stop-color="{hexc(mix(GREEN, (0, 0, 0), .55))}"/>'
             '</radialGradient>')
    d.append(f'<radialGradient id="halo"><stop offset="0" stop-color="{hexc(GREEN)}" stop-opacity=".6"/>'
             f'<stop offset="1" stop-color="{hexc(GREEN)}" stop-opacity="0"/></radialGradient>')
    d.append(f'<radialGradient id="ahalo"><stop offset="0" stop-color="{hexc(AMBER)}" stop-opacity=".9"/>'
             f'<stop offset="1" stop-color="{hexc(AMBER)}" stop-opacity="0"/></radialGradient>')
    d.append('<pattern id="scan" width="8" height="3" patternUnits="userSpaceOnUse">'
             '<rect y="2" width="8" height="1" fill="#000" fill-opacity=".3"/></pattern>')
    d.append(f'<filter id="glow" filterUnits="userSpaceOnUse" x="{DX}" y="{DY}" width="{DW}" height="{DH}" '
             'color-interpolation-filters="sRGB">'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="2" result="a"/>'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="6.5" result="b"/>'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="20" result="c"/>'
             '<feMerge><feMergeNode in="c"/><feMergeNode in="b"/><feMergeNode in="a"/>'
             '<feMergeNode in="SourceGraphic"/></feMerge></filter>')
    d.append('<filter id="glow2" x="-10%" y="-60%" width="120%" height="220%" color-interpolation-filters="sRGB">'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="1.2" result="a"/>'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="4.5" result="b"/>'
             '<feComponentTransfer in="b" result="b2"><feFuncA type="linear" slope=".8"/></feComponentTransfer>'
             '<feMerge><feMergeNode in="b2"/><feMergeNode in="a"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    d.append('<filter id="glow3" x="-60%" y="-60%" width="220%" height="220%" color-interpolation-filters="sRGB">'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="2.2" result="a"/>'
             '<feMerge><feMergeNode in="a"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    d.append(f'<path id="tl" d="{dots_d(lit)}"/>')                    # lit title dots: mask, glow source, hot cores
    d.append(f'<path id="tg" d="{dots_d(ghost)}"/>')                  # unlit title dots
    d.append(f'<mask id="mg" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
             f'<use href="#tg" stroke="#fff" stroke-width="{n(DOT)}" stroke-linecap="round"/></mask>')
    d.append(f'<mask id="ml" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
             f'<use href="#tl" stroke="#fff" stroke-width="{n(DOT)}" stroke-linecap="round"/></mask>')
    d.append(f'<clipPath id="cd"><rect x="{DX}" y="{DY}" width="{DW}" height="{DH}" rx="9"/></clipPath>')

    # ---------------- chassis: steel edge, engraved groove, four screws
    o.append(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="22" fill="url(#bg)" '
             'stroke="url(#steel)" stroke-width="1.5"/>')
    o.append(f'<rect x="1.5" y="1.5" width="{W - 3}" height="{H - 3}" rx="21" fill="url(#toplight)"/>')
    o.append(f'<rect x="10.5" y="10.5" width="{W - 21}" height="{H - 21}" rx="14" fill="none" stroke="#020203"/>'
             f'<rect x="11.5" y="11.5" width="{W - 23}" height="{H - 23}" rx="13" fill="none" stroke="#1e202b"/>')
    for i, (sx, sy) in enumerate([(25, 25), (W - 25, 25), (25, H - 25), (W - 25, H - 25)]):
        a = math.radians(28 + 47 * i)
        dx, dy = 3.1 * math.cos(a), 3.1 * math.sin(a)
        o.append(f'<circle cx="{sx}" cy="{sy}" r="5" fill="url(#screw)" stroke="#05050a"/>'
                 f'<path d="M{n(sx - dx)} {n(sy - dy)}L{n(sx + dx)} {n(sy + dy)}" stroke="#15161d" stroke-width="1.4" '
                 'stroke-linecap="round"/>')

    # ---------------- top strip: maker's plate left, status lamps right
    PY = 40                                                          # plate text baseline
    o.append(handset(64, PY - 4.6, hexc(STEEL_HI), hexc(CYAN)))
    px = 92
    o.append(text(px, PY, "AT-1", 13, .2, "plate"))
    px += text_w("AT-1", 13, .2) + 12
    o.append(f'<path d="M{n(px)} {PY - 11}v13" stroke="{hexc(STEEL_LO)}"/>')
    px += 12
    o.append(text(px, PY, "TACHYONIC ANTITELEPHONE · RECEIVING END", 13, .2, "plate dim"))

    x = W - 50
    for label, col, cls in reversed([("POWER", GREEN, ""), ("BEACON LINK", CYAN, "blink"), ("LISTENING", AMBER, "breathe")]):
        o.append(text(x, PY, label, 13, .2, "plate dim", "end"))
        x -= text_w(label, 13, .2) + 13
        c = f' class="{cls}"' if cls else ""
        o.append(f'<g{c}><circle cx="{n(x)}" cy="{PY - 4.6}" r="6" fill="{hexc(col)}" fill-opacity=".16"/>'
                 f'<circle cx="{n(x)}" cy="{PY - 4.6}" r="2.9" fill="{hexc(col)}"/></g>')
        x -= 30

    # ---------------- main display
    o.append(f'<rect x="{DX - 1.5}" y="{DY - 1.5}" width="{DW + 3}" height="{DH + 3}" rx="10.5" fill="none" '
             'stroke="url(#well)" stroke-width="3"/>')
    o.append(f'<rect x="{DX}" y="{DY}" width="{DW}" height="{DH}" rx="9" fill="url(#glass)"/>')
    o.append('<g clip-path="url(#cd)">')
    ticks = []
    for i in range(61):
        xx = DX + 24 + i * (DW - 48) / 60
        tl = 6 if i % 10 == 0 else 3
        ticks.append(f"M{n(xx)} {DY + 8}v{tl}M{n(xx)} {DY + DH - 8}v{-tl}")
    o.append(f'<path d="{"".join(ticks)}" stroke="{hexc(STEEL)}" stroke-opacity=".3"/>')
    top_y, bot_y = DY + 34, DY + DH - 21
    o.append(text(DX + 24, top_y, "RX · CH1", 13, .14, "tiny", attrs=f'fill="{hexc(GREEN)}" fill-opacity=".85"'))
    bx = DX + 24 + text_w("RX · CH1", 13, .14) + 12
    for i in range(6):
        bh = 3.5 + 2.1 * i
        cls = ' class="flick"' if i == 3 else ""
        o.append(f'<rect x="{n(bx + i * 6)}" y="{n(top_y - bh)}" width="3.6" height="{n(bh)}" rx=".6"{cls} '
                 f'fill="{hexc(GREEN if i < 4 else GREEN_GHOST)}"{"" if i >= 4 else " fill-opacity=" + chr(34) + ".85" + chr(34)}/>')
    o.append(text(DX + DW - 24, top_y, "NIST BEACON SYNC", 13, .14, "tiny", "end",
                  attrs=f'fill="{hexc(CYAN)}" fill-opacity=".8"'))
    o.append(text(DX + 24, bot_y, "MATCH 16 HEX · 64 BIT", 13, .14, "tiny", attrs=f'fill="{hexc(DIM)}"'))
    o.append(text(DX + DW - 24, bot_y, "P(LUCK) = 1 : 18 446 744 073 709 551 616", 13, .14, "tiny", "end",
                  attrs=f'fill="{hexc(DIM)}"'))
    # ghost dots: every unlit cell of the matrix, faintly tinted by the spectrum
    o.append(f'<use href="#tg" stroke="url(#spectrum)" stroke-opacity=".13" stroke-width="{n(DOT)}" stroke-linecap="round"/>')
    # lit dots: the receiver's spectrum flowing through a dot mask; an incoming pulse sweeps right to left
    span = 2 * LEG                                       # one full ping-pong of the reflected gradient
    pulse = (f'<g transform="skewX(-16)"><rect class="pulse" x="{W + 160}" y="0" width="230" height="{H}" '
             'fill="url(#pulseg)"{extra}/></g>')         # plain string: {extra} is filled in below
    o.append(f'<g filter="url(#glow)"><g mask="url(#ml)">'
             f'<rect class="flow" x="{n(t_left)}" y="{n(ty0 - P)}" width="{n(LEG + span + 20)}" height="{n(8 * P)}" '
             'fill="url(#spectrum)"/>' + pulse.format(extra="") + '</g></g>')
    o.append(f'<use href="#tl" stroke="#fff" stroke-opacity=".4" stroke-width="{n(DOT * .36)}" stroke-linecap="round"/>')
    o.append('<g mask="url(#mg)">' + pulse.format(extra=' opacity=".1"') + '</g>')   # unlit LEDs catch the pulse
    o.append(pulse.replace("pulseg", "pulsew").format(extra=""))
    o.append(f'<rect x="{DX}" y="{DY}" width="{DW}" height="{DH}" fill="url(#scan)"/>')
    o.append(f'<rect x="{DX}" y="{DY}" width="{DW}" height="{DH}" fill="url(#gloss)"/>')
    o.append(f'<rect x="{DX}" y="{DY}" width="{DW}" height="12" fill="url(#lip)"/>')
    o.append('</g>')
    o.append(f'<rect x="{DX + .5}" y="{DY + .5}" width="{DW - 1}" height="{DH - 1}" rx="8.5" fill="none" '
             'stroke="#fff" stroke-opacity=".05"/>')
    o.append(f'<path d="M{n(t_left + 40)} {DY + DH + 1.5}H{n(t_right - 40)}" stroke="url(#spectrum)" stroke-width="1.6" '
             'stroke-opacity=".45"/>')
    css.append(f".flow{{animation:flow 24s linear infinite}}@keyframes flow{{to{{transform:translateX({n(-span)}px)}}}}")
    css.append(".pulse{animation:pulse 9s cubic-bezier(.45,0,.55,1) infinite}"
               "@keyframes pulse{0%,8%{transform:translateX(0)}48%,100%{transform:translateX(-2050px)}}")

    # ---------------- tagline, engraved under the display, with a blinking block cursor
    TS, TT = 20, .07
    TL = text_w(TAGLINE, TS, TT)
    CUR_GAP, CUR_W = 6, 11
    block = TL + CUR_GAP + CUR_W
    tx = W / 2 - block / 2
    o.append(text(tx, TY, TAGLINE, TS, TT, "tag"))
    o.append(f'<rect class="cursor" x="{n(tx + TL + CUR_GAP)}" y="{TY - 15}" width="{CUR_W}" height="19" '
             f'fill="{hexc(CYAN)}" filter="url(#glow3)"/>')
    for side in (-1, 1):
        x_in = (tx - 26) if side < 0 else (tx + block + 26)
        x_out = DX + 6 if side < 0 else DX + DW - 6
        gid = "rl" if side < 0 else "rr"
        d.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{n(x_out)}" y1="0" x2="{n(x_in)}" y2="0">'
                 f'<stop offset="0" stop-color="{hexc(STEEL)}" stop-opacity="0"/>'
                 f'<stop offset="1" stop-color="{hexc(STEEL_HI)}" stop-opacity=".75"/></linearGradient>')
        o.append(f'<path d="M{n(x_out)} {TY - 6.5}H{n(x_in)}" stroke="url(#{gid})"/>')
        o.append(f'<path d="M{n(x_in + side * 8)} {TY - 6.5}l{-side * 4} -4l{-side * 4} 4l{side * 4} 4z" '
                 f'fill="{hexc(AMBER)}"/>')
    css.append(".cursor{animation:cursor 1.1s steps(1) infinite}@keyframes cursor{50%{opacity:0}}")

    # ---------------- readout modules: label strip + recessed glass window
    for mx, mw, label, col, note in MODULES:
        o.append(f'<rect x="{mx}" y="{MY - 23}" width="7" height="7" rx="1.5" fill="{hexc(col)}"/>')
        o.append(text(mx + 14, MY - 15.5, label, 13, .14, "lbl"))
        if note:
            o.append(text(mx + mw, MY - 15.5, note, 13, .14, "lbl dim", "end"))
        o.append(f'<rect x="{mx - 1.5}" y="{MY - 1.5}" width="{mw + 3}" height="{MH + 3}" rx="7.5" fill="none" '
                 'stroke="url(#well)" stroke-width="3"/>')
        o.append(f'<rect x="{mx}" y="{MY}" width="{mw}" height="{MH}" rx="6" fill="url(#glass)"/>')

    # A: reported-hits counter (red seven-segment, unlit segments visible like a real display)
    mx, mw = MODULES[0][:2]
    u = 6.8
    oy = MY + (MH - 7 * u) / 2
    lit_d, ghost_d = seg_text("000", mx + 20, oy, u)
    o.append(f'<path d="{ghost_d}" fill="{hexc(RED_GHOST)}"/>')
    o.append(f'<path d="{lit_d}" fill="{hexc(RED)}" filter="url(#glow2)"/>')
    o.append(text(mx + mw - 18, MY + MH / 2 - 3, "REPORTED", 13, .06, "tiny", "end", f'fill="{hexc(DIM)}"'))
    o.append(text(mx + mw - 18, MY + MH / 2 + 15, "HITS", 13, .06, "tiny", "end", f'fill="{hexc(FAINT)}"'))

    # B: receiver lamp, ONLINE, and the year the receiver was switched on
    mx, mw = MODULES[1][:2]
    cx, cy = mx + 31, MY + 30
    o.append(f'<circle cx="{cx}" cy="{cy}" r="24" fill="url(#halo)" class="halo"/>')
    o.append(f'<circle cx="{cx}" cy="{cy}" r="10.5" fill="#031407" stroke="#000" stroke-width="2"/>')
    o.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="url(#lamp)" class="lampc"/>')
    o.append(f'<ellipse cx="{cx - 2.5}" cy="{cy - 3.5}" rx="3.4" ry="2.1" fill="#fff" fill-opacity=".6"/>')
    p2 = 4.75
    ow = 34 * p2
    ol, og = dot_text("ONLINE", mx + mw - 18 - ow, cy - 3 * p2, p2)
    o.append(f'<path d="{dots_d(og)}" stroke="{hexc(GREEN_GHOST)}" stroke-width="3.6" stroke-linecap="round"/>')
    o.append(f'<path d="{dots_d(ol)}" stroke="{hexc(GREEN)}" stroke-width="3.6" stroke-linecap="round" filter="url(#glow2)"/>')
    yu = 3.0
    yr = MY + MH - 12                                                # baseline of the bottom row
    yw = seg_width("2026", yu)
    yl, yg = seg_text("2026", mx + mw - 18 - yw, yr - 7 * yu, yu)
    o.append(f'<path d="{yg}" fill="{hexc(AMBER_GHOST)}"/>')
    o.append(f'<path d="{yl}" fill="{hexc(AMBER)}" filter="url(#glow2)"/>')
    o.append(text(mx + 16, yr, "LISTENING SINCE", 13, .08, "tiny", attrs=f'fill="{hexc(DIM)}"'))

    # C: beacon pulse, a scrolling cyan hex stream over its first 128 bits
    mx, mw = MODULES[2][:2]
    hu = 4.4
    hp = 7 * hu
    pulse_hex = "".join(rnd.choice("0123456789ABCDEF") for _ in range(128))
    for ch in "0123456789ABCDEF":
        a, b = seg_polys(ch, 0, 0, hu)
        d.append(f'<g id="h{ch}"><path d="{polys_d(b)}" fill="currentColor"/><path d="{polys_d(a)}"/></g>')
    gap = hu * 3
    xs, x = [], 0.0
    for i, ch in enumerate(pulse_hex):
        xs.append((x, ch))
        x += hp + (gap if i % 4 == 3 else 0)
    L = x
    win_x, win_w = mx + 14, mw - 28
    uses = [f'<use href="#h{ch}" x="{n(win_x + xx + k * L)}"/>'
            for k in range(2) for xx, ch in xs if k == 0 or xx < win_w + 40]
    hy = MY + 15
    d.append(f'<clipPath id="ch"><rect x="{mx + 3}" y="{MY + 3}" width="{mw - 6}" height="{MH - 6}"/></clipPath>')
    o.append(f'<g clip-path="url(#ch)"><g filter="url(#glow2)"><g class="hex" fill="{hexc(CYAN)}" color="{hexc(CYAN_GHOST)}">'
             f'<g transform="translate(0 {n(hy)})">{"".join(uses)}</g></g></g></g>')
    css.append(f".hex{{animation:hex 160s linear infinite}}@keyframes hex{{to{{transform:translateX({n(-L)}px)}}}}")
    d.append('<linearGradient id="fadeh" x1="0" y1="0" x2="1" y2="0">'
             '<stop offset="0" stop-color="#050508"/><stop offset=".07" stop-color="#050508" stop-opacity="0"/>'
             '<stop offset=".93" stop-color="#050508" stop-opacity="0"/><stop offset="1" stop-color="#050508"/></linearGradient>')
    o.append(f'<rect x="{mx}" y="{MY + 4}" width="{mw}" height="48" fill="url(#fadeh)"/>')
    bits = bin(int(pulse_hex[:32], 16))[2:].zfill(128)
    bp = win_w / 64
    on, off = [], []
    for i, bit in enumerate(bits):
        r, c = divmod(i, 64)
        (on if bit == "1" else off).append((win_x + bp / 2 + c * bp, MY + 64 + r * 7))
    o.append(f'<path d="{dots_d(off)}" stroke="{hexc(CYAN_GHOST)}" stroke-width="3.1" stroke-linecap="round"/>')
    o.append(f'<path d="{dots_d(on)}" stroke="{hexc(CYAN)}" stroke-opacity=".85" stroke-width="3.1" stroke-linecap="round"/>')

    # D: CH1 incoming, a roll-mode scope: a flat line waiting under a dashed trigger level; now and then a
    # blip rolls in from the right edge and crosses it.
    mx, mw = MODULES[3][:2]
    sx, sy, sw, sh = mx + 6, MY + 6, mw - 12, MH - 12
    o.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="3" fill="{hexc(SCOPE_BG)}"/>')
    grid = [f"M{n(sx + i * sw / 10)} {sy}v{sh}" for i in range(1, 10)] + [f"M{sx} {n(sy + j * sh / 4)}h{sw}" for j in (1, 2, 3)]
    o.append(f'<path d="{"".join(grid)}" stroke="{hexc(GREEN)}" stroke-opacity=".09"/>')
    minor = [f"M{n(sx + i * sw / 50)} {n(sy + sh / 2 - 2)}v4" for i in range(1, 50) if i % 5]
    o.append(f'<path d="{"".join(minor)}" stroke="{hexc(GREEN)}" stroke-opacity=".16"/>')
    base_y = sy + sh * .72
    trig_y = sy + sh * .36
    o.append(f'<path d="M{sx} {n(trig_y)}h{sw}" stroke="{hexc(AMBER)}" stroke-opacity=".55" stroke-dasharray="5 4"/>')
    # level markers on the bezel: channel ground on the left, trigger level on the right
    o.append(f'<path d="M{sx} {n(base_y - 4.5)}l6 4.5l-6 4.5z" fill="{hexc(GREEN)}" fill-opacity=".8"/>')
    o.append(f'<circle class="tflash" cx="{sx + sw - 4}" cy="{n(trig_y)}" r="11" fill="url(#ahalo)" opacity="0"/>')
    o.append(f'<path d="M{sx + sw} {n(trig_y - 4.5)}l-6 4.5l6 4.5z" fill="{hexc(AMBER)}"/>')
    step = 2
    npts = int(3 * sw / step)                    # one roll period = three screen widths of samples
    LP = npts * step
    raw = [rnd.gauss(0, 1) for _ in range(npts)]
    sm = [sum(raw[(i + k) % npts] for k in range(-2, 3)) / 5 for i in range(npts)]
    A = base_y - trig_y + 13                      # blip height: clears the trigger level by 13 px
    xb = round(.6 * sw / step) * step             # where the blip sits on the first frame
    ys = []
    for i in range(npts):                         # periodic, so the roll loops seamlessly
        dd = (i * step - xb + LP / 2) % LP - LP / 2
        v = 1.25 * sm[i]
        v += (-A * math.exp(-(dd / 4.2) ** 2) + .34 * A * math.exp(-((dd - 8.5) / 4.6) ** 2)
              - .12 * A * math.exp(-((dd - 17.5) / 5.5) ** 2) + .04 * A * math.exp(-((dd - 27) / 6.5) ** 2))
        ys.append(v)
    pts = [(sx + i * step, base_y + ys[i % npts]) for i in range(npts + sw // step + 3)]
    tr = "M" + "L".join(f"{n(x)} {n(y)}" for x, y in pts)
    d.append(f'<clipPath id="cs"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="3"/></clipPath>')
    d.append(lin("persist", [(0, "#fff", .14), (.82, "#fff", 1)], x2=1, y2=0))
    d.append(f'<mask id="mp" maskUnits="userSpaceOnUse" x="{sx}" y="{sy}" width="{sw}" height="{sh}">'
             f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="url(#persist)"/></mask>')
    o.append(f'<g clip-path="url(#cs)"><g mask="url(#mp)"><g filter="url(#glow2)">'
             f'<path class="trace" d="{tr}" fill="none" stroke="{hexc(GREEN)}" stroke-width="1.6" stroke-linejoin="round"/>'
             '</g></g></g>')
    T = 12.0                                      # seconds per roll period
    css.append(f".trace{{animation:trace {n(T)}s linear infinite}}@keyframes trace{{to{{transform:translateX({-LP}px)}}}}")
    f_in = 100 * (xb + LP - sw) / LP              # % of the period at which the blip peak reaches the right edge
    css.append(f".tflash{{animation:tflash {n(T)}s linear infinite}}@keyframes tflash{{0%,{n(f_in - .3)}%{{opacity:0}}"
               f"{n(f_in + .4)}%{{opacity:1}}{n(f_in + 6)}%,100%{{opacity:0}}}}")

    # ---------------- styles
    css.insert(0, f"text{{font-family:{MONO}}}"
               f".plate{{font-weight:700;fill:{hexc(TEXT)}}}.plate.dim{{fill:{hexc(DIM)};font-weight:600}}"
               f".lbl{{font-weight:700;fill:{hexc(mix(TEXT, DIM, .3))}}}.lbl.dim{{fill:{hexc(FAINT)}}}"
               f".tiny{{font-weight:600}}.tag{{font-weight:500;fill:{hexc(TEXT)}}}")
    css.append(".halo{animation:halo 2.4s ease-in-out infinite}@keyframes halo{50%{opacity:.25}}"
               ".lampc{animation:lampc 2.4s ease-in-out infinite}@keyframes lampc{50%{opacity:.7}}"
               ".blink{animation:blink 1.2s steps(1) infinite}@keyframes blink{50%{opacity:.15}}"
               ".flick{animation:flick 2.7s steps(1) infinite}@keyframes flick{40%{opacity:.2}55%{opacity:1}80%{opacity:.2}}"
               ".breathe{animation:breathe 3s ease-in-out infinite}@keyframes breathe{50%{opacity:.3}}"
               ".wv{animation:wave 2.4s ease-in-out infinite}@keyframes wave{0%,60%,100%{opacity:1}30%{opacity:.2}}")
    reduce = "*{animation:none!important}.pulse{display:none}"
    css.append(f"@media (prefers-reduced-motion:reduce){{{reduce}}}")
    if still:                                   # preview of the reduced-motion picture (not used for the real banner)
        css.append(reduce)
    if frame is not None:                       # preview a moment of the animation (not used for the real banner)
        css.append(f"*{{animation-play-state:paused!important;animation-delay:{-frame}s!important}}")

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            'role="img" aria-labelledby="t d">'
            '<title id="t">Operation Antitelephone</title>'
            '<desc id="d">A listening station for messages from the future. An instrument panel with a dot-matrix '
            'title, a counter of reported signals from the future reading 000, a receiver-online lamp listening '
            'since 2026, a NIST randomness beacon hex stream and a CH1 trace waiting below its trigger level.</desc>'
            f'<style>{"".join(css)}</style><defs>{"".join(d)}</defs>{"".join(o)}</svg>\n')


def main():
    args = sys.argv[1:]
    frame, still = None, False
    if "--frame" in args:                       # python make_banner.py --frame 2.5 preview.svg
        i = args.index("--frame")
        frame = float(args[i + 1])
        del args[i:i + 2]
    if "--still" in args:                       # python make_banner.py --still preview.svg
        args.remove("--still")
        still = True
    out = Path(args[0]) if args else OUT
    svg = build(frame, still)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(svg.encode("utf-8"))        # bytes, so line endings are LF on every OS
    print(f"wrote {out} ({len(svg.encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    main()
