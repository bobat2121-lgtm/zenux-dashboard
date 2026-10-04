"""Workspace configuration, read from st.secrets only.

Shape (dashboard/.streamlit/secrets.toml locally, App settings -> Secrets on Streamlit Community Cloud):

    open_access = false          # optional: false requires the PIN again (default: OPEN_ACCESS_DEFAULT)
    owner_pin = "..."            # optional default PIN for every workspace
    builder_pin = "..."          # optional: opens the Control room (8+ characters)

    [[workspaces]]
    id = "pilot"
    title = "Pilot"              # optional
    timezone = "America/New_York"  # optional
    hub_url = "https://zenux-pilot-hub.<account>.workers.dev"
    read_token = "..."           # hub READ_TOKEN: every dashboard read
    owner_token = "..."          # hub OWNER_TOKEN: owner writes, unlocked by the PIN
    owner_pin = "..."            # optional per-workspace PIN (overrides the default)

    [[workspaces.modules]]
    id = "ai-infra"
    url = "https://zenux-pilot-ai-infra.<account>.workers.dev"
    run_token = "..."            # module RUN_TOKEN: backfill and the module's detailed /health

Problems are reported by workspace id and field name only. A secret value never appears in a message,
and the secret fields are excluded from every dataclass repr.

An owner_pin must be usable: a placeholder from the committed example or the docs (REPLACE_WITH_..., "...",
"<your PIN>", "choose-a-pin"), which anyone can read, counts as unset (the top-level default then applies, as in
deploy/streamlit-secrets.mjs), and a PIN shorter than MIN_PIN_LENGTH characters turns owner writes off.

Open access (the beta): while `open_access` is on, every visitor can edit every workspace that has a hub_url and an
owner_token and sees the Control room, with no PIN. It is on by default (OPEN_ACCESS_DEFAULT) while the owner beta
tests; `open_access = false` at the top of the secrets turns the PIN gate back on. The PINs stay in the secrets
either way, so switching back needs nothing else.

The builder PIN opens the Control room (docs/SPEC-PHASE03-UI.md 1.2). It is read the same way (placeholders count as
unset, a short one is dropped). Without one, and only when exactly one workspace is configured (the pilot, where the
owner is the builder), it falls back to the top-level owner_pin, then to that workspace's owner_pin. With two or more
workspaces no owner PIN opens it (an analyst who knows a shared default PIN would get every workspace's owner token):
the Control room stays hidden and the Configuration notes say why. `builder_pin_source` says which applied ("builder_pin" | "owner_pin" | "workspace" | ""), never the value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

WORKSPACE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_TIMEZONE = "America/New_York"
MIN_PIN_LENGTH = 8
# Beta testing: no PIN anywhere unless the secrets say `open_access = false`. Turn this off before other analysts get
# the link (docs: dashboard/README.md, "Open access").
OPEN_ACCESS_DEFAULT = True
# Placeholders that the example, the README and the deploy tool print, so anyone can read them.
PLACEHOLDER_PIN_RE = re.compile(r"^(?:REPLACE_WITH.*|\.+|<[^<>]*>|choose-a-pin)$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Module:
    id: str
    url: str
    run_token: str = field(default="", repr=False)
    title: str = ""

    @property
    def label(self) -> str:
        return self.title or self.id

    @property
    def can_backfill(self) -> bool:
        return bool(self.url and self.run_token)


@dataclass(frozen=True)
class Workspace:
    id: str
    title: str
    hub_url: str
    timezone: str = DEFAULT_TIMEZONE
    read_token: str = field(default="", repr=False)
    owner_token: str = field(default="", repr=False)
    owner_pin: str = field(default="", repr=False)
    modules: tuple[Module, ...] = ()
    open_access: bool = False  # edits need no PIN (Config.open_access)

    @property
    def label(self) -> str:
        return self.title or self.id

    @property
    def can_read(self) -> bool:
        return bool(self.hub_url and self.read_token)

    @property
    def can_write(self) -> bool:
        return bool(self.hub_url and self.owner_token and (self.owner_pin or self.open_access))

    def module(self, module_id: str | None) -> Module | None:
        return next((m for m in self.modules if m.id == module_id), None)


@dataclass(frozen=True)
class Config:
    workspaces: tuple[Workspace, ...] = ()
    problems: tuple[str, ...] = ()
    builder_pin: str = field(default="", repr=False)
    builder_pin_source: str = ""  # "builder_pin" | "owner_pin" | "workspace" | ""
    open_access: bool = False  # every visitor edits and sees the Control room, no PIN

    @property
    def has_builder(self) -> bool:
        return bool(self.builder_pin)

    def workspace(self, workspace_id: str | None) -> Workspace | None:
        return next((w for w in self.workspaces if w.id == workspace_id), None)

    @property
    def ids(self) -> list[str]:
        return [w.id for w in self.workspaces]


def to_plain(value: Any, depth: int = 0) -> Any:
    """st.secrets AttrDicts and nested Mappings as plain dicts and lists (depth-bounded)."""
    if depth > 8:
        return None
    if isinstance(value, Mapping):
        return {str(k): to_plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v, depth + 1) for v in value]
    return value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def is_placeholder_pin(pin: Any) -> bool:
    return bool(PLACEHOLDER_PIN_RE.match(_text(pin)))


def usable_pin(raw: Any) -> str:
    """The PIN, or '' when it is unset or a published placeholder (the same rule as usablePin in the deploy tool).

    An all-digit PIN written without quotes (owner_pin = 12345678) arrives from TOML as an integer; accept it as
    its digits rather than silently treating the PIN as unset.
    """
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = str(raw)
    pin = _text(raw)
    return "" if is_placeholder_pin(pin) else pin


def flag(raw: Any, default: bool) -> bool:
    """A true/false setting: TOML booleans, or "true"/"false" (also yes/no, on/off, 1/0) written as text."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw != 0
    text = _text(raw).lower()
    if text in ("true", "yes", "on", "1"):
        return True
    if text in ("false", "no", "off", "0"):
        return False
    return default


