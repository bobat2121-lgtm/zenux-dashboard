"""Pure helpers: time parsing and display, safe HTML fragments, tolerant field access.

Every string that reaches an unsafe_allow_html block goes through `esc` (or `esc_lines`), and every link through
`safe_url`. HTML fragments never contain a blank line: Markdown would end the raw HTML block there and render
whatever follows as Markdown.
"""

from __future__ import annotations

import base64
import html
import zlib
import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

UTC = timezone.utc
MIN_TIME = datetime.min.replace(tzinfo=UTC)
DEFAULT_GRADER_TIMES = ("07:30", "12:30", "16:30")  # the Grader's default local schedule (hub ROUTINE_SCHEDULE)
SLOT_RE = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")

MODULE_NAMES = {"ai-infra": "AI infrastructure", "defense-unmanned": "defense unmanned"}
MODULE_COLORS = {"ai-infra": "#A78BFA", "defense-unmanned": "#2DD4BF"}  # violet, teal
TAG_COLORS = ("#FBBF24", "#F472B6", "#38BDF8", "#A3E635")  # amber, pink, sky, lime: any other module, by a stable hash
TAG_FILL = 0.14  # a tag's translucent fill; its text stays at 4.5:1 or more on the dark cards
TAG_LINE = 0.55  # a tag's border

PILL_CLASS = {
    "ok": "ok", "healthy": "ok", "done": "ok", "active": "ok", "approved": "ok", "published": "ok", "free": "ok",
    "selected": "ok", "stored": "ok", "approved_pending_apply": "ok", "applied": "ok",
    "degraded": "warn", "partial": "warn", "queued": "warn", "running": "warn", "proposed": "warn", "draft": "warn",
    "stale": "warn", "backoff": "warn", "pending": "warn", "held": "warn", "watch": "warn", "silent": "warn",
    "duplicate": "idle", "already_covered": "idle", "no_runs": "idle", "idle": "idle", "expired": "warn",
    "failed": "bad", "down": "bad", "error": "bad", "quarantined": "bad", "blocked": "bad", "unreachable": "bad",
    "rejected": "bad", "unauthorized": "bad", "dead_letter": "bad",
    "missing": "missing",
    # workspace severity (hub /diagnostics severity.level), routine and prompt states
    "green": "ok", "amber": "warn", "red": "bad",
    "current": "ok", "due": "warn", "out_of_date": "warn",
    "missed": "bad", "edition_missed": "bad", "overdue": "bad", "never_seen": "idle",
}


# ---------------------------------------------------------------------------------------------- values


def pick(obj: Any, *keys: str, default: Any = None) -> Any:
    """The first present, non-None value among keys (dotted paths allowed)."""
    if not isinstance(obj, Mapping):
        return default
    for key in keys:
        cur: Any = obj
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, Mapping) else None
            if cur is None:
                break
        if cur is not None:
            return cur
    return default


def as_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def dicts(value: Any) -> list[dict]:
    return [v for v in as_list(value) if isinstance(v, Mapping)]


def unique_by_id(rows: list[dict], key: str = "id") -> list[dict]:
    """Rows with a usable id, first occurrence only: widget keys are built from these ids."""
    seen: set[str] = set()
    out = []
    for row in rows:
        rid = one_line(row.get(key))
        if rid and rid not in seen:
            seen.add(rid)
            out.append(row)
    return out


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return None


def count_of(value: Any) -> int:
    """A count given as a number, a list (its length) or a {total|count} object."""
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, Mapping):
        return as_int(pick(value, "total", "count", "n")) or 0
    return as_int(value) or 0


def one_line(value: Any) -> str:
    return " ".join(("" if value is None else str(value)).split())


