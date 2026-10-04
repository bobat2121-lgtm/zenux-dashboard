"""Test harness for the ZENUX dashboard: fake secrets, a routed fake for requests.get/post, and AppTest setup.

Nothing here touches the network: every request goes through FakeHttp, and an unrouted URL behaves like an
unreachable host (requests.ConnectionError). Tokens below are obvious test values, never real ones.

AppCase.app() opens the app on a tab (`tab`, the slug set in session "zx_tab"), optionally signed in (`pin`, adopted
and unlocked on the first run; `builder_pin` the same for the builder), with query parameters (`query`) and extra
session state (`state`). hub_defaults() routes every hub read of docs/SPEC-PHASE03-UI.md 3.3 to a fixtures.py body;
a test then overrides the routes it cares about.
"""

from __future__ import annotations

import copy
import html as html_lib
import logging
import re
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

import fixtures as fx  # noqa: E402
from zenux_dashboard import labels, owner  # noqa: E402
from zenux_dashboard.config import Workspace  # noqa: E402

# Bare-mode notices ("missing ScriptRunContext", "No runtime found") are expected outside `streamlit run`.
# The option covers every later config parse; set_log_level covers the loggers that already exist.
_st_config.set_option("logger.level", "error")
_st_logger.set_log_level("error")
# The shell logs a view it turned into a "Couldn't load this page" box; tests see it through assert_clean instead.
logging.getLogger("zenux_dashboard").setLevel(logging.CRITICAL)
# Never read a real secrets file. Streamlit looks for .streamlit/secrets.toml in the working directory, and
# dashboard/.streamlit/secrets.toml holds live production secrets: run from dashboard/, a bare-mode st.secrets (or an
# AppTest given no secrets) would load it. Tests pass their secrets through AppTest.secrets only.
NO_SECRETS_FILE = Path(__file__).resolve().parent / "no-such-dir" / "secrets.toml"
_st_config.set_option("secrets.files", [str(NO_SECRETS_FILE)])
st.secrets._secrets = None  # forget anything parsed before this module was imported

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
BUILDER_PIN = "builder-2468-test"
SECRETS = (READ, OWNER, RUN_AI, RUN_DEF, BETA_READ, BETA_OWNER, BETA_RUN, PIN, BETA_PIN, BUILDER_PIN)
DATA_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]+")
TAG_RE = re.compile(r"<[^>]*>")
ICON_RE = re.compile(r":material/[a-z0-9_]+:")
STYLE_RE = re.compile(r"<style\b.*?</style>", re.DOTALL | re.IGNORECASE)
TITLE_ATTR_RE = re.compile(r'\btitle="([^"]*)"')  # an HTML tooltip (the Coverage chips' help texts)
# Every source key, entity id and coverage-area id of the fixtures: none may reach an analyst tab (assert_plain).
ENGINE_KEYS = ("ai-infra", "defense-unmanned", "breaking-defense", "dcd-news", "defense-news", "dod-budget", "edgar-8k",
               "ent-coreweave-1", "ent-coreweave-2", "ent-example-co-1", "ercot-large-load", "gn-themes", "html-list",
               "loudoun-agendas", "miner-ir", "neocloud-ir", "old-key", "puct-large-load", "sam-awards", "sam-opps",
               "sodium-news", "uas-vision", "wargov-contracts", "example-co")
ENGINE_KEY_RE = re.compile(r"(?<![\w./-])(?:" + "|".join(re.escape(k) for k in ENGINE_KEYS) + r")(?![\w-])")
CRASH_KEY = "zx_page_crash"


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
    """A fresh server-wide PIN guard, and no remembered verdicts or unlocks in the bare-mode session state."""
    owner.guard.clear()
    try:
        for key in (owner.MEMO_KEY, owner.UNLOCK_KEY, owner.BUILDER_KEY, owner.RESULT_KEY):
            st.session_state.pop(key, None)
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


def _flag(params: dict | None, name: str) -> bool:
    return str((params or {}).get(name, "")).lower() in ("1", "true")


