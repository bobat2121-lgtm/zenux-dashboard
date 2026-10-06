"""Contract with the hub: the Friday "Conferences coming up" item exactly as the hub's GET /editions serves it
(hub_conference_item.json, which hub/test/conferences.test.js keeps equal to the hub's answer) renders as the
structured card: flag labels, month sections and event-page links, not the plain-text fallback. Each side once tested
only its own shape, and the card fell back to plain text against the real hub."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts dashboard/ on sys.path)
from zenux_dashboard import feed_view

ITEM = json.loads((Path(__file__).resolve().parent / "hub_conference_item.json").read_text(encoding="utf-8"))


class HubConferenceItemTests(unittest.TestCase):
    def test_the_hub_item_is_the_conference_list(self):
        self.assertTrue(feed_view.is_conference_list(ITEM))
        self.assertEqual(feed_view.story_items([ITEM]), [])
        self.assertTrue(feed_view.conference_body(ITEM).get("months"))

    def test_renders_flags_months_and_event_pages(self):
        html = feed_view.conference_html(ITEM)
        self.assertNotIn("conf-text-block", html)  # the plain-text fallback
        for label in ("October 2026", "November 2026", "January 2027"):
            self.assertIn(f'<div class="conf-month-label">{label}</div>', html)
        for flags in ("NOW PRESENTING: RCAT", "NEW", "DATES SET, NOW PRESENTING: ONDS"):
            self.assertIn(f'<span class="conf-flag">{flags}</span>', html)
        self.assertIn('href="https://www.think-equity.com/"', html)
        self.assertIn(feed_view.CONFERENCE_LINK, html)
        self.assertIn("Later (Jun 2027 to May 2028)", html)
        self.assertIn("Dates not posted yet: DSI Loitering Munitions Systems Summit 2027", html)


if __name__ == "__main__":
    unittest.main()
