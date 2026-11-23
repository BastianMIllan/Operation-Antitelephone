"""Offline tests for receiver.py (no network, no terminal needed):  python -m unittest discover tests"""
import datetime as dt
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import receiver  # noqa: E402
import station   # noqa: E402

UTC = dt.timezone.utc
REPO = "BastianMIllan/Operation-Antitelephone"


def demo_state(t):
    st = receiver.State(REPO, demo=True)
    receiver.demo_tick(st, t)
    return st


def text_of(cv):
    return "\n".join("".join(row) for row in cv.ch)


def msg(n, verdict, target=None):
    return {"number": n, "created": dt.datetime.now(UTC), "target": target, "verdict": verdict}


class TempStateFile:
    def __enter__(self):
        self.saved, receiver.STATE_FILE = receiver.STATE_FILE, os.path.join(tempfile.mkdtemp(), "state.json")
        return receiver.STATE_FILE

    def __exit__(self, *a):
        receiver.STATE_FILE = self.saved


class Rendering(unittest.TestCase):
    SIZES = [(260, 75), (213, 54), (206, 52), (205, 52), (200, 55), (160, 48), (143, 44), (130, 42), (120, 40),
             (119, 40), (120, 30), (108, 28), (107, 28), (100, 30), (80, 24), (60, 20), (20, 5)]

    def test_every_size_and_moment_renders(self):
        for t in (0.5, 12, 30):
            st = demo_state(t)
            for w, h in self.SIZES:
                with self.subTest(size=(w, h), t=t):
                    cv = receiver.render(st, w, h, t)
                    self.assertEqual((len(cv.ch), len(cv.ch[0])), (h, w))
                    for y in range(h):
                        cv.ansi_line(y)

    def test_live_mode_before_publishing_renders(self):
        st = receiver.State(REPO, demo=False)
        st.gh.update(ok=False, published=False)
        for w, h in ((213, 54), (160, 48), (120, 30), (90, 25)):
            self.assertIn("NOT", text_of(receiver.render(st, w, h, 5)))

    def test_result_column_always_visible(self):
        st = demo_state(30)                                   # has a HIT row
        st.ack()                                              # take the alarm box off the screen
        for w in (143, 150, 156, 160, 213):
            with self.subTest(w=w):
                self.assertIn("HIT", text_of(receiver.render(st, w, 48, 30)).replace("HITS", ""))

    def test_html_snapshot(self):
        page = receiver.render(demo_state(12), 130, 42, 12).html()
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("TEMPORAL DISPLAY", page)


class Alarms(unittest.TestCase):
    def test_demo_alarm_can_be_dismissed_and_is_never_saved(self):
        with TempStateFile() as path:
            st = demo_state(30)
            self.assertEqual(st.alarm["number"], 99)
            self.assertIn("NOT A REAL SIGNAL", text_of(receiver.render(st, 160, 48, 30)))
            st.ack()
            receiver.demo_tick(st, 30.2)
            self.assertIsNone(st.alarm)
            self.assertFalse(os.path.exists(path))

    def test_real_acknowledgement_is_remembered(self):
        with TempStateFile():
            st = receiver.State(REPO)
            st.gh["messages"] = [msg(5, "HIT")]
            st.check_alarm()
            self.assertEqual(st.alarm["number"], 5)
            st.ack()
            st2 = receiver.State(REPO)
            st2.gh["messages"] = [msg(5, "HIT")]
            st2.check_alarm()
            self.assertIsNone(st2.alarm)

    def test_withdrawn_hit_clears_the_alarm_and_hit_beats_check(self):
        with TempStateFile():
            st = receiver.State(REPO)
            st.gh["messages"] = [msg(9, "check by hand"), msg(3, "HIT")]
            st.check_alarm()
            self.assertEqual((st.alarm["number"], st.alarm["kind"]), (3, "HIT"))
            st.gh["messages"] = [msg(9, "check by hand"), msg(3, "invalid")]
            st.check_alarm()
            self.assertEqual((st.alarm["number"], st.alarm["kind"]), (9, "check by hand"))
            st.gh["messages"] = [msg(9, "HIT"), msg(3, "invalid")]
            st.check_alarm()
            self.assertEqual(st.alarm["kind"], "HIT")

    def test_test_alarm_switches_itself_off(self):
        st = receiver.State(REPO)
        st.alarm = {"kind": "HIT", "number": None, "target": None, "test": True, "since": receiver.mono() - 16}
        receiver.render(st, 160, 48, 5)
        self.assertIsNone(st.alarm)