def hub_defaults(http: FakeHttp, base: str = PILOT_HUB) -> FakeHttp:
    """Route every hub read (docs/SPEC-PHASE03-UI.md 3.3, plus the WF5 reads of docs/SPEC-PHASE05.md) to a
    fixtures.py body. Query-dependent reads answer by their parameters: /rejected by filter and include_auto, /mutes
    by all=1, the previews by their target and mode, /modules/<id>/inspect for both pilot modules, /editions/<id>
    for 10 to 12, /editions/search with no hits. Returns http for chaining."""
    http.on("GET", base + "/editions", fx.editions_v8())
    for edition_id in (12, 11, 10):
        http.on("GET", f"{base}/editions/{edition_id}", fx.edition_single(edition_id))
    http.on("GET", base + "/editions/latest", fx.latest())
    http.on("GET", base + "/editions/search", lambda call: fx.search_hits((call.params or {}).get("q", "")))
    http.on("GET", base + "/status", fx.status())
    http.on("GET", base + "/mutes/bring-back-preview",
            lambda call: fx.bring_back_preview(int((call.params or {}).get("mute_id") or 4)))
    http.on("GET", base + "/rejected",
            lambda call: fx.rejected_v8((call.params or {}).get("filter", "all"), _flag(call.params, "include_auto")))
    http.on("GET", base + "/modules", fx.modules())
    for module in ("ai-infra", "defense-unmanned"):
        http.on("GET", f"{base}/modules/{module}/inspect", fx.inspect(module))
    http.on("GET", base + "/mutes", lambda call: fx.mutes(_flag(call.params, "all")))
    http.on("GET", base + "/mutes/preview", lambda call: fx.mute_preview(
        (call.params or {}).get("kind", "source"), (call.params or {}).get("ref", "dcd-news"),
        (call.params or {}).get("module")))
    http.on("GET", base + "/stars", fx.stars())
    http.on("GET", base + "/stars/preview", lambda call: fx.star_preview((call.params or {}).get("entity", "nebius")))
    http.on("GET", base + "/preferences", fx.preferences())
    http.on("GET", base + "/rules", fx.rules())
    http.on("GET", base + "/settings", fx.settings())
    http.on("GET", base + "/settings/volume/preview",
            lambda call: fx.volume_preview((call.params or {}).get("mode", "top")))
    http.on("GET", base + "/brief", fx.brief())
    http.on("GET", base + "/radar", fx.radar_v8())
    http.on("GET", base + "/diagnostics", fx.diagnostics())
    return http


VIEW_STUBS = {"briefing": "feed_view", "filtered": "filtered_view", "preferences": "preferences_view",
              "coverage": "coverage_view", "control": "control_view"}


def stub_views(case: unittest.TestCase, **renders: Callable) -> dict[str, Any]:
    """Replace the view modules (and `actions`) with stubs for one test, so a shell test does not depend on the
    views: renders maps a tab slug to its render function (render(ws), or render(conf, ws) for "control"); a tab
    without one draws a one-line placeholder. Only the replaced sys.modules entries are restored afterwards."""
    import types

    stubs: dict[str, Any] = {}
    for name in ("actions",) + tuple(VIEW_STUBS.values()):
        module = types.ModuleType(f"zenux_dashboard.{name}")
        stubs[name] = module
    for tab, name in VIEW_STUBS.items():
        default = (lambda conf, ws, _t=tab: st.markdown(f"stub {_t}")) if tab == "control" else \
            (lambda ws, _t=tab: st.markdown(f"stub {_t}"))
        stubs[name].render = renders.get(tab, default)
    for name, module in stubs.items():
        key = f"zenux_dashboard.{name}"
        previous = sys.modules.get(key, None)
        sys.modules[key] = module
        case.addCleanup(_restore_module, key, previous)
    return stubs


