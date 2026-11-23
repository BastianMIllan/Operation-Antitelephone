#!/usr/bin/env python3
"""
station.py - robot and checker for Operation Antitelephone (rules: RULES.md, version 1).

  python station.py verify <issue number or link>   check one message yourself (anyone can run this)
  python station.py value 2026-12-01 00:00          show the NIST beacon code for a minute (UTC), or "not yet"
  python station.py hash RULES.md                   SHA-256 of a file
  python station.py robot                           what the GitHub Actions robot runs (needs GITHUB_TOKEN)

Only Python's standard library is used (Python 3.11 or newer). The robot is a helper; RULES.md decides.
"""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
BUFFER = dt.timedelta(minutes=60)
MIN_CODE = 16
BEACON = "https://beacon.nist.gov/beacon/2.0/pulse/time/{ms}"
BEACON_LAST = "https://beacon.nist.gov/beacon/2.0/pulse/last"
API = "https://api.github.com"
UA = "operation-antitelephone/1"
BOT = "github-actions[bot]"
RECEIPT_MARK = "<!-- station-robot:receipt -->"
VERDICT_MARK = "<!-- station-robot:verdict -->"
TIME_BUDGET = 8 * 60                                    # seconds; the workflow's hard limit is 10 minutes

# ---------------------------------------------------------------- reading a message (RULES.md "How a message is read")
# The word TARGET must not come directly after a letter (Unicode category L). That test is done in code (letter_before),
# because a regex \w class would also count number characters such as U+00BD (one half) or U+216B (Roman twelve).
TARGET_START = re.compile(r"(?i:TARGET)[ \t]*:?[ \t]*[0-9]{4}-[0-9]{2}-[0-9]{2}", re.A)
TARGET_LINE = re.compile(
    r"(?i:TARGET)[ \t]*:?[ \t]*"
    r"(?P<y>[0-9]{4})-(?P<mo>[0-9]{2})-(?P<d>[0-9]{2})"
    r"(?:[ \t]*[Tt][ \t]*|[ \t]+)"                       # 1. a space or the letter T
    r"(?P<h>[0-9]{1,2}):(?P<mi>[0-9]{2})"                # 2. H:MM or HH:MM
    r"(?:[ \t]*:00(?>\.0+)?)?"                           # 3. optionally :00, optionally a dot and ALL its zeros
    r"[ \t]*(?:(?i:UTC|GMT|Z))?"                         # 4. optionally UTC, GMT or Z
    r"[ \t]*=?"                                          # 5. optionally =
    r"[ \t]*(?>(?:0[xX][ \t]*)?)"                        # 6. optionally 0x: if present it is always this part
    r"(?P<code>[0-9A-Fa-f]+)", re.A)                     # 7. the code: the unbroken run of hex characters
# loose scans, used only to flag rule-breaking messages whose code nevertheless matches (never make a HIT by themselves)
LOOSE_HEAD = r"(?:(?i:TARGET)\W{0,3})?([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})\D{1,3}([0-9]{1,2}):([0-9]{2})[\s\S]{0,40}?"
LOOSE = re.compile(LOOSE_HEAD + r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16,128})(?![0-9A-Fa-f])", re.A)
LOOSE_GROUPED = re.compile(LOOSE_HEAD + r"(?<![0-9A-Fa-f])((?:[0-9A-Fa-f]{2,32}[ -]){1,16}[0-9A-Fa-f]{2,32})(?![0-9A-Fa-f])",
                           re.A)

_pulse_cache = {}