def clip(value: Any, limit: int) -> str:
    text = one_line(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def label_of(code: Any) -> str:
    return one_line(code).replace("_", " ")


# ---------------------------------------------------------------------------------------------- time


def parse_time(value: Any) -> datetime:
    """ISO, RFC 2822, epoch seconds or milliseconds, or a datetime → aware UTC datetime (MIN_TIME if unknown)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if abs(seconds) > 100_000_000_000:
            seconds /= 1000
        try:
            parsed = datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return MIN_TIME
    else:
        raw = str(value or "").strip()
        if not raw:
            return MIN_TIME
        if raw.replace(".", "", 1).isdigit():
            return parse_time(float(raw))
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError, IndexError):
                return MIN_TIME
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def zone(name: str | None) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or "UTC")
    except Exception:  # unknown zone or no tz database
        return UTC


def zone_label(name: str | None, local: datetime) -> str:
    if name in ("America/New_York", "US/Eastern"):
        return "ET"
    return local.strftime("%Z") or "UTC"


def fmt_time(value: Any, tz_name: str | None = "UTC") -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "time unavailable"
    local = parsed.astimezone(zone(tz_name))
    return f"{local:%b} {local.day}, {local.year} · {local.hour % 12 or 12}:{local:%M %p} {zone_label(tz_name, local)}"


def fmt_short(value: Any, tz_name: str | None = "UTC") -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "—"
    local = parsed.astimezone(zone(tz_name))
    return f"{local:%b} {local.day} · {local.hour % 12 or 12}:{local:%M %p}"


def _local(value: Any, tz_name: str | None) -> datetime | None:
    parsed = parse_time(value)
    return None if parsed == MIN_TIME else parsed.astimezone(zone(tz_name))


def clock_text(value: Any, tz_name: str | None) -> str:
    """"12:30 PM" in local time, without the zone; "—" when unknown."""
    local = _local(value, tz_name)
    return "—" if local is None else f"{local.hour % 12 or 12}:{local:%M %p}"


def fmt_clock(value: Any, tz_name: str | None) -> str:
    """"12:30 PM ET"; "—" when unknown."""
    local = _local(value, tz_name)
    return "—" if local is None else f"{local.hour % 12 or 12}:{local:%M %p} {zone_label(tz_name, local)}"


def fmt_day(value: Any, tz_name: str | None) -> str:
    """"Sat Oct 4" in local time; "—" when unknown."""
    local = _local(value, tz_name)
    return "—" if local is None else f"{local:%a} {local:%b} {local.day}"


def fmt_date(value: Any, tz_name: str | None) -> str:
    """"Oct 4" in local time; "—" when unknown."""
    local = _local(value, tz_name)
    return "—" if local is None else f"{local:%b} {local.day}"


def parse_slot(value: Any) -> tuple[int, int] | None:
    """"07:30" -> (7, 30); None for anything else."""
    m = SLOT_RE.match(value) if isinstance(value, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def next_slot(times: Iterable[str], tz_name: str | None, now: datetime | None = None) -> datetime | None:
    """The next local "HH:MM" of times strictly after now, as an aware UTC datetime (correct across DST: each day's
    slot is placed with that day's offset). None when times holds no valid slot."""
    try:
        slots = [s for s in (parse_slot(t) for t in times) if s is not None]
    except TypeError:
        return None
    if not slots:
        return None
    tz = zone(tz_name)
    clock = parse_time(now or datetime.now(UTC))
    today: date = clock.astimezone(tz).date()
    best: datetime | None = None
    for offset in range(0, 8):
        day = today + timedelta(days=offset)
        for hour, minute in slots:
            at = datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(UTC)
            if at > clock and (best is None or at < best):
                best = at
        if best is not None:
            return best
    return best


def relative_time(value: Any, now: datetime | None = None) -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "never"
    clock = parse_time(now or datetime.now(UTC))
    seconds = int((clock - parsed).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        text = "just now" if not future else "in under a minute"
        return text
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    span = f"{minutes}m" if minutes < 60 else f"{hours}h" if hours < 48 else f"{days}d"
    return f"in {span}" if future else f"{span} ago"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------------------------- html


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]$~|<>])")