def normalize_url(raw: Any) -> tuple[str, str | None]:
    """A base URL without a trailing slash, or ('', why). https only, except http for a local dev host."""
    text = _text(raw)
    if not text:
        return "", "missing"
    try:
        parts = urlsplit(text)
    except ValueError:
        return "", "not a URL"
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return "", "must be an http(s) URL"
    if parts.username or parts.password:
        return "", "must not carry credentials"
    if parts.query or parts.fragment:
        return "", "must not carry a query or fragment"
    if parts.scheme == "http" and host not in LOCAL_HOSTS and not host.endswith(".localhost"):
        return "", "must use https (http is allowed for localhost only)"
    return text.rstrip("/"), None


_NEAR_PIN_KEY_RE = re.compile(r"^(?:owner[\s_-]*pin|pin)$", re.IGNORECASE)


def _pin_hint(data: Mapping, entry: Mapping) -> str:
    """Where a misplaced or misspelled PIN was found, by key and table only (never the value)."""
    for index, (_, module) in enumerate(_entries(entry.get("modules"))):
        if "owner_pin" in module:
            name = _text(module.get("id")) or f"#{index + 1}"
            return (f": an owner_pin was found inside module '{name}'; TOML puts every line under the nearest "
                    f"[[...]] header above it, so move the owner_pin line above the first [[workspaces.modules]] "
                    f"line (or to the very top of the secrets)")
    for scope, table in (("the workspace block", entry), ("the top of the secrets", data)):
        for key in table:
            if isinstance(key, str) and key != "owner_pin" and _NEAR_PIN_KEY_RE.match(key.strip()):
                return f": found the key '{key}' in {scope}; the key must be exactly owner_pin"
    return ": add owner_pin = \"<your PIN>\" (in quotes) above the first [[workspaces.modules]] line"


def _entries(raw: Any) -> list[tuple[str | None, Mapping]]:
    """[[workspaces]] (a list of tables) or [workspaces.<id>] (a table of tables)."""
    if isinstance(raw, Mapping):
        return [(str(k), v) for k, v in raw.items() if isinstance(v, Mapping)]
    if isinstance(raw, list):
        return [(None, v) for v in raw if isinstance(v, Mapping)]
    return []


def _parse_modules(ws_id: str, raw: Any, problems: list[str]) -> tuple[Module, ...]:
    modules: list[Module] = []
    seen: set[str] = set()
    for index, (key, entry) in enumerate(_entries(raw)):
        module_id = _text(entry.get("id")) or (key or "")
        where = f"workspace '{ws_id}' module #{index + 1}"
        if not MODULE_ID_RE.match(module_id):
            problems.append(f"{where}: id is missing or invalid")
            continue
        if module_id in seen:
            problems.append(f"workspace '{ws_id}' module '{module_id}': duplicate id")
            continue
        seen.add(module_id)
        url, why = normalize_url(entry.get("url"))
        if why:
            problems.append(f"workspace '{ws_id}' module '{module_id}': url {why}")
        run_token = _text(entry.get("run_token"))
        if not run_token:
            problems.append(f"workspace '{ws_id}' module '{module_id}': run_token missing (backfill disabled; "
                            "its health shows the hub's view only)")
        modules.append(Module(id=module_id, url=url, run_token=run_token, title=_text(entry.get("title"))))
    return tuple(modules)


