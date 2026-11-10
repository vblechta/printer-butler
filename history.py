"""SQLite samples of printer page counters, and the statistics derived from them."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_INTERVAL = timedelta(hours=6)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTH_DAYS = 30.4375
YEAR_DAYS = 365.25


def resolve_database_path(config: dict[str, Any] | None = None) -> Path:
    env = os.environ.get("PRINTER_BUTLER_DB")
    if env:
        return Path(env)
    configured = ((config or {}).get("history") or {}).get("database")
    if configured:
        return Path(str(configured))
    data_dir = Path("/data")
    if data_dir.is_dir() and os.access(data_dir, os.W_OK):
        return data_dir / "pages.sqlite"
    return Path(__file__).resolve().parent / "data" / "pages.sqlite"


def sample_interval(config: dict[str, Any] | None) -> timedelta:
    raw = ((config or {}).get("history") or {}).get("sample_interval_hours", 6)
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        hours = 6
    if hours <= 0:
        hours = 6
    return timedelta(hours=hours)


class PageHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._last_recorded: dict[str, datetime] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS page_samples (
                    printer_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    PRIMARY KEY (printer_id, recorded_at)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_page_samples_printer
                ON page_samples (printer_id, recorded_at)
                """
            )
            rows = conn.execute(
                "SELECT printer_id, MAX(recorded_at) FROM page_samples GROUP BY printer_id"
            ).fetchall()
        for printer_id, recorded_at in rows:
            self._last_recorded[str(printer_id)] = _parse_time(recorded_at)

    def record_due(
        self,
        readings: list[tuple[str, Any]],
        *,
        now: datetime | None = None,
        interval: timedelta = SAMPLE_INTERVAL,
    ) -> int:
        moment = _as_utc(now or datetime.now(timezone.utc))
        pending: list[tuple[str, str, int]] = []
        with self._lock:
            for printer_id, count in readings:
                parsed = _parse_count(count)
                if not printer_id or parsed is None:
                    continue
                key = str(printer_id)
                last = self._last_recorded.get(key)
                if last is not None and moment < last + interval:
                    continue
                pending.append((key, moment.isoformat(timespec="seconds"), parsed))
            if not pending:
                return 0
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO page_samples (printer_id, recorded_at, page_count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(printer_id, recorded_at) DO UPDATE SET page_count = excluded.page_count
                    """,
                    pending,
                )
            for printer_id, _stamp, _count in pending:
                self._last_recorded[printer_id] = moment
        log.info("saved page counts for %s printer(s)", len(pending))
        return len(pending)

    def stats(self, printer_id: str, current: Any = None, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now or datetime.now().astimezone()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT recorded_at, page_count
                    FROM page_samples
                    WHERE printer_id = ?
                    ORDER BY recorded_at
                    """,
                    (str(printer_id),),
                ).fetchall()
        stored = [(_parse_time(stamp), int(count)) for stamp, count in rows]
        points = _with_current(stored, current, moment)
        payload = build_stats(points, moment)
        payload["sample_count"] = len(stored)
        if stored:
            payload["history_since"] = stored[0][0].astimezone(moment.tzinfo).isoformat(timespec="seconds")
        else:
            payload["history_since"] = None
        return payload

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return _ClosingConnection(conn)


def build_stats(points: list[tuple[datetime, int]], now: datetime) -> dict[str, Any]:
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    ordered = sorted(points, key=lambda item: item[0])
    measured = len(ordered) >= 2 and (ordered[-1][0] - ordered[0][0]).total_seconds() > 0
    week = _day_series(ordered, moment, 7, measured)
    month = _day_series(ordered, moment, 30, measured)
    year = _month_series(ordered, moment, 12, measured)
    averages = _averages(ordered) if measured else (None, None, None)
    return {
        "today": week[-1]["pages"],
        "last_week": _sum_if_complete(week),
        "last_month": _sum_if_complete(month),
        "average_day": averages[0],
        "average_month": averages[1],
        "average_year": averages[2],
        "series": {"week": week, "month": month, "year": year},
    }


