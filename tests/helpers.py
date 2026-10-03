"""Test harness for the ZENUX dashboard: fake secrets, a routed fake for requests.get/post, and AppTest setup.

Nothing here touches the network: every request goes through FakeHttp, and an unrouted URL behaves like an
unreachable host (requests.ConnectionError). Tokens below are obvious test values, never real ones.
"""

from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

DASHBOARD = Path(__file__).resolve().parents[1]
APP_PATH = DASHBOARD / "streamlit_app.py"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

import requests  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit import config as _st_config  # noqa: E402
from streamlit import logger as _st_logger  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from zenux_dashboard import owner  # noqa: E402
from zenux_dashboard.config import Workspace  # noqa: E402

# Bare-mode notices ("missing ScriptRunContext", "No runtime found") are expected outside `streamlit run`.
# The option covers every later config parse; set_log_level covers the loggers that already exist.
_st_config.set_option("logger.level", "error")
_st_logger.set_log_level("error")

PILOT_HUB = "https://zenux-pilot-hub.test.invalid"
PILOT_AI = "https://zenux-pilot-ai-infra.test.invalid"
PILOT_DEF = "https://zenux-pilot-defense-unmanned.test.invalid"
BETA_HUB = "https://zenux-beta-hub.test.invalid"
BETA_COV = "https://zenux-beta-coverage.test.invalid"

READ = "test-read-token-pilot"
OWNER = "test-owner-token-pilot"
PIN = "pin-4321-test"
RUN_AI = "test-run-token-ai-infra"
RUN_DEF = "test-run-token-defense"
BETA_READ = "test-read-token-beta"
BETA_OWNER = "test-owner-token-beta"
BETA_PIN = "pin-8765-test"
BETA_RUN = "test-run-token-beta-coverage"


def pilot_secrets() -> dict:
    return {
        "id": "pilot", "title": "Pilot", "timezone": "America/New_York",
        "hub_url": PILOT_HUB, "read_token": READ, "owner_token": OWNER, "owner_pin": PIN,
        "modules": [
            {"id": "ai-infra", "url": PILOT_AI, "run_token": RUN_AI},
            {"id": "defense-unmanned", "url": PILOT_DEF, "run_token": RUN_DEF},
        ],
    }


def beta_secrets() -> dict:
    return {
        "id": "beta", "title": "Beta analyst", "hub_url": BETA_HUB, "read_token": BETA_READ,
        "owner_token": BETA_OWNER, "owner_pin": BETA_PIN,
        "modules": [{"id": "coverage", "url": BETA_COV, "run_token": BETA_RUN}],
    }


def wrong_pin(workspace_id: str) -> str:
    """The message for a wrong PIN, which is also the message for any PIN during a lockout."""
    return owner.lock_message(Workspace(id=workspace_id, title="", hub_url=""), owner.WRONG_PIN)


def reset_pin_guard() -> None:
    """A fresh server-wide PIN guard, and no remembered verdicts in the bare-mode session state."""
    owner.guard.clear()
    try:
        st.session_state.pop(owner.MEMO_KEY, None)
    except Exception:
        pass


def one_workspace() -> dict:
    return {"workspaces": [pilot_secrets()]}


def two_workspaces() -> dict:
    return {"workspaces": [pilot_secrets(), beta_secrets()]}


_NO_JSON = object()


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None, *, no_json: bool = False):
        self.status_code = status
        self._body = _NO_JSON if no_json else body
        self.text = "" if no_json or body is None else str(body)[:200]
        self.headers = {"content-type": "application/json"}

    def json(self):
        if self._body is _NO_JSON:
            raise ValueError("not JSON")
        return copy.deepcopy(self._body)


@dataclass
class Call:
    method: str
    url: str
    params: dict | None = None
    headers: dict = field(default_factory=dict)
    body: Any = None

    @property
    def bearer(self) -> str | None:
        value = self.headers.get("Authorization", "")
        return value[7:] if value.startswith("Bearer ") else None