def parse_config(secrets: Mapping[str, Any] | None) -> Config:
    data = to_plain(secrets or {})
    if not isinstance(data, dict):
        return Config(problems=("secrets are not a table",))
    problems: list[str] = []
    open_access = flag(data.get("open_access"), OPEN_ACCESS_DEFAULT)
    default_pin = usable_pin(data.get("owner_pin"))
    owner = data.get("owner")
    if not default_pin and isinstance(owner, dict):
        default_pin = usable_pin(owner.get("pin"))
    placeholder_seen = any(is_placeholder_pin(v) for v in (
        data.get("owner_pin"), owner.get("pin") if isinstance(owner, dict) else None))
    workspaces: list[Workspace] = []
    seen: set[str] = set()
    for index, (key, entry) in enumerate(_entries(data.get("workspaces"))):
        ws_id = _text(entry.get("id")) or (key or "")
        if not WORKSPACE_ID_RE.match(ws_id):
            problems.append(f"workspace #{index + 1}: id is missing or invalid")
            continue
        if ws_id in seen:
            problems.append(f"workspace '{ws_id}': duplicate id")
            continue
        seen.add(ws_id)
        hub_url, why = normalize_url(entry.get("hub_url"))
        if why:
            problems.append(f"workspace '{ws_id}': hub_url {why}")
        read_token = _text(entry.get("read_token"))
        if not read_token:
            problems.append(f"workspace '{ws_id}': read_token missing (hub reads disabled)")
        owner_token = _text(entry.get("owner_token"))
        owner_pin = usable_pin(entry.get("owner_pin")) or default_pin
        pin_placeholder = not owner_pin and (placeholder_seen or is_placeholder_pin(entry.get("owner_pin")))
        if not owner_token:
            problems.append(f"workspace '{ws_id}': owner_token missing (owner writes disabled)")
        if open_access:  # no PIN is asked for, so a missing or short one disables nothing
            pass
        elif pin_placeholder:
            problems.append(f"workspace '{ws_id}': owner_pin is the example placeholder, which anyone can read "
                            "(owner writes disabled)")
        elif not owner_pin:
            problems.append(f"workspace '{ws_id}': owner_pin missing (owner writes disabled)"
                            + _pin_hint(data, entry))
        if owner_pin and len(owner_pin) < MIN_PIN_LENGTH:
            if not open_access:
                problems.append(f"workspace '{ws_id}': owner_pin is shorter than {MIN_PIN_LENGTH} characters "
                                "(owner writes disabled)")
            owner_pin = ""
        workspaces.append(Workspace(
            id=ws_id,
            title=_text(entry.get("title")),
            hub_url=hub_url,
            timezone=_text(entry.get("timezone")) or DEFAULT_TIMEZONE,
            read_token=read_token,
            owner_token=owner_token,
            owner_pin=owner_pin,
            modules=_parse_modules(ws_id, entry.get("modules"), problems),
            open_access=open_access,
        ))
    builder_pin, builder_source = _builder_pin(data, default_pin, workspaces, [] if open_access else problems)
    return Config(workspaces=tuple(workspaces), problems=tuple(problems), builder_pin=builder_pin,
                  builder_pin_source=builder_source, open_access=open_access)


def _builder_pin(data: Mapping, default_pin: str, workspaces: list[Workspace], problems: list[str]) -> tuple[str, str]:
    """(the builder PIN, where it came from). A builder_pin given but too short hides the Control room (no fallback)."""
    pin = usable_pin(data.get("builder_pin"))
    if pin:
        if len(pin) < MIN_PIN_LENGTH:
            problems.append(f"builder_pin is shorter than {MIN_PIN_LENGTH} characters (the Control room stays hidden)")
            return "", ""
        return pin, "builder_pin"
    # The owner PIN opens the Control room only in the pilot, where the owner is the builder: with two or more
    # workspaces an analyst who knows the shared default PIN would otherwise get every workspace's owner token.
    if len(workspaces) == 1:
        if default_pin and len(default_pin) >= MIN_PIN_LENGTH:
            return default_pin, "owner_pin"
        if workspaces[0].owner_pin:
            return workspaces[0].owner_pin, "workspace"
    if len(workspaces) > 1:
        problems.append('builder_pin missing: the Control room stays hidden; with two or more workspaces no owner PIN '
                        'opens it (add builder_pin = "..." at the top of the secrets)')
    return "", ""


def read_secrets() -> Mapping[str, Any]:
    """st.secrets as a plain mapping; empty when no secrets file or Cloud secrets exist."""
    import streamlit as st

    try:
        return to_plain({key: st.secrets[key] for key in st.secrets.keys()})
    except Exception:  # no secrets.toml (StreamlitSecretNotFoundError) or an unparsable one
        return {}


def load_config() -> Config:
    return parse_config(read_secrets())