def _day_series(
    points: list[tuple[datetime, int]],
    now: datetime,
    days: int,
    measured: bool,
) -> list[dict[str, Any]]:
    today = _midnight(now)
    start_day = today - timedelta(days=days - 1)
    series = []
    for index in range(days):
        start = start_day + timedelta(days=index)
        end = min(start + timedelta(days=1), now)
        pages = _bucket_pages(points, start, end, measured)
        series.append(
            {
                "label": WEEKDAYS[start.weekday()] if days <= 7 else str(start.day),
                "title": f"{WEEKDAYS[start.weekday()]} {start.day} {MONTHS[start.month - 1]} {start.year}",
                "pages": pages,
                "current": index == days - 1,
            }
        )
    return series


def _month_series(
    points: list[tuple[datetime, int]],
    now: datetime,
    months: int,
    measured: bool,
) -> list[dict[str, Any]]:
    year, month = now.year, now.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    series = []
    for index in range(months):
        start = datetime(year, month, 1, tzinfo=now.tzinfo)
        next_year, next_month = year, month + 1
        if next_month == 13:
            next_month = 1
            next_year += 1
        end = min(datetime(next_year, next_month, 1, tzinfo=now.tzinfo), now)
        pages = _bucket_pages(points, start, end, measured)
        series.append(
            {
                "label": MONTHS[month - 1],
                "title": f"{MONTHS[month - 1]} {year}",
                "pages": pages,
                "current": index == months - 1,
            }
        )
        year, month = next_year, next_month
    return series


def _averages(points: list[tuple[datetime, int]]) -> tuple[float | None, float | None, float | None]:
    start, end = points[0][0], points[-1][0]
    span_seconds = (end - start).total_seconds()
    if span_seconds <= 0:
        return None, None, None
    total = _pages_between(points, start, end)
    if total is None:
        return None, None, None
    if total == 0 and span_seconds < 3600:
        return None, None, None
    span_days = span_seconds / 86400
    average_day = total / span_days
    return (
        round(average_day, 1),
        round(average_day * MONTH_DAYS, 1),
        round(average_day * YEAR_DAYS, 1),
    )


def _bucket_pages(
    points: list[tuple[datetime, int]],
    start: datetime,
    end: datetime,
    measured: bool,
) -> int | None:
    if not measured or end <= start:
        return None
    first, last = points[0][0], points[-1][0]
    if end <= first or start >= last:
        return None
    return _pages_between(points, start, end)


def _sum_if_complete(series: list[dict[str, Any]]) -> int | None:
    if any(item["pages"] is None for item in series):
        return None
    return sum(item["pages"] for item in series)


def _pages_between(points: list[tuple[datetime, int]], start: datetime, end: datetime) -> int | None:
    """Pages printed in [start, end], splitting each counter increase across the sample gap."""
    if len(points) < 2:
        return None
    if end <= start:
        return 0
    total = 0.0
    for (left_at, left_count), (right_at, right_count) in zip(points, points[1:]):
        if right_at <= start or left_at >= end or right_count < left_count:
            continue
        span = (right_at - left_at).total_seconds()
        if span <= 0:
            continue
        overlap_start = left_at if left_at > start else start
        overlap_end = right_at if right_at < end else end
        overlap = (overlap_end - overlap_start).total_seconds()
        if overlap <= 0:
            continue
        total += (right_count - left_count) * (overlap / span)
    return int(total + 0.5)


def _with_current(
    points: list[tuple[datetime, int]],
    current: Any,
    now: datetime,
) -> list[tuple[datetime, int]]:
    count = _parse_count(current)
    if count is None:
        return points
    if points and points[-1][0] >= now:
        return points
    return [*points, (now, count)]


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


class _ClosingConnection:
    """Commit and close a sqlite connection when the `with` block ends."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
