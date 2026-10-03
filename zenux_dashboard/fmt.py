"""Pure helpers: time parsing and display, safe HTML fragments, tolerant field access.

Every string that reaches an unsafe_allow_html block goes through `esc` (or `esc_lines`), and every link through
`safe_url`. HTML fragments never contain a blank line: Markdown would end the raw HTML block there and render
whatever follows as Markdown.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone, tzinfo
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

UTC = timezone.utc
MIN_TIME = datetime.min.replace(tzinfo=UTC)

TAG_PALETTE = ["#b692f6", "#4fd1c5", "#f6c177", "#f38ba8", "#7ee787", "#c3e88d", "#ffab70", "#ffd166"]

PILL_CLASS = {
    "ok": "ok", "healthy": "ok", "done": "ok", "active": "ok", "approved": "ok", "published": "ok", "free": "ok",
    "selected": "ok", "stored": "ok", "approved_pending_apply": "ok", "applied": "ok",
    "degraded": "warn", "partial": "warn", "queued": "warn", "running": "warn", "proposed": "warn", "draft": "warn",
    "stale": "warn", "backoff": "warn", "pending": "warn", "held": "warn", "watch": "warn", "silent": "warn",
    "duplicate": "idle", "already_covered": "idle", "no_runs": "idle", "idle": "idle", "expired": "warn",
    "failed": "bad", "down": "bad", "error": "bad", "quarantined": "bad", "blocked": "bad", "unreachable": "bad",
    "rejected": "bad", "unauthorized": "bad", "dead_letter": "bad",
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


def pill(status: Any, text: Any = None) -> str:
    key = one_line(status).lower() or "unknown"
    css = PILL_CLASS.get(key, "idle")
    return f'<span class="status-pill {css}">{esc(label_of(text if text is not None else key))}</span>'


def chip(text: Any, css: str = "") -> str:
    return f'<span class="zx-chip {css}">{esc(text)}</span>' if one_line(text) else ""


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def palette_for(labels: Iterable[str]) -> dict[str, str]:
    """A stable colour per distinct label, in first-seen order."""
    out: dict[str, str] = {}
    for label in labels:
        if label not in out:
            out[label] = TAG_PALETTE[len(out) % len(TAG_PALETTE)]
    return out


def table(headers: list[str], rows: list[list[str]], css: str = "zx-table") -> str:
    """An HTML table; cells are already-escaped fragments."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="zx-table-wrap"><table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def empty_state(message: str, detail: str | None = None) -> str:
    extra = f"<br><code>{esc(detail)}</code>" if detail else ""
    return f'<div class="empty-state">{esc(message)}{extra}</div>'


def section_label(text: str, aside: str = "") -> str:
    side = f"<span>{esc(aside)}</span>" if aside else ""
    return f'<div class="section-label"><span>{esc(text)}</span>{side}</div>'
