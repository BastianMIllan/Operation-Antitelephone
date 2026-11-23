#!/usr/bin/env python3
"""
make_preview.py - render the receiver screenshot used in the README (assets/receiver.png) from the real program.

  python tools/make_preview.py [--size 160x48] [--at 12] [--out assets/receiver.png]

It renders one frame of receiver.py in demo mode to HTML, then asks a headless Chromium-based browser (Microsoft Edge or
Google Chrome) to take a screenshot of it. Only Python's standard library is used.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import receiver  # noqa: E402
import station   # noqa: E402

CELL_W, CELL_H = 9, 18                                   # pixels per terminal cell in the screenshot
CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def find_browser():
    for c in CANDIDATES:
        if os.path.isfile(c) or shutil.which(c):
            return c if os.path.isfile(c) else shutil.which(c)
    sys.exit("No Edge or Chrome found for the headless screenshot.")


def page(cv):
    """The frame as HTML with exact cell sizes, so half-block LED pixels line up without gaps."""
    rows = []
    for y in range(cv.h):
        cells = []
        for x in range(cv.w):
            ch, (fr, fg, fb), (br, bg, bb) = cv.ch[y][x], cv.fg[y][x], cv.bg[y][x]
            if ch == "\u2580":                           # draw half blocks as two coloured halves, not as glyphs
                cells.append(f"<i style='background:linear-gradient(rgb({fr},{fg},{fb}) 50%,rgb({br},{bg},{bb}) 50%)'></i>")
            elif ch == "\u2584":
                cells.append(f"<i style='background:linear-gradient(rgb({br},{bg},{bb}) 50%,rgb({fr},{fg},{fb}) 50%)'></i>")
            elif ch == "\u2588":
                cells.append(f"<i style='background:rgb({fr},{fg},{fb})'></i>")
            else:
                text = {"<": "&lt;", ">": "&gt;", "&": "&amp;", " ": "&nbsp;"}.get(ch, ch)
                cells.append(f"<i style='background:rgb({br},{bg},{bb});color:rgb({fr},{fg},{fb})'>{text}</i>")
        rows.append("<div>" + "".join(cells) + "</div>")
    return ("<!doctype html><meta charset=utf-8><style>body{margin:0;background:#06060a}"
            f"div{{display:flex;height:{CELL_H}px}}"
            f"i{{display:block;width:{CELL_W}px;height:{CELL_H}px;font:normal 14px/{CELL_H}px 'Cascadia Mono',Consolas,"
            "'DejaVu Sans Mono',monospace;text-align:center;overflow:hidden;font-style:normal}</style>"
            + "".join(rows))


def main(argv):
    size = (160, 48)
    if "--size" in argv:
        a, b = argv[argv.index("--size") + 1].lower().split("x")
        size = (int(a), int(b))
    at = float(argv[argv.index("--at") + 1]) if "--at" in argv else 12.0
    out = os.path.abspath(argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "assets", "receiver.png"))
    st = receiver.State(station.station_repo() or "unknown/unknown", demo=True)
    st.started = receiver.mono() - 4321
    receiver.demo_tick(st, at)
    with st.lock:
        st.nist["changed"] = receiver.mono() - 23
    cv = receiver.render(st, size[0], size[1], at)
    tmp = tempfile.mkdtemp()
    html_path = os.path.join(tmp, "frame.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page(cv))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([find_browser(), "--headless", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={tmp}",
                    f"--screenshot={out}", f"--window-size={size[0] * CELL_W},{size[1] * CELL_H}",
                    "file:///" + html_path.replace(os.sep, "/")], capture_output=True, timeout=120)
    # the browser's launcher can exit before its background process has written the file, so wait for it
    deadline, last = time.time() + 60, -1
    while time.time() < deadline:
        size_now = os.path.getsize(out) if os.path.exists(out) else -1
        if size_now > 0 and size_now == last:
            break
        last = size_now
        time.sleep(1)
    if not os.path.exists(out):
        sys.exit("The browser did not write the screenshot.")
    print(f"wrote {out} ({size[0]}x{size[1]} cells, {os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1:])
