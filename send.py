#!/usr/bin/env python3
"""
send.py - send a message to Operation Antitelephone (rules: RULES.md).

  python send.py                     asks for the target minute and the code, then sends the message
  python send.py --target "2026-12-01 00:00" --code 0123456789abcdef [--print-only]

It opens GitHub in your browser with the message already filled in; you click the button that creates the issue.
If the GitHub CLI (gh) is installed and logged in, it can also send the message right from this terminal.
Only Python's standard library is used.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
MARGIN = dt.timedelta(minutes=65)       # rules need 60 minutes; 5 more for typing and clicking Submit


def station_repo():
    try:
        with open(os.path.join(BASE, "station.json"), encoding="utf-8") as f:
            repo = json.load(f)["repo"]
    except Exception:
        repo = ""
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repo) or repo.startswith("OWNER/"):
        sys.exit("station.json does not name the station's repository yet, so this copy cannot send.")
    return repo


def parse_target(s):
    m = re.fullmatch(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})(?:\s*[Tt]\s*|\s+)([0-9]{1,2}):([0-9]{2})\s*(?:UTC|utc|Z|z)?\s*", s)
    if not m:
        return None, "Write it like 2026-12-01 00:00 (year-month-day hour:minute, in UTC)."
    try:
        t = dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc)
    except ValueError:
        return None, "That date or time does not exist."
    now = dt.datetime.now(dt.timezone.utc)
    if t <= now:
        return None, "That minute has already passed, so its code is public. Pick a future minute."
    if t < now + MARGIN:
        return None, f"Too soon. The rules need at least 60 minutes. Pick a minute after {(now + MARGIN):%Y-%m-%d %H:%M} UTC."
    return t, None


def parse_code(s):
    c = re.sub(r"\s+", "", s or "")
    c = c[2:] if c[:2].lower() == "0x" else c
    if not re.fullmatch(r"[0-9A-Fa-f]{16,128}", c):
        return None, "The code must be at least 16 characters, each one 0-9 or a-f."
    return c.lower(), None


def ask(prompt, parse):
    while True:
        try:
            value, err = parse(input(prompt))
        except EOFError:
            sys.exit("\nCancelled.")
        if err is None:
            return value
        print("   " + err)


def gh_ready():
    if not shutil.which("gh"):
        return False
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    print_only = "--print-only" in argv
    rest = [a for a in argv if a != "--print-only"]
    args = dict(zip(rest[::2], rest[1::2]))
    repo = station_repo()
    print("\nOperation Antitelephone: send a message")
    print("Read RULES.md first. The code is the first 16 (or more) characters of the NIST beacon")
    print("\"outputValue\" for your target minute, and you must send it at least 60 minutes before that minute.\n")
    if "--target" in args:
        target, err = parse_target(args["--target"])
        if err:
            sys.exit(err)
    else:
        target = ask("Target minute in UTC (for example 2026-12-01 00:00): ", parse_target)
    if "--code" in args:
        code, err = parse_code(args["--code"])
        if err:
            sys.exit(err)
    else:
        code = ask("Code (16 or more characters): ", parse_code)
    line = f"TARGET {target:%Y-%m-%d %H:%M} UTC = {code}"
    title = f"Message for {target:%Y-%m-%d %H:%M} UTC"
    body = line + "\n"
    print(f"\nYour message:  {line}")
    print("Do not edit it after sending: an edited message does not count. To change it, send a new one.\n")
    url = f"https://github.com/{repo}/issues/new?" + urllib.parse.urlencode({"title": title, "body": body})
    if not print_only and gh_ready():
        try:
            yes = input("Send it now from this terminal with your GitHub account (gh)? [y/N] ").strip().lower() == "y"
        except EOFError:
            yes = False
        if yes:
            r = subprocess.run(["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print("Sent:", r.stdout.strip())
                print("The station robot will reply on that page. Good luck.")
                return
            print("gh could not send it:", (r.stderr or r.stdout).strip()[:300])
    print("Open this link, check the text, and click the button that creates the issue:\n")
    print(url + "\n")
    if not print_only:
        try:
            webbrowser.open(url)
        except Exception:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
