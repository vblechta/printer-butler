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
    inclusive, weekdays = _averages(ordered) if measured else ((None, None, None), (None, None, None))
    return {
        "today": week[-1]["pages"],
        "last_week": _sum_if_complete(week),
        "last_month": _sum_if_complete(month),
        "average_day": inclusive[0],
        "average_month": inclusive[1],
        "average_year": inclusive[2],
        "average_day_weekdays": weekdays[0],
        "average_month_weekdays": weekdays[1],
        "average_year_weekdays": weekdays[2],
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


def _averages(
    points: list[tuple[datetime, int]],
) -> tuple[tuple[float | None, float | None, float | None], tuple[float | None, float | None, float | None]]:
    start, end = points[0][0], points[-1][0]
    if (end - start).total_seconds() <= 0:
        empty = (None, None, None)
        return empty, empty
    inclusive = _rate(points, start, end, include_weekends=True)
    weekdays = _rate(points, start, end, include_weekends=False)
    return inclusive, weekdays


def _rate(
    points: list[tuple[datetime, int]],
    start: datetime,
    end: datetime,
    *,
    include_weekends: bool,
) -> tuple[float | None, float | None, float | None]:
    span_seconds = _covered_seconds(start, end, weekdays_only=not include_weekends)
    total = _pages_between(points, start, end, weekdays_only=not include_weekends)
    if total is None or span_seconds <= 0:
        return None, None, None
    if total == 0 and span_seconds < 3600:
        return None, None, None
    average_day = total / (span_seconds / 86400)
    month_days = MONTH_DAYS if include_weekends else MONTH_DAYS * 5 / 7
    year_days = YEAR_DAYS if include_weekends else YEAR_DAYS * 5 / 7
    return (
        round(average_day, 1),
        round(average_day * month_days, 1),
        round(average_day * year_days, 1),
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


def _pages_between(
    points: list[tuple[datetime, int]],
    start: datetime,
    end: datetime,
    *,
    weekdays_only: bool = False,
) -> int | None:
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
        overlap = _covered_seconds(overlap_start, overlap_end, weekdays_only=weekdays_only)
        if overlap <= 0:
            continue
        total += (right_count - left_count) * (overlap / span)
    return int(total + 0.5)


def _covered_seconds(start: datetime, end: datetime, *, weekdays_only: bool) -> float:
    if end <= start:
        return 0
    if not weekdays_only:
        return (end - start).total_seconds()
    total = 0.0
    cursor = start
    while cursor < end:
        next_day = _midnight(cursor) + timedelta(days=1)
        segment_end = next_day if next_day < end else end
        if segment_end <= cursor:
            break
        if cursor.weekday() < 5:
            total += (segment_end - cursor).total_seconds()
        cursor = segment_end
    return total


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
