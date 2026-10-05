"""status.py (docs/SPEC-PHASE03-UI.md 3.7 and 4.3; GET /status and GET /editions/latest of docs/SPEC-PHASE05.md 4
and 5): the analyst's status line from the hub's light status read, the next briefing time (the hub's, else the
default 07:30, 12:30, 16:30), the late text, and the new-briefing banner."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import streamlit as st

import fixtures as fx
from helpers import AppCase, PILOT_HUB, READ, hub_defaults, one_workspace, stub_views
from zenux_dashboard import labels, links, status
from zenux_dashboard.api import ApiError
from zenux_dashboard.config import parse_config

NOW = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)  # Sun Oct 4, 10:00 AM EDT
WS = parse_config(one_workspace()).workspace("pilot")


def body(level: str = "green", reasons: list | None = None, **over) -> dict:
    """A GET /status answer at NOW: the last briefing 2h before, the next at 12:30 PM EDT."""
    out = fx.status(level, reasons=reasons or [])
    out["last_briefing"]["published_at"] = "2026-10-04T12:00:00Z"
    out.update(next_briefing_at="2026-10-04T16:30:00Z", last_due_at="2026-10-04T11:30:00Z")
    out.update(over)
    return out


class SummaryTests(unittest.TestCase):
    def summary(self, answer=None, *, error: ApiError | None = None, now: datetime = NOW):
        def read(_):
            if error is not None:
                raise error
            return answer if answer is not None else body()

        with patch.object(status.data, "status", side_effect=read):
            return status.summary(WS, now=now)

    def test_levels(self):
        for level, text, hint in (
                ("green", "Healthy", ""),
                ("amber", "Mostly healthy", " · a minor issue for the builder; briefings run as usual"),
                ("red", "Having trouble", " · briefings may be late or thinner; tell the builder if it lasts")):
            with self.subTest(level=level):
                s = self.summary(body(level))
                self.assertEqual(s["level"], level)
                self.assertEqual(s["text"], f"{text} · last briefing 2h ago · next 12:30 PM ET{hint}")
                self.assertFalse(s["late"])
                self.assertEqual(labels.find_jargon(s["text"]), [])

    def test_amber_from_sources_points_to_coverage(self):
        # WF3 review CV13: amber and red say what the analyst can make of them (there are no alerts)
        s = self.summary(body("amber", [{"level": "amber", "code": "sources_not_responding", "count": 2,
                                         "text": "2 sources are not responding. Coverage shows which."}]))
        self.assertEqual(s["text"], "Mostly healthy · last briefing 2h ago · next 12:30 PM ET · some sources "
                                    "aren't responding (see Coverage)")

    def test_the_editor_at_work(self):
        s = self.summary(body(editor_working=True))
        self.assertEqual(s["text"], "Healthy · last briefing 2h ago · next 12:30 PM ET · the editor is preparing your "
                                    "next briefing")

    def test_the_editor_stopped_partway(self):
        # WF5 SA-1: a Grader run whose lease ran out is not "preparing your next briefing"; the hub says it stopped
        s = self.summary(body("amber", [{"level": "amber", "code": "editor_stopped",
                                         "text": "The editor stopped partway through a briefing. The next scheduled "
                                                 "run picks it up."}], editor_working=False, code="editor_stopped"))
        self.assertEqual(s["text"], "Mostly healthy · last briefing 2h ago · next 12:30 PM ET · the editor stopped "
                                    "partway; the next scheduled run picks it up")
        self.assertNotIn("preparing", s["text"])
        self.assertEqual(labels.find_jargon(s["text"]), [])

    def test_next_from_the_default_schedule_when_missing_or_past(self):
        s = self.summary(body(next_briefing_at=None))
        self.assertEqual(s["next_at"], datetime(2026, 10, 4, 16, 30, tzinfo=timezone.utc))  # 12:30 PM EDT
        self.assertEqual(s["text"], "Healthy · last briefing 2h ago · next 12:30 PM ET")
        s = self.summary(body(next_briefing_at="2026-10-04T11:30:00Z"))  # already past
        self.assertEqual(s["text"], "Healthy · last briefing 2h ago · next 12:30 PM ET")
        evening = datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc)
        s = self.summary(body(next_briefing_at=None), now=evening)
        self.assertTrue(s["text"].endswith("next 7:30 AM ET tomorrow"))

    def test_next_from_the_hub(self):
        s = self.summary(body(next_briefing_at="2026-10-04T20:30:00Z"))
        self.assertEqual(s["next_at"], datetime(2026, 10, 4, 20, 30, tzinfo=timezone.utc))
        self.assertEqual(s["text"], "Healthy · last briefing 2h ago · next 4:30 PM ET")

    def test_late(self):
        late = {"level": "red", "code": "briefing_late", "due_at": "2026-10-04T16:30:00Z",
                "text": "The 12:30 PM ET briefing is late."}
        s = self.summary(body("red", [late], late=True, late_text=late["text"],
                              next_briefing_at="2026-10-04T20:30:00Z"))
        self.assertTrue(s["late"])
        self.assertEqual(s["late_text"], "The 12:30 PM ET briefing is late.")
        self.assertNotIn("tell the builder", s["text"])  # the late text says enough
        s = self.summary(body("red", [late], late=False, late_text=None))  # an older answer: the red reason decides
        self.assertTrue(s["late"])
        self.assertEqual(s["late_text"], "The 12:30 PM ET briefing is late.")
        s = self.summary(body("amber", [{**late, "level": "amber"}], late=False))
        self.assertFalse(s["late"])  # only a red reason is late

    def test_staging(self):
        s = self.summary(body("amber", [{"level": "amber", "code": "awaiting_signoff",
                                         "text": "Collecting. Briefings start after you sign off."}]))
        self.assertEqual((s["level"], s["text"]), ("staging", "Collecting · briefings start after sign-off"))
        s = self.summary(body(stage="staging", next_briefing_at=None))
        self.assertEqual(s["level"], "staging")
        self.assertIsNone(s["next_at"])  # no briefing is due while staging

    def test_unreachable_and_unknown(self):
        s = self.summary(error=ApiError("unreachable", "timed out"))
        self.assertEqual((s["level"], s["text"]), ("unreachable", "Can't reach ZENUX right now"))
        s = self.summary(error=ApiError("unauthorized", "HTTP 401: token refused", 401))
        self.assertEqual((s["level"], s["text"]), ("unknown", "Status unavailable"))
        self.assertEqual(self.summary(body(level="purple"))["level"], "unknown")
        self.assertEqual(self.summary({"level": None})["text"], "Status unavailable · next 12:30 PM ET")

    def test_no_briefing_yet(self):
        self.assertEqual(self.summary(body(last_briefing=None))["text"], "Healthy · next 12:30 PM ET")


class StatusLineTests(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)

        def briefing(ws):
            status.status_line(ws)
            status.new_briefing_watch(ws, st.session_state.get("probe_shown", 12))

        stub_views(self, briefing=briefing, coverage=lambda ws: st.markdown("stub coverage"))

    def test_the_line_and_refresh(self):
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="zx-status zx-status-amber"><span class="zx-dot"></span><span>Mostly healthy · last '
                      'briefing 2h ago · next ', html)
        self.assertIn("some sources aren&#x27;t responding (see Coverage)", html)
        reads = self.http.find("GET", PILOT_HUB + "/status")
        self.assertEqual(reads[-1].bearer, READ)
        # the light read only: no diagnostics, no settings
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/diagnostics"), [])
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/settings"), [])
        at.button(key="zx_refresh_status").click().run()
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/status")), len(reads) + 1)
        self.assert_plain(at)

    def test_late_text(self):
        self.http.on("GET", PILOT_HUB + "/status", fx.status("red", late=True))
        at = self.app()
        self.assertIn('<span class="zx-status-late">The 12:30 PM ET briefing is late.</span>', self.html(at))
        self.assert_plain(at)

    def test_staging_offers_the_sign_off(self):
        self.http.on("GET", PILOT_HUB + "/status", fx.status("amber", stage="staging", reasons=[
            {"level": "amber", "code": "awaiting_signoff", "text": "Collecting. Briefings start after you sign off."}]))
        at = self.app()
        self.assertIn("Collecting · briefings start after sign-off", self.html(at))
        at.button(key="zx_status_signoff").click().run()
        self.assert_clean(at)
        # What ZENUX looks for and its sign-off sit at the top of Coverage (docs/SPEC-SIMPLIFY.md 2.4)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "coverage")
        self.assertIn("stub coverage", self.html(at))

    def test_unreachable_offers_try_again(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/status"))  # unrouted: unreachable
        at = self.app()
        self.assert_clean(at)
        self.assertIn("<span>Can&#x27;t reach ZENUX right now</span>", self.html(at))
        self.assertEqual(at.button(key="zx_refresh_status").label, "Try again")

    def test_new_briefing_banner(self):
        at = self.app()  # the newest is 12, as shown
        self.assertNotIn("A new briefing is ready.", self.html(at))
        latest = self.http.find("GET", PILOT_HUB + "/editions/latest")
        self.assertTrue(latest)  # the id only: GET /editions/latest, never a full briefing
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/editions"), [])
        at = self.app(state={"probe_shown": 11})
        self.assertIn('<div class="zx-new-briefing">A new briefing is ready.</div>', self.html(at))
        reads = len(self.http.find("GET", PILOT_HUB + "/editions/latest"))
        at.button(key="zx_show_new_briefing").click().run()
        self.assert_clean(at)
        self.assertGreater(len(self.http.find("GET", PILOT_HUB + "/editions/latest")), reads)  # read again, fresh

    def test_no_banner_without_a_briefing_or_while_unreachable(self):
        self.http.on("GET", PILOT_HUB + "/editions/latest", fx.latest(None))
        at = self.app(state={"probe_shown": None})
        self.assert_clean(at)
        self.assertNotIn("A new briefing is ready.", self.html(at))
        self.http.routes.pop(("GET", PILOT_HUB + "/editions/latest"))
        self.fresh()
        at = self.app(state={"probe_shown": None})
        self.assert_clean(at)
        self.assertNotIn("A new briefing is ready.", self.html(at))


if __name__ == "__main__":
    unittest.main()