class Pollers(unittest.TestCase):
    def test_github_sync_sees_a_hit_on_an_old_issue(self):
        issues = [{"number": n, "created_at": "2026-11-23T05:00:00Z", "updated_at": "2026-11-23T%02d:00:00Z" % (n % 24),
                   "body": "TARGET 2099-01-01 00:00 UTC = 0123456789abcdef",
                   "labels": [{"name": "station: HIT" if n == 20 else "station: pending"}]} for n in range(1, 151)]
        st = receiver.State(REPO)

        def fake_gh(method, path, data=None, token=None):
            if "/issues?" in path:
                page = int(re.search(r"[?&]page=(\d+)", path).group(1))
                return issues[(page - 1) * 100: page * 100]
            st.running = False                                # stop after the first full poll
            return {"workflow_runs": []}

        saved = station.gh, station.gh_token
        station.gh, station.gh_token = fake_gh, (lambda allow_cli=True: None)
        try:
            with TempStateFile():
                receiver.github_loop(st)
        finally:
            station.gh, station.gh_token = saved
        self.assertEqual(len(st.gh["messages"]), 150)
        self.assertEqual(st.alarm["number"], 20)

    def test_github_poller_survives_unexpected_data(self):
        st = receiver.State(REPO)

        def fake_gh(method, path, data=None, token=None):
            st.running = False
            return [{"number": 1}]                            # no created_at: would crash message_from_issue

        saved = station.gh, station.gh_token, receiver.ERROR_LOG
        station.gh, station.gh_token = fake_gh, (lambda allow_cli=True: None)
        receiver.ERROR_LOG = os.path.join(tempfile.mkdtemp(), "err.log")
        try:
            receiver.github_loop(st)                          # must return normally, not raise
        finally:
            station.gh, station.gh_token, receiver.ERROR_LOG = saved
        self.assertFalse(st.gh["ok"])
        self.assertIn("INTERNAL", st.gh["err"])

    def test_bad_beacon_value_is_rejected(self):
        st = receiver.State(REPO)

        def fake_get(url):
            st.running = False
            return {"pulse": {"pulseIndex": 1, "timeStamp": "2026-11-23T05:00:00.000Z", "outputValue": "XYZ"}}

        saved = station.get_json
        station.get_json = fake_get
        try:
            receiver.nist_loop(st)
        finally:
            station.get_json = saved
        self.assertFalse(st.nist["ok"])
        self.assertIsNone(st.nist["value"])


class Data(unittest.TestCase):
    def test_parse_target(self):
        self.assertEqual(receiver.parse_target("TARGET 2026-12-01 00:00 UTC = 0123456789abcdef"),
                         dt.datetime(2026, 12, 1, 0, 0, tzinfo=UTC))
        self.assertIsNone(receiver.parse_target("hello"))
        self.assertIsNone(receiver.parse_target("TARGET 2026-12-01 00:00 = a\nTARGET 2026-12-02 00:00 = b"))

    def test_issue_to_message(self):
        it = {"number": 3, "created_at": "2026-11-23T05:00:00Z", "body": "TARGET 2026-12-01 00:00 UTC = 0123456789abcdef",
              "labels": [{"name": "station: received"}, {"name": "station: pending"}]}
        self.assertEqual(receiver.message_from_issue(it)["verdict"], "pending")
        it["labels"] = [{"name": "not a message"}]
        self.assertIsNone(receiver.message_from_issue(it))


if __name__ == "__main__":
    unittest.main()
