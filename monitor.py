from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import Any

from collectors import brother, epson, ipp, snmp, xerox
from collectors.http_client import make_session
from status import empty_status, finalize, merge_status

BRAND_HTTP = {
    "brother": brother.collect,
    "epson": epson.collect,
    "xerox": xerox.collect,
}


class Monitor:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._lock = threading.Lock()
        self._statuses: dict[str, dict[str, Any]] = {
            printer["name"]: empty_status(printer) for printer in config["printers"]
        }
        self._subscribers: list[Queue] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session = make_session(
            bool(config["http"].get("verify_tls", False)),
            float(config.get("request_timeout_seconds", 5)),
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="printer-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            printers = [dict(item) for item in self._statuses.values()]
        return {
            "printers": printers,
            "summary": _summary(printers),
            "poll_interval_seconds": self.config.get("poll_interval_seconds", 20),
        }

    def subscribe(self) -> Queue:
        queue: Queue = Queue(maxsize=8)
        with self._lock:
            self._subscribers.append(queue)
        queue.put(self.snapshot())
        return queue

    def unsubscribe(self, queue: Queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self._poll_once()
            wait = max(1.0, float(self.config.get("poll_interval_seconds", 20)) - (time.monotonic() - started))
            self._stop.wait(wait)

    def _poll_once(self) -> None:
        printers = self.config["printers"]
        timeout = float(self.config.get("request_timeout_seconds", 5))
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(printers)))) as pool:
            results = list(pool.map(lambda printer: self._poll_printer(printer, timeout), printers))
        with self._lock:
            for status in results:
                self._statuses[status["id"]] = status
            snapshot = {
                "printers": [dict(item) for item in self._statuses.values()],
                "summary": _summary(list(self._statuses.values())),
                "poll_interval_seconds": self.config.get("poll_interval_seconds", 20),
            }
            subscribers = list(self._subscribers)
        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except Exception:
                    pass
            try:
                queue.put_nowait(snapshot)
            except Exception:
                pass

    def _poll_printer(self, printer: dict[str, Any], timeout: float) -> dict[str, Any]:
        status = empty_status(printer)
        brand = printer["brand"]
        if self.config["http"].get("enabled", True) and brand in BRAND_HTTP:
            try:
                http_data = BRAND_HTTP[brand](self._session, printer, timeout)
                merge_status(status, http_data)
            except Exception as exc:
                status["errors"].append(f"HTTP collector: {exc}")
        if self.config.get("ipp", {}).get("enabled", True):
            try:
                ipp_data = ipp.collect(self._session, printer, timeout)
                merge_status(status, ipp_data)
            except Exception as exc:
                status["errors"].append(f"IPP collector: {exc}")
        if self.config["snmp"].get("enabled", True):
            try:
                snmp_data = snmp.collect_sync(self.config, printer)
                merge_status(status, snmp_data)
            except Exception as exc:
                status["errors"].append(f"SNMP collector: {exc}")
        return finalize(status, self.config)


def _summary(printers: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"ok": 0, "warning": 0, "error": 0, "offline": 0, "total": len(printers)}
    for printer in printers:
        health = printer.get("health") or "offline"
        counts[health] = counts.get(health, 0) + 1
    return counts