def _restore_module(key: str, previous: Any) -> None:
    if previous is None:
        sys.modules.pop(key, None)
    else:
        sys.modules[key] = previous


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

    def app(self, secrets: dict | None = None, *, tab: str | None = None, pin: str | None = None,
            builder_pin: str | None = None, query: dict | None = None, state: dict | None = None,
            run: bool = True) -> AppTest:
        """The app with these secrets (default: the pilot workspace). tab: the slug set in session "zx_tab"; pin:
        preset owner.PIN_KEY (adopted and unlocked on the first run); builder_pin: preset owner.BUILDER_PIN_KEY;
        query: at.query_params; state: more session state."""
        at = AppTest.from_file(str(APP_PATH), default_timeout=60)
        at.secrets.update(copy.deepcopy(secrets if secrets is not None else one_workspace()))
        if tab:
            at.session_state["zx_tab"] = tab
        if pin is not None:
            at.session_state[owner.PIN_KEY] = pin
        if builder_pin is not None:
            at.session_state[owner.BUILDER_PIN_KEY] = builder_pin
        for key, value in (query or {}).items():
            at.query_params[key] = value
        for key, value in (state or {}).items():
            at.session_state[key] = value
        return at.run() if run else at

    @staticmethod
    def raw_html(at: AppTest) -> str:
        """Every markdown block but the stylesheet, exactly as sent (the logo mark is an inline data: URI)."""
        return "\n".join(str(m.value) for m in at.markdown if not str(m.value).startswith("<style>"))

    @classmethod
    def html(cls, at: AppTest) -> str:
        """raw_html with inline images shortened, so a failing assertion prints a readable page."""
        return DATA_URI.sub("data:image/png;base64,...", cls.raw_html(at))

    @staticmethod
    def walk(node: Any):
        """Every node of an AppTest element tree, in page order."""
        yield node
        children = getattr(node, "children", None) or {}
        for key in sorted(children):
            yield from AppCase.walk(children[key])

    @staticmethod
    def visible_text(at: AppTest) -> str:
        """What a reader sees, one piece per line: markdown with tags and attributes stripped (plus its title=""
        tooltips), captions, button, widget (with options, radio captions, placeholders and help tooltips), expander,
        popover and dialog labels, toasts, warnings, infos, errors. Material icon codes are left out."""
        parts: list[str] = []
        for node in AppCase.walk(at._tree):
            kind = getattr(node, "type", "")
            proto = getattr(node, "proto", None)
            if kind == "markdown":
                raw = STYLE_RE.sub("", str(node.value))
                parts.append(html_lib.unescape(TAG_RE.sub(" ", raw)))
                parts.extend(html_lib.unescape(t) for t in TITLE_ATTR_RE.findall(raw))
            elif kind in ("caption", "warning", "info", "error", "success", "toast", "text", "header", "subheader",
                          "title"):
                parts.append(str(node.value))
            elif kind == "popover" and proto is not None:
                parts.append(proto.popover.label)
            elif kind == "dialog" and proto is not None:
                parts.append(proto.dialog.title)
            elif kind in ("expander", "tab", "status"):
                parts.append(str(getattr(node, "label", "")))
            elif hasattr(node, "label") and getattr(node, "label", None) is not None:
                parts.append(str(node.label))
                for option in getattr(node, "options", None) or []:
                    parts.append(option if isinstance(option, str) else str(getattr(option, "content", option)))
                placeholder = getattr(node, "placeholder", None)
                if placeholder:
                    parts.append(str(placeholder))
                parts.extend(str(c) for c in (getattr(proto, "captions", None) or []))
            help_text = getattr(proto, "help", None) if proto is not None else None
            if isinstance(help_text, str) and help_text:
                parts.append(help_text)
        text = "\n".join(" ".join(p.split()) for p in parts if p and p.strip())
        return ICON_RE.sub("", text)

    def assert_plain(self, at: AppTest) -> None:
        """The jargon guard: no engine word, source key, entity id or coverage-area id anywhere a reader can see
        (tooltips included)."""
        text = self.visible_text(at)
        self.assertEqual(labels.find_jargon(text) + ENGINE_KEY_RE.findall(text), [], text)

    @staticmethod
    def open_popover(at: AppTest, key: str) -> None:
        """Open a lazy popover (key, on_change="rerun") for the next run."""
        at.session_state[key] = True

    @staticmethod
    def open_expander(at: AppTest, key: str) -> None:
        """Open a lazy expander (key, on_change="rerun") for the next run."""
        at.session_state[key] = True

    @staticmethod
    def toasts(at: AppTest) -> list[str]:
        return [str(t.value) for t in at.toast]

    @staticmethod
    def click(at: AppTest, key: str) -> AppTest:
        return at.button(key=key).click().run()

    @staticmethod
    def fresh() -> None:
        """Forget cached hub reads, as a later session past the cache TTL would."""
        st.cache_data.clear()

    @staticmethod
    def texts(at: AppTest, kind: str) -> list[str]:
        return [str(e.value) for e in getattr(at, kind)]

    def assert_clean(self, at: AppTest) -> None:
        """No exception on the page, and no tab or dialog that the shell turned into a "Couldn't load this page" box
        (its traceback is in the failure message)."""
        self.assertEqual([str(e.value) for e in at.exception], [])
        self.assertIsNone(at.session_state.get(CRASH_KEY), at.session_state.get(CRASH_KEY))

    def assert_no_secrets(self, at: AppTest) -> None:
        """No token or PIN appears anywhere in the rendered page, its widget values or the query string."""
        rendered = "\n".join(
            [self.html(at), self.visible_text(at)]
            + [str(e.value) for kind in ("caption", "error", "warning", "info", "success", "toast", "code")
               for e in getattr(at, kind)]
            + [str(j.value) for j in at.json]
            + [str(w.value) for w in at.text_input]
            + [str(at.query_params)]
        )
        for secret in SECRETS:
            self.assertNotIn(secret, rendered)