def md_label(value: Any) -> str:
    """Text for a place Streamlit renders as Markdown, not HTML (widget, expander, popover and dialog labels, help
    tooltips, toasts, captions, st.info/warning/error): the Markdown control characters are backslash-escaped, so a
    headline with two dollar amounts is not typeset as math and "*" or "_" do not turn into emphasis. Never use it
    inside an unsafe_allow_html block (esc() is for those)."""
    return _MD_SPECIAL_RE.sub(r"\\\1", "" if value is None else str(value))


def esc_lines(value: Any) -> str:
    """Escaped text with each line break as <br> (blank lines collapse), safe inside a raw HTML block."""
    lines = [one_line(line) for line in ("" if value is None else str(value)).splitlines()]
    return "<br>".join(esc(line) for line in lines if line)


def safe_url(value: Any) -> str:
    """The URL when it is a plain http(s) link, else ''."""
    text = one_line(value)
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    return text


def domain_of(url: Any) -> str:
    try:
        host = (urlsplit(one_line(url)).hostname or "").lower()
    except ValueError:
        return ""
    host = host[4:] if host.startswith("www.") else host
    return "Google News" if host == "news.google.com" else host


def link(url: Any, text: Any, css: str = "source-link") -> str:
    href = safe_url(url)
    if not href:
        return f'<span class="{css} no-link">{esc(text)}</span>' if text else ""
    return f'<a class="{css}" href="{esc(href)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>'


def pill(status: Any, text: Any = None, css: str | None = None) -> str:
    """A status pill: its colour from PILL_CLASS by status (or css: ok, warn, bad, idle), its text the status."""
    key = one_line(status).lower() or "unknown"
    css = css or PILL_CLASS.get(key, "idle")
    return f'<span class="status-pill {css}">{esc(label_of(text if text is not None else key))}</span>'


def chip(text: Any, css: str = "") -> str:
    return f'<span class="zx-chip {css}">{esc(text)}</span>' if one_line(text) else ""


def module_name(module_id: Any) -> str:
    """A module's display name: "ai-infra" -> "AI infrastructure"; an unknown id with its dashes as spaces."""
    mid = one_line(module_id)
    return MODULE_NAMES.get(mid.lower()) or mid.replace("-", " ").replace("_", " ")


def module_color(module_id: Any) -> str:
    """A module's tag colour: fixed for the known modules, else one of TAG_COLORS picked by a stable hash of the id."""
    mid = one_line(module_id).lower()
    return MODULE_COLORS.get(mid) or TAG_COLORS[zlib.crc32(mid.encode("utf-8")) % len(TAG_COLORS)]


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def tag_style(color: str) -> str:
    """Inline style for a coloured pill: coloured text, a coloured border and a tinted translucent fill."""
    return f"color:{color};border-color:{rgba(color, TAG_LINE)};background:{rgba(color, TAG_FILL)}"


def join_and(parts: list[str]) -> str:
    """["a"] -> "a", ["a", "b"] -> "a and b", ["a", "b", "c"] -> "a, b and c"."""
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def table(headers: list[str], rows: list[list[str]], css: str = "zx-table") -> str:
    """An HTML table; cells are already-escaped fragments."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="zx-table-wrap"><table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


@lru_cache(maxsize=8)
def png_data_uri(path: str) -> str:
    """A PNG file as a data: URI, read once per process (the page then needs no static-file serving); '' if unreadable."""
    try:
        return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return ""


def empty_state(message: str, detail: str | None = None) -> str:
    extra = f"<br><code>{esc(detail)}</code>" if detail else ""
    return f'<div class="empty-state">{esc(message)}{extra}</div>'


def section_label(text: str, aside: str = "") -> str:
    side = f"<span>{esc(aside)}</span>" if aside else ""
    return f'<div class="section-label"><span>{esc(text)}</span>{side}</div>'
