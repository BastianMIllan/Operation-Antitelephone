"""Offline tests for station.py and send.py:  python -m unittest discover tests
NIST and GitHub are replaced by fakes, so no network is used."""
import datetime as dt
import os
import sys
import time
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import station  # noqa: E402
import send     # noqa: E402

UTC = dt.timezone.utc
T = dt.datetime(2026, 11, 23, 6, 0, tzinfo=UTC)
T1 = dt.datetime(2026, 11, 23, 6, 1, tzinfo=UTC)
OUT = "92bb00897d889137" + "a" * 112           # fake outputValue for T (first 16 = the real 06:00 code)
OUT1 = "fa17c37f0798d323" + "b" * 112          # fake outputValue for T1
C, F = OUT[:16], OUT1[:16]
SKIPPED = dt.datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
FUTURE = dt.datetime(2099, 1, 1, 0, 0, tzinfo=UTC)
EARLY = T - dt.timedelta(hours=2)
STATE = {"future_published": False}            # lets a test "publish" the 2099 minute


def fake_pulse(target):
    if target == T:
        return {"outputValue": OUT.upper(), "uri": "https://beacon.nist.gov/beacon/2.0/chain/2/pulse/1"}
    if target == T1:
        return {"outputValue": OUT1.upper(), "uri": "https://beacon.nist.gov/beacon/2.0/chain/2/pulse/2"}
    if target == SKIPPED:
        return None
    if target >= FUTURE:
        return {"outputValue": OUT.upper(), "uri": "https://evil.example/x"} if STATE["future_published"] else "pending"
    return {"outputValue": "0" * 128, "uri": "https://beacon.nist.gov/other"}


station.fetch_pulse = fake_pulse


def judge(body, created=EARLY, edited=None, transferred=False):
    return station.judge_message(body, created, edited, transferred)