class CheckLater(Exception):
    """Something outside our control (network, NIST, GitHub) prevents a decision now. Never turned into a verdict."""


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_gh_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def normalize(text):
    """RULES.md: Cf characters are ignored; tabs and Zs characters count as spaces. Runs of spaces are collapsed
    (the rules allow any number of spaces between parts, so this changes no verdict and keeps matching fast)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(" " if unicodedata.category(c) == "Zs" else c for c in text if unicodedata.category(c) != "Cf")
    return re.sub(r"[ \t]+", " ", text)


def letter_before(text, i):
    return i > 0 and unicodedata.category(text[i - 1]).startswith("L")


def target_starts(text):
    return [m.start() for m in TARGET_START.finditer(text) if not letter_before(text, m.start())]


def on_time(created, target):
    """Created at least 60 minutes before the target. Written without subtraction so year 0001 cannot overflow."""
    return created + BUFFER <= target


def fetch_pulse(target):
    """The v2.0 pulse whose timeStamp is exactly `target`; 'pending' if NIST has not published it yet;
    None (void) if NIST has provably moved past T without a pulse at T, or has served nothing new for a year and T is
    after its last pulse. Raises CheckLater when nothing can be decided now."""
    if target > now_utc() + dt.timedelta(minutes=1):
        return "pending"                                   # the future: no need to ask NIST
    ms = int(target.timestamp() * 1000)
    if ms in _pulse_cache:
        return _pulse_cache[ms]
    try:
        p = get_json(BEACON.format(ms=ms))["pulse"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise CheckLater(f"NIST answered HTTP {e.code}")
        if target > now_utc() - dt.timedelta(minutes=10):
            return "pending"
        try:
            last = parse_gh_time(get_json(BEACON_LAST)["pulse"]["timeStamp"])
        except Exception:
            raise CheckLater("NIST shows nothing for this minute yet, and its latest pulse cannot be read")
        if last < target and now_utc() - last > dt.timedelta(days=365):
            _pulse_cache[ms] = None
            return None                                    # RULES.md: no new pulse for a whole year -> void
        raise CheckLater("NIST shows nothing for this minute yet (beacon delayed or down)")
    except CheckLater:
        raise
    except Exception as e:
        raise CheckLater(f"could not reach NIST ({type(e).__name__})")
    try:
        ts = parse_gh_time(p["timeStamp"])
        out = p["outputValue"]
    except Exception:
        raise CheckLater("NIST sent a pulse in an unexpected format")
    if not re.fullmatch(r"[0-9A-Fa-f]{128}", out or ""):
        raise CheckLater("NIST sent an outputValue that is not 128 hex characters")
    if ts < target:
        raise CheckLater("NIST returned an earlier pulse than the one asked for")
    res = p if ts == target else None          # a LATER pulse means NIST skipped minute T: void
    _pulse_cache[ms] = res
    return res


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def read_target(text, created):
    """Verdict for one message text (already normalized) created at `created`. May raise CheckLater."""
    starts = target_starts(text)
    if not starts:
        return {"verdict": "unreadable", "why": "no TARGET line (the word TARGET followed by a date YYYY-MM-DD)"}
    if len(starts) > 1:
        return {"verdict": "invalid", "why": "more than one TARGET line in one message"}
    g = TARGET_LINE.match(text, starts[0])
    if not g:
        return {"verdict": "unreadable", "why": "the TARGET line does not fit the pattern in RULES.md"}
    try:
        target = dt.datetime(int(g.group("y")), int(g.group("mo")), int(g.group("d")),
                             int(g.group("h")), int(g.group("mi")), tzinfo=dt.timezone.utc)
    except ValueError:
        return {"verdict": "unreadable", "why": "the target is not a real date and time"}
    code = g.group("code").lower()
    rec = {"target": target, "code": code}
    if not on_time(created, target):
        return {**rec, "verdict": "too late", "why": "sent less than 60 minutes before the target"}
    if len(code) < MIN_CODE:
        return {**rec, "verdict": "miss", "why": "the code has fewer than 16 characters"}
    pulse = fetch_pulse(target)
    if pulse == "pending":
        return {**rec, "verdict": "pending", "why": "NIST has not published the target minute yet"}
    if pulse is None:
        return {**rec, "verdict": "void", "why": "NIST skipped this minute, or has stopped publishing"}
    actual = pulse["outputValue"].lower()
    uri = pulse.get("uri") or ""
    rec.update(actual=actual[:min(len(code), 128)], pulse_uri=uri if uri.startswith("https://beacon.nist.gov/") else "")
    if actual.startswith(code):
        return {**rec, "verdict": "HIT", "why": "every character matches the beacon"}
    return {**rec, "verdict": "miss", "why": "the code does not match the beacon"}


def matching_code_hint(text, created):
    """'match' if a loosely written, on-time (date, time, code) matches the beacon; 'pending' if one can't be checked
    yet; otherwise 'none'."""
    state = "none"
    found = list(LOOSE.finditer(text))[:5] + list(LOOSE_GROUPED.finditer(text))[:5]
    for m in found:
        code = re.sub(r"[ -]", "", m.group(6)).lower()
        if len(code) < MIN_CODE:
            continue
        try:
            t = dt.datetime(*map(int, m.groups()[:5]), tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if not on_time(created, t):
            continue
        try:
            p = fetch_pulse(t)
        except CheckLater:
            state = "pending"
            continue
        if p == "pending":
            state = "pending"
        elif isinstance(p, dict) and p["outputValue"].lower().startswith(code):
            return "match"
    return state


def judge_message(body, created, last_edited, transferred=False):
    """The whole judgement for one issue. May raise CheckLater."""
    text = normalize(body)
    if transferred:
        return {"verdict": "invalid", "why": "the issue was moved here from another repository (RULES.md: opened here)"}
    if last_edited is not None:                          # no safety net here: an edit can add anything afterwards
        return {"verdict": "invalid", "why": "the message was edited after it was created (RULES.md: never edited)"}
    rec = read_target(text, created)
    breaks_rule = rec["verdict"] in ("invalid", "unreadable") or \
        (rec["verdict"] == "miss" and rec["why"].startswith("the code has fewer"))
    if breaks_rule:
        hint = matching_code_hint(text, created)
        if hint == "match":
            return {**rec, "verdict": "check by hand",
                    "why": f"a code in this message matches the beacon, but the message breaks a rule ({rec['why']}). "
                           "A human must look at it"}
        if hint == "pending":
            return {**rec, "verdict": "pending",
                    "why": f"under RULES.md this is a miss ({rec['why']}), but it mentions a minute NIST has not "
                           "published yet, so I will look once more after that minute in case its code matches"}
    return rec


# ---------------------------------------------------------------- GitHub access
def gh_token(allow_cli=True):
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok or not allow_cli:
        return tok
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or None
    except Exception:
        return None


def gh(method, path, data=None, token=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise CheckLater(f"GitHub answered HTTP {e.code} for {method} {path}")
    except Exception as e:
        raise CheckLater(f"could not reach GitHub ({type(e).__name__})")


def graphql(query, variables, token):
    res = gh("POST", "/graphql", {"query": query, "variables": variables}, token)
    if not res or res.get("errors"):
        raise CheckLater(f"GitHub GraphQL error: {res.get('errors') if res else 'empty answer'}")
    return res["data"]


FIELDS = ("number state createdAt lastEditedAt body labels(first:30){nodes{name}} "
          "timelineItems(itemTypes:[TRANSFERRED_EVENT],first:1){totalCount}")
# only issues whose result can still change: all open ones, closed ones updated recently, closed ones still pending
LIST_QUERIES = [
    ("open", "issues(first:50,states:[OPEN],after:$after,orderBy:{field:CREATED_AT,direction:ASC})", {}),
    ("recently closed", "issues(first:50,states:[CLOSED],filterBy:{since:$since},after:$after)", {"since": True}),
    ("closed pending", 'issues(first:50,states:[CLOSED],labels:["station: pending"],after:$after)', {}),
]
ONE_QUERY = ("query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){issue(number:$n){"
             + FIELDS + "}}}")


def list_query(selector, with_since):
    var = ",$since:DateTime!" if with_since else ""
    return ("query($owner:String!,$name:String!,$after:String" + var + "){repository(owner:$owner,name:$name){"
            + selector + "{pageInfo{hasNextPage endCursor} nodes{" + FIELDS + "}}}}")


def station_repo():
    try:
        with open(os.path.join(BASE, "station.json"), encoding="utf-8") as f:
            return json.load(f)["repo"]
    except Exception:
        return None


# ---------------------------------------------------------------- the robot
LABELS = {
    "station: received": "c5def5", "station: pending": "fbca04", "station: HIT": "b60205", "station: miss": "cfd3d7",
    "station: too late": "cfd3d7", "station: invalid": "cfd3d7", "station: unreadable": "cfd3d7",
    "station: void": "cfd3d7", "station: check by hand": "d93f0b", "not a message": "ededed",
}
FINAL = {"HIT", "miss", "too late", "invalid", "unreadable", "void", "check by hand"}
CLOSE = {"miss", "too late", "invalid", "unreadable", "void"}


def robot_sign(repo):
    return (f"\n\n<sub>I am the station robot. [RULES.md](https://github.com/{repo}/blob/HEAD/RULES.md) decides; "
            "anyone can check by hand.</sub>")


def label_path(repo, num, label):
    return f"/repos/{repo}/issues/{num}/labels/" + urllib.parse.quote(label, safe="")


def verdict_text(rec):
    v = rec["verdict"]
    head = {"HIT": "**HIT.** This needs human verification before anyone celebrates (RULES.md, \"How anyone can check\").",
            "miss": "**Miss.**", "too late": "**Too late.**", "invalid": "**Invalid.**", "unreadable": "**Unreadable.**",
            "void": "**Void.**", "check by hand": "**Check by hand.**", "pending": "**Pending.**"}[v]
    out = [head, f"Reason: {rec['why']}."]
    if rec.get("actual"):
        out.append(f"NIST code for that minute starts with `{rec['actual']}`." +
                   (f" Pulse: {rec['pulse_uri']}" if rec.get("pulse_uri") else ""))
    if v == "pending":
        out.append("I will check again after NIST publishes that minute.")
    return out


def robot(fake=None):
    """Scan the station's issues once. `fake` replaces GitHub access in tests."""
    started = time.time()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = None
    if not fake:
        if not repo:
            print("GITHUB_REPOSITORY is not set; doing nothing.")
            return
        token = gh_token(allow_cli=False)
        if not token:
            sys.exit("GITHUB_TOKEN is not set; the robot runs only inside GitHub Actions.")
    call = fake.gh if fake else (lambda m, p, d=None: gh(m, p, d, token))
    query = fake.graphql if fake else (lambda q, v: graphql(q, v, token))
    if repo.lower() != (station_repo() or "").lower():
        try:
            is_fork = bool((call("GET", f"/repos/{repo}") or {}).get("fork"))
        except CheckLater:
            is_fork = False
        if is_fork:
            print(f"{repo} is a fork, not the station; doing nothing.")
            return
        sys.exit(f"This repository ({repo}) is not the station named in station.json ({station_repo()}).")
    if unicodedata.unidata_version != "15.0.0":
        print(f"warning: this Python uses Unicode {unicodedata.unidata_version}; RULES.md uses Unicode 15.0")
    owner, name = repo.split("/")
    have = {l["name"] for l in (call("GET", f"/repos/{repo}/labels?per_page=100") or [])}
    for label, color in LABELS.items():
        if label not in have:
            call("POST", f"/repos/{repo}/labels", {"name": label, "color": color})
    since = (now_utc() - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issues = {}
    for what, selector, opts in LIST_QUERIES:
        after = None
        while True:
            variables = {"owner": owner, "name": name, "after": after}
            if opts.get("since"):
                variables["since"] = since
            data = query(list_query(selector, bool(opts.get("since"))), variables)["repository"]["issues"]
            for node in data["nodes"]:
                issues[node["number"]] = node
            if not data["pageInfo"]["hasNextPage"]:
                break
            after = data["pageInfo"]["endCursor"]
    # messages the robot has never answered come first, so a crowd of old pending ones can never delay them
    order = sorted(issues.values(), key=lambda it: ("station: received" in {n["name"] for n in it["labels"]["nodes"]},
                                                     it["number"]))
    summary = {}
    for it in order:
        if time.time() - started > TIME_BUDGET:
            print("time budget used up; the rest waits for the next run")
            break
        try:
            v = handle_issue(it, repo, call)
        except CheckLater as e:
            v = "error"
            print(f"#{it['number']}: nothing decided ({e})")
        except Exception as e:                           # one strange issue must never stop the others
            v = "error"
            print(f"#{it['number']}: skipped after an unexpected problem ({type(e).__name__}: {e})")
        if v:
            summary[v] = summary.get(v, 0) + 1
    line = ", ".join(f"{k}: {n}" for k, n in sorted(summary.items())) or "no new messages"
    print("summary:", line)
    if os.environ.get("GITHUB_STEP_SUMMARY") and not fake:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"Station robot: {line}\n")