Handler = FakeResponse | Exception | Callable[[Call], Any]


class FakeHttp:
    """Routes (METHOD, URL without query) to a FakeResponse, an exception, or a callable(call)."""

    def __init__(self):
        self.routes: dict[tuple[str, str], Handler] = {}
        self.calls: list[Call] = []

    def on(self, method: str, url: str, handler: Handler | dict | list) -> "FakeHttp":
        if isinstance(handler, (dict, list)):
            handler = FakeResponse(200, handler)
        self.routes[(method, url)] = handler
        return self

    def get(self, url, params=None, headers=None, timeout=None, **_):
        return self._dispatch(Call("GET", url, dict(params or {}), dict(headers or {})))

    def post(self, url, params=None, json=None, headers=None, timeout=None, **_):
        return self._dispatch(Call("POST", url, dict(params or {}), dict(headers or {}), copy.deepcopy(json)))

    def _dispatch(self, call: Call):
        self.calls.append(call)
        handler = self.routes.get((call.method, call.url))
        if handler is None:
            raise requests.ConnectionError("no route in test")
        if isinstance(handler, Exception):
            raise handler
        if callable(handler) and not isinstance(handler, FakeResponse):
            out = handler(call)
            return out if isinstance(out, FakeResponse) else FakeResponse(200, out)
        return handler

    def find(self, method: str, url: str) -> list[Call]:
        return [c for c in self.calls if c.method == method and c.url == url]

    def posts(self) -> list[Call]:
        return [c for c in self.calls if c.method == "POST"]


class AppCase(unittest.TestCase):
    """Fresh caches and a fresh FakeHttp per test; requests.get/post are patched for the whole test."""

    maxDiff = None

    def setUp(self):
        st.cache_data.clear()
        reset_pin_guard()
        self.http = FakeHttp()
        for name in ("get", "post"):
            patcher = patch(f"requests.{name}", side_effect=getattr(self.http, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        delay = patch.object(owner, "FAIL_DELAY", 0)  # the wrong-PIN wait, which the PIN tests check on their own
        delay.start()
        self.addCleanup(delay.stop)
        self.addCleanup(st.cache_data.clear)
        self.addCleanup(reset_pin_guard)

    def app(self, secrets: dict | None = None, *, view: str | None = None, pin: str | None = None,
            grading: bool = False, state: dict | None = None, run: bool = True) -> AppTest:
        at = AppTest.from_file(str(APP_PATH), default_timeout=60)
        at.secrets.update(copy.deepcopy(secrets if secrets is not None else one_workspace()))
        if view:
            at.session_state["dashboard_view"] = view
        if pin is not None:
            at.session_state["owner_pin"] = pin
        if grading:
            at.session_state["grading_enabled"] = True
        for key, value in (state or {}).items():
            at.session_state[key] = value
        return at.run() if run else at

    @staticmethod
    def html(at: AppTest) -> str:
        """Every markdown block but the stylesheet."""
        return "\n".join(str(m.value) for m in at.markdown if not str(m.value).startswith("<style>"))

    @staticmethod
    def fresh() -> None:
        """Forget cached hub reads, as a later session past the cache TTL would."""
        st.cache_data.clear()

    @staticmethod
    def texts(at: AppTest, kind: str) -> list[str]:
        return [str(e.value) for e in getattr(at, kind)]

    def assert_clean(self, at: AppTest) -> None:
        self.assertEqual([str(e.value) for e in at.exception], [])

    def assert_no_secrets(self, at: AppTest) -> None:
        """No token or PIN appears anywhere in the rendered page."""
        rendered = "\n".join(
            [self.html(at)] + [str(e.value) for kind in ("caption", "error", "warning", "info", "success")
                               for e in getattr(at, kind)]
            + [str(j.value) for j in at.json]
        )
        for secret in (READ, OWNER, RUN_AI, RUN_DEF, BETA_READ, BETA_OWNER, BETA_RUN, PIN, BETA_PIN):
            self.assertNotIn(secret, rendered)