class Reading(unittest.TestCase):
    CASES = [
        ("TARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("Greetings from 2031-05-05 12:00 UTC.\nTARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("TARGET 2026-11-23T06:00:00.000Z = " + C, "HIT"),
        ("TARGET 2026-11-23 06:00 :00 UTC = " + C, "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = " + OUT[:32].upper(), "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = " + C + "0000000000000000", "miss"),
        ("my target is clear \U0001F680 TARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = 0123456789abcdef", "miss"),
        ("TARGET 2099-01-01 00:00 UTC = 0123456789abcdef", "pending"),
        ("TARGET 2026-11-23 07:00 UTC = 0123456789abcdef", "void"),
        ("TARGET 2026-11-23 06:00 UTC = 92bb0089\u200b7d889137", "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = 0x" + C, "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = 0x " + C, "HIT"),
        ("TARGET 2026-11-23 06:00 " + C.upper(), "HIT"),
        ("TARGET 2026-11-23 06:00 GMT = " + C, "HIT"),
        ("hello\n# TARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("my target 2026-2030 is far.\nTARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("target 2026-11-23 06:00 utc = " + C, "HIT"),
        ("TARGET : 2026-11-23 06:00 = " + C, "HIT"),
        ("TARGET 2026-11-23T06:01Z" + F, "HIT"),
        ("TARGET 2026-11-23 06:01 UTC" + F, "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = " + C + "thanks", "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = " + C[:15], "miss"),
        ("TARGET 2026-11-23 06:00 UTC = " + OUT + "ab", "miss"),
        ("TARGET 2026-11-23t06:00 = " + C, "HIT"),
        ("TARGET\n2026-11-23 06:00 UTC = 1111111111111111\nTARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("TARGETS 2026-11-23 06:00 = 1111111111111111\nTARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("hi\u2028there TARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("TARGET\u20032026-11-23 06:00 UTC = " + C, "HIT"),
        ("TARGET 2026-11-23 06:00:00" + C, "HIT"),
        ("TARGET: 2026-11-23 6:00 Z = " + C, "HIT"),
        ("TARGET 2026-02-30 06:00 UTC = " + C, "unreadable"),
        ("TARGET 2026-11-23 24:00 UTC = " + C, "unreadable"),
        ("TARGET 2026-11-23 06:00 UTC = " + C[:15] + "0", "miss"),
        ("no target line at all", "unreadable"),
        ("", "unreadable"),
        ("TARGET 2026-11-23 06:00 UTC -> 0123456789abcdef", "unreadable"),
        ("TARGET 2026-11-23 06:00 UTC = 0123456789abcdef\nTARGET 2026-11-23 06:01 UTC = 0123456789abcdef", "invalid"),
        ("\u00e9TARGET 2026-11-23 06:00 UTC = 0123456789abcdef", "unreadable"),
        ("TARGET 0001-01-01 00:00 = 0123456789abcdef", "too late"),            # used to crash (OverflowError)
        ("hello 0001-01-01 00:30 aaaaaaaaaaaaaaaaaaaa", "unreadable"),
        # the safety net: rule-breaking messages whose code matches are flagged for a human
        ("TARGET 2026-11-23 06:00:30 UTC = " + C, "check by hand"),
        ("TARGET 2026-11-23 06:00 EST = " + C, "check by hand"),
        ("TARGET 2026-11-23 06:00+02:00 = " + C, "check by hand"),
        ("TARGET 2026-11-23 06:00 UTC = " + C + "\nTARGET 2026-11-23 06:01 UTC = " + F, "check by hand"),
        ("TARGET 2026-11-23 06:00 UTC -> " + C, "check by hand"),
        ("2026-11-23 06:00 UTC = " + C, "check by hand"),
        ("TARGET 2026-11-23 06:00 (UTC) = " + C, "check by hand"),
        # ...and if the minute they mention is not published yet, they wait instead of being closed
        ("TARGET 2099-01-01 00:00 EST = 0123456789abcdef", "pending"),
        # final-review cases
        ("\u00bdTARGET 2026-11-23 06:00 UTC = 1111111111111111\nTARGET 2026-11-23 06:00 UTC = " + C, "check by hand"),
        ("\u216bTARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("\u00e9TARGET 2026-11-23 06:00 UTC = 1111111111111111\nTARGET 2026-11-23 06:00 UTC = " + C, "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = 0xZZ", "unreadable"),
        ("TARGET 2026-11-23 06:00:00.0092bb00897d889137", "HIT"),
        ("TARGET 2026-11-23 06:00 UTC = 92bb0089 7d889137", "check by hand"),
        ("TARGET 2026-11-23 06:00 UTC = " + C + " (sent from 2031)", "HIT"),
    ]

    def test_cases(self):
        for body, want in self.CASES:
            with self.subTest(body=body):
                self.assertEqual(judge(body)["verdict"], want)

    def test_timing(self):
        line = "TARGET 2026-11-23 06:00 UTC = " + C
        self.assertEqual(judge(line, created=T - dt.timedelta(minutes=60))["verdict"], "HIT")   # exactly 60 min
        self.assertEqual(judge(line, created=T - dt.timedelta(minutes=59, seconds=59))["verdict"], "too late")
        self.assertEqual(judge("TARGET 2026-11-23 06:00 UTC -> " + C, created=T)["verdict"], "unreadable")

    def test_edited_and_transferred_are_invalid_without_alarm(self):
        line = "TARGET 2026-11-23 06:00 UTC = " + C
        self.assertEqual(judge(line, edited=EARLY + dt.timedelta(minutes=1))["verdict"], "invalid")
        self.assertEqual(judge(line, transferred=True)["verdict"], "invalid")

    def test_hostile_spaces_are_fast(self):
        for body in ("TARGET 2026-11-23 06:00" + " " * 60000 + "x",
                     "TARGET 2026-11-23 06:00" + "\u00a0" * 60000 + "x",
                     "TARGET" + " " * 65000 + "2026-11-23 06:00 x",
                     ("TARGET 2026-11-23 06:00 " * 2000)):
            start = time.time()
            judge(body)
            self.assertLess(time.time() - start, 1.0)


class FakeGitHub:
    def __init__(self, issues):
        self.issues = {i["number"]: i for i in issues}
        self.comments, self.closed, self.calls, self.labels_made = [], [], [], set()
        self.fail_on = None
        self.is_fork = False

    def gh(self, method, path, data=None):
        self.calls.append((method, path, data))
        parts = path.split("?")[0].split("/")
        if self.fail_on and self.fail_on(method, path):
            raise station.CheckLater("simulated GitHub failure")
        if method == "GET" and len(parts) == 4:
            return {"fork": self.is_fork}
        if method == "GET" and path.startswith(f"/repos/{parts[2]}/{parts[3]}/labels"):
            return [{"name": n} for n in self.labels_made]
        if method == "POST" and len(parts) == 5 and parts[4] == "labels":
            self.labels_made.add(data["name"])
            return None
        if path.split("?")[0].endswith("/comments"):
            n = int(parts[5])
            if method == "GET":
                return [{"body": b, "user": {"login": u}} for m, b, u in self.comments if m == n]
            self.comments.append((n, data["body"], station.BOT))
        elif method == "POST" and len(parts) == 7 and parts[6] == "labels":
            self.issues[int(parts[5])]["labels"]["nodes"] += [{"name": x} for x in data["labels"]]
        elif method == "DELETE" and "/labels/" in path:
            name = urllib.parse.unquote(parts[-1])
            nodes = self.issues[int(parts[5])]["labels"]["nodes"]
            nodes[:] = [x for x in nodes if x["name"] != name]
        elif method == "PATCH":
            self.closed.append(int(parts[5]))
            self.issues[int(parts[5])]["state"] = "CLOSED"
        return None

    def graphql(self, query, variables):
        if "issue(number" in query:
            return {"repository": {"issue": self.issues[variables["n"]]}}
        nodes = list(self.issues.values())
        return {"repository": {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}


def issue(n, body, created=EARLY, edited=None, labels=(), state="OPEN", transferred=False):
    z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None
    return {"number": n, "state": state, "createdAt": z(created), "lastEditedAt": z(edited), "body": body,
            "labels": {"nodes": [{"name": x} for x in labels]}, "timelineItems": {"totalCount": int(transferred)}}


class Robot(unittest.TestCase):
    def setUp(self):
        STATE["future_published"] = False

    def run_robot(self, fake):
        os.environ["GITHUB_REPOSITORY"] = "BastianMIllan/Operation-Antitelephone"
        station.robot(fake=fake)

    def labels(self, fake, n):
        return {x["name"] for x in fake.issues[n]["labels"]["nodes"]}

    def test_lifecycle(self):
        fake = FakeGitHub([
            issue(1, "TARGET 2026-11-23 06:00 UTC = " + C),                 # HIT
            issue(2, "TARGET 2026-11-23 06:00 UTC = 0123456789abcdef"),     # miss
            issue(3, "TARGET 2099-01-01 00:00 UTC = 0123456789abcdef"),     # pending
            issue(4, "hello"),                                              # unreadable
            issue(5, "About this repo", labels=["not a message"]),          # ignored
            issue(6, "TARGET 2026-11-23 06:00 UTC = 0123456789abcdef", edited=EARLY + dt.timedelta(minutes=3)),
            issue(7, "TARGET 2026-11-23 06:00 UTC = " + C, state="CLOSED"),  # closed by its sender: still judged
            issue(8, "TARGET 2026-11-23 06:00 UTC = " + C, transferred=True),
        ])
        self.run_robot(fake)
        self.assertEqual(fake.labels_made, set(station.LABELS))
        self.assertEqual(self.labels(fake, 1), {"station: received", "station: HIT"})
        self.assertEqual(self.labels(fake, 2), {"station: received", "station: miss"})
        self.assertEqual(self.labels(fake, 3), {"station: received", "station: pending"})
        self.assertEqual(self.labels(fake, 4), {"station: received", "station: unreadable"})
        self.assertEqual(self.labels(fake, 5), {"not a message"})
        self.assertEqual(self.labels(fake, 6), {"station: received", "station: invalid"})
        self.assertEqual(self.labels(fake, 7), {"station: received", "station: HIT"})
        self.assertEqual(self.labels(fake, 8), {"station: received", "station: invalid"})
        self.assertEqual(sorted(fake.closed), [2, 4, 6, 8])                 # HITs and pending stay open; 7 was closed
        self.assertTrue(any(station.RECEIPT_MARK in b and "HIT" in b for n, b, _ in fake.comments if n == 1))
        for n, b, _ in fake.comments:
            self.assertNotIn("hello", b)                                    # never echoes raw message text
            self.assertNotIn("evil.example", b)
        before = len(fake.comments)
        self.run_robot(fake)                                                # second run: nothing new to say
        self.assertEqual(len(fake.comments), before)
        self.assertEqual(len([c for c in fake.calls if c[0] == "POST" and c[1].endswith("/labels")
                              and c[2] and "name" in c[2]]), len(station.LABELS))   # labels created only once
        fake.issues[3]["body"] = "TARGET 2026-11-23 06:00 UTC = 0123456789abcdef"   # becomes judgeable
        self.run_robot(fake)
        self.assertEqual(self.labels(fake, 3), {"station: received", "station: miss"})
        self.assertEqual(len(fake.comments), before + 1)
        fake.issues[1]["lastEditedAt"] = "2026-11-23T07:00:00Z"             # a HIT edited later is withdrawn
        self.run_robot(fake)
        self.assertIn("station: invalid", self.labels(fake, 1))
        self.assertNotIn("station: HIT", self.labels(fake, 1))

    def test_safety_net_waits_then_flags(self):
        fake = FakeGitHub([issue(1, "TARGET 2099-01-01 00:00 EST = " + C)])
        self.run_robot(fake)
        self.assertEqual(self.labels(fake, 1), {"station: received", "station: pending"})
        self.assertEqual(fake.closed, [])
        STATE["future_published"] = True
        self.run_robot(fake)
        self.assertIn("station: check by hand", self.labels(fake, 1))
        self.assertEqual(fake.closed, [])

    def test_receipt_is_not_repeated_after_a_failed_label_write(self):
        fake = FakeGitHub([issue(1, "TARGET 2099-01-01 00:00 UTC = 0123456789abcdef")])
        fake.fail_on = lambda m, p: m == "POST" and p.endswith("/issues/1/labels")
        self.run_robot(fake)                                                # comment posted, label write failed
        fake.fail_on = None
        self.run_robot(fake)
        receipts = [b for n, b, _ in fake.comments if station.RECEIPT_MARK in b]
        self.assertEqual(len(receipts), 1)
        self.assertIn("station: pending", self.labels(fake, 1))

    def test_one_bad_issue_does_not_stop_the_rest(self):
        fake = FakeGitHub([issue(1, "TARGET 2026-11-23 06:00 UTC = " + C), issue(2, "TARGET 2026-11-23 06:00 UTC = " + C)])
        fake.issues[1]["createdAt"] = "not a time"                          # makes handling issue 1 blow up
        self.run_robot(fake)
        self.assertIn("station: HIT", self.labels(fake, 2))

    def test_network_trouble_decides_nothing(self):
        def down(target):
            raise station.CheckLater("could not reach NIST")
        saved, station.fetch_pulse = station.fetch_pulse, down
        try:
            fake = FakeGitHub([issue(1, "TARGET 2026-11-23 06:00 UTC = " + C)])
            self.run_robot(fake)
            self.assertEqual(fake.comments, [])
            self.assertEqual(self.labels(fake, 1), set())
        finally:
            station.fetch_pulse = saved

    def test_fork_stays_quiet_and_mismatch_is_loud(self):
        fake = FakeGitHub([issue(1, "TARGET 2026-11-23 06:00 UTC = " + C)])
        os.environ["GITHUB_REPOSITORY"] = "someone/time-signal-station"
        fake.is_fork = True
        station.robot(fake=fake)                                            # a fork: quiet, nothing written
        self.assertEqual(fake.comments, [])
        fake.is_fork = False
        with self.assertRaises(SystemExit):                                 # a renamed or misconfigured station: loud
            station.robot(fake=fake)

    def test_spoofed_receipt_mark_is_ignored(self):
        fake = FakeGitHub([issue(1, "TARGET 2099-01-01 00:00 UTC = 0123456789abcdef")])
        fake.comments.append((1, "thanks! " + station.RECEIPT_MARK, "some-visitor"))
        self.run_robot(fake)
        self.assertEqual(len([b for n, b, u in fake.comments if u == station.BOT and station.RECEIPT_MARK in b]), 1)

    def test_verdict_is_not_repeated_after_a_failed_label_write(self):
        fake = FakeGitHub([issue(1, "TARGET 2026-11-23 06:00 UTC = 0123456789abcdef")])
        fake.fail_on = lambda m, p: m == "POST" and p.endswith("/issues/1/labels")
        self.run_robot(fake)
        fake.fail_on = None
        self.run_robot(fake)
        self.run_robot(fake)
        verdicts = [b for n, b, u in fake.comments if station.VERDICT_MARK in b]
        self.assertEqual(len(verdicts), 1)
        self.assertIn("station: miss", self.labels(fake, 1))


class Sender(unittest.TestCase):
    def test_target_and_code_checks(self):
        now = dt.datetime.now(UTC)
        ok = (now + dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        soon = (now + dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
        self.assertIsNotNone(send.parse_target(ok)[0])
        self.assertIsNone(send.parse_target(soon)[0])
        self.assertIsNone(send.parse_target("2020-01-01 00:00")[0])
        self.assertIsNone(send.parse_target("2026-02-30 00:00")[0])
        self.assertEqual(send.parse_code("0x" + C.upper())[0], C)
        self.assertEqual(send.parse_code("92bb 0089 7d88 9137")[0], C)
        self.assertIsNone(send.parse_code("123")[0])
        self.assertIsNone(send.parse_code("zz" * 8)[0])

    def test_sent_line_is_read_back_exactly(self):
        line = f"TARGET {T:%Y-%m-%d %H:%M} UTC = {C}"                       # the format send.py writes
        self.assertEqual(judge(line + "\n")["verdict"], "HIT")


if __name__ == "__main__":
    unittest.main()