def robot_comments(repo, num, call):
    old = call("GET", f"/repos/{repo}/issues/{num}/comments?per_page=100") or []
    return [c.get("body") or "" for c in old if (c.get("user") or {}).get("login") == BOT]


def handle_issue(it, repo, call):
    num = it["number"]
    labels = {n["name"] for n in it["labels"]["nodes"]}
    transferred = it["timelineItems"]["totalCount"] > 0
    if "not a message" in labels:
        return None
    if "station: HIT" in labels:
        if it["lastEditedAt"] or transferred:            # a HIT edited or moved later no longer counts
            why = "edited" if it["lastEditedAt"] else "moved here from another repository"
            call("DELETE", label_path(repo, num, "station: HIT"))
            call("POST", f"/repos/{repo}/issues/{num}/labels", {"labels": ["station: invalid"]})
            call("POST", f"/repos/{repo}/issues/{num}/comments", {"body": f"**Invalid.** This message was {why} "
                 "after the result, so under RULES.md it no longer counts." + robot_sign(repo)})
            return "invalid"
        return None
    if any(f"station: {f}" in labels for f in FINAL):
        return None
    created, edited = parse_gh_time(it["createdAt"]), parse_gh_time(it["lastEditedAt"])
    rec = judge_message(it["body"], created, edited, transferred)
    v = rec["verdict"]
    received = "station: received" in labels
    if v == "pending" and received:
        return "pending"                                 # nothing new to say, and no API call needed
    mine = robot_comments(repo, num, call)               # never repeat a receipt or a verdict (e.g. after a failed write)
    if v == "pending" and any(RECEIPT_MARK in b for b in mine):
        call("POST", f"/repos/{repo}/issues/{num}/labels", {"labels": ["station: received", "station: pending"]})
        return "pending"
    if v != "pending" and any(VERDICT_MARK in b for b in mine):
        call("POST", f"/repos/{repo}/issues/{num}/labels", {"labels": ["station: received", f"station: {v}"]})
        return v
    parts = []
    if not any(RECEIPT_MARK in b for b in mine):
        parts += [RECEIPT_MARK, "**Received.**",
                  f"GitHub creation time: `{created.strftime('%Y-%m-%dT%H:%M:%SZ')}`",
                  f"First seen by this robot: `{now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')}`",
                  "Fingerprint of the message text (SHA-256): "
                  f"`{hashlib.sha256((it['body'] or '').encode('utf-8')).hexdigest()}`"]
        if rec.get("target"):
            parts.append(f"I read: target **{rec['target'].strftime('%Y-%m-%d %H:%M')} UTC**, code `{rec['code'][:128]}`"
                         + (" (shown up to 128 characters)" if len(rec["code"]) > 128 else ""))
        parts.append("")
    if v != "pending":
        parts.append(VERDICT_MARK)
    parts += verdict_text(rec)
    call("POST", f"/repos/{repo}/issues/{num}/comments", {"body": "\n".join(parts) + robot_sign(repo)})
    if "station: pending" in labels and v != "pending":
        call("DELETE", label_path(repo, num, "station: pending"))
    call("POST", f"/repos/{repo}/issues/{num}/labels", {"labels": ["station: received", f"station: {v}"]})
    if v in CLOSE and it.get("state") == "OPEN":
        call("PATCH", f"/repos/{repo}/issues/{num}", {"state": "closed", "state_reason": "completed"})
    print(f"#{num}: {v} ({rec['why']})")
    return v


# ---------------------------------------------------------------- commands for people
def cmd_verify(arg):
    repo = station_repo()
    m = re.search(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([0-9]+)", arg or "") or \
        re.fullmatch(r"\s*#?([0-9]+)\s*", arg or "")
    if not m:
        sys.exit("Give an issue number or link, e.g.:  python station.py verify 12")
    if m.lastindex == 2:
        repo_in, num = m.group(1), int(m.group(2))
        if repo and repo_in.lower() != repo.lower():
            print(f"Note: {repo_in} is not the station ({repo}). Messages count only in the station.")
        repo = repo_in
    else:
        num = int(m.group(1))
    if not repo:
        sys.exit("This copy does not know the station's repository; give the full issue link.")
    token = gh_token()
    try:
        if token:
            owner, name = repo.split("/")
            it = graphql(ONE_QUERY, {"owner": owner, "name": name, "n": num}, token)["repository"]["issue"]
            if not it:
                sys.exit(f"#{num} is not an issue in {repo} (it may be a pull request, or not exist).")
            created, edited, body = parse_gh_time(it["createdAt"]), parse_gh_time(it["lastEditedAt"]), it["body"]
            transferred = it["timelineItems"]["totalCount"] > 0
        else:
            it = gh("GET", f"/repos/{repo}/issues/{num}")
            if it.get("pull_request"):
                sys.exit(f"#{num} is a pull request, not a message.")
            created, edited, body, transferred = parse_gh_time(it["created_at"]), None, it["body"], False
        rec = judge_message(body, created, edited, transferred)
    except CheckLater as e:
        sys.exit(f"Could not decide now: {e}. Try again later.")
    print(f"issue #{num} in {repo}")
    print(f"   created (GitHub)  {iso(created)}")
    print(f"   edited            {('yes, ' + iso(edited)) if edited else ('no' if token else 'NOT CHECKED')}")
    print(f"   transferred in    {('yes' if transferred else 'no') if token else 'NOT CHECKED'}")
    if rec.get("target"):
        print(f"   target            {rec['target'].strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"   code sent         {rec['code']}")
    if rec.get("actual"):
        print(f"   beacon code       {rec['actual']}")
    print(f"\n{rec['verdict'].upper() if rec['verdict'] == 'HIT' else rec['verdict']}: {rec['why']}")
    if not token:
        print("(Not logged in to GitHub, so edits and transfers were NOT checked: look for 'edited' and "
              "'transferred' on the issue page before trusting this result.)")
    if rec["verdict"] == "HIT":
        print("Now check the independent records in RULES.md, 'How anyone can check a claimed hit', step 3.")


def parse_minute(s):
    m = re.search(r"([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[ \t]*[Tt][ \t]*|[ \t]+)([0-9]{1,2}):([0-9]{2})", s, re.A)
    if not m:
        return None
    try:
        return dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def cmd_value(args):
    t = parse_minute(" ".join(args))
    if not t:
        sys.exit("Give a time in UTC like:  python station.py value 2026-12-01 00:00")
    try:
        p = fetch_pulse(t)
    except CheckLater as e:
        sys.exit(f"{iso(t)}: {e}; try again later")
    if p == "pending":
        print(f"{iso(t)}: not yet (the value does not exist publicly until about a minute after that minute)")
    elif p is None:
        print(f"{iso(t)}: NIST skipped this minute (void)")
    else:
        print(f"{iso(t)}: code = {p['outputValue'][:MIN_CODE].lower()}   (pulse {p['uri']})")


def cmd_hash(where):
    try:
        path = where if os.path.isabs(where) or os.path.exists(where) else os.path.join(BASE, where)
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        sys.exit(f"Could not read {where}: {e}")
    print(hashlib.sha256(data).hexdigest())


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    cmds = {"verify": lambda a: cmd_verify(" ".join(a)), "value": cmd_value,
            "hash": lambda a: cmd_hash(a[0] if a else "RULES.md"), "robot": lambda a: robot()}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        return
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
