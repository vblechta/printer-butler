from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_status(printer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": printer["name"],
        "name": printer["name"],
        "ip": printer["ip"],
        "brand": printer["brand"],
        "location": printer.get("location") or "",
        "online": False,
        "health": "offline",
        "status": "Unreachable",
        "model": None,
        "serial": None,
        "firmware": None,
        "page_count": None,
        "console": None,
        "mac": None,
        "supplies": [],
        "trays": [],
        "alerts": [],
        "sources": [],
        "errors": [],
        "web_url": f"http://{printer['ip']}/",
        "updated_at": utc_now_iso(),
    }


def merge_status(base: dict[str, Any], incoming: dict[str, Any] | None) -> dict[str, Any]:
    if not incoming:
        return base
    if incoming.get("online"):
        base["online"] = True
    for key in ("model", "serial", "firmware", "page_count", "console", "mac"):
        if incoming.get(key) not in (None, "", []):
            if base.get(key) in (None, "", []):
                base[key] = incoming[key]
    if incoming.get("status") and (
        base.get("status") in (None, "", "Unreachable") or incoming.get("status_priority", 0) >= 1
    ):
        if incoming.get("status_priority", 0) >= 1 or base.get("status") in (None, "", "Unreachable"):
            base["status"] = incoming["status"]
    if incoming.get("source") and incoming.get("online"):
        if incoming["source"] not in base["sources"]:
            base["sources"].append(incoming["source"])
    for alert in incoming.get("alerts") or []:
        if alert and alert not in base["alerts"] and not _noise_alert(alert):
            base["alerts"].append(alert)
    for err in incoming.get("errors") or []:
        if err and err not in base["errors"]:
            if base.get("online") and "timeout" in str(err).lower():
                continue
            base["errors"].append(err)
    base["supplies"] = _merge_named(base.get("supplies") or [], incoming.get("supplies") or [], _supply_key)
    base["trays"] = _merge_named(base.get("trays") or [], incoming.get("trays") or [], _tray_key)
    return base


def _supply_key(item: dict[str, Any]) -> str:
    color = str(item.get("color") or "").strip().lower()
    kind = str(item.get("kind") or "").strip().lower()
    if color and color not in {"other", ""} and kind:
        return f"{kind}:{color}"
    return str(item.get("name") or item.get("id") or "").strip().lower()


def _tray_key(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("id") or "").strip().lower()


def _merge_named(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    key_of,
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in existing + incoming:
        key = key_of(item)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = dict(item)
            order.append(key)
            continue
        current = by_key[key]
        for field, value in item.items():
            if value in (None, "", []):
                continue
            if field == "percent" and _is_unknown_percent(current.get("percent")):
                current[field] = value
            elif field not in current or current[field] in (None, "", []):
                current[field] = value
            elif field == "percent" and not _is_unknown_percent(value) and _is_unknown_percent(current.get("percent")):
                current[field] = value
    return [by_key[key] for key in order]


def _noise_alert(alert: str) -> bool:
    text = alert.lower()
    return text in {"none", "input tray empty"}


def _is_unknown_percent(value: Any) -> bool:
    return value is None or value < 0


def compute_health(status: dict[str, Any], *, nongenuine_toner_as_warning: bool = True) -> str:
    if not status.get("online"):
        return "offline"
    text = " ".join(
        str(part)
        for part in [
            status.get("status"),
            status.get("console"),
            " ".join(status.get("alerts") or []),
        ]
        if part
    ).lower()
    error_words = (
        "error",
        "jam",
        "fatal",
        "offline",
        "paper out",
        "no paper",
        "replace",
        "cover open",
        "door open",
        "failed",
        "chyba",
        "zaseknut",
        "vymen",
        "vyměň",
    )
    warn_words = [
        "warning",
        "toner low",
        "ink low",
        "attention",
        "reorder",
        "nízk",
        "objednat",
        "media low",
    ]
    if nongenuine_toner_as_warning:
        warn_words.extend(["non-genuine", "nongenuine"])
    supplies = status.get("supplies") or []
    remaining = [
        s.get("percent")
        for s in supplies
        if s.get("kind") != "waste" and isinstance(s.get("percent"), (int, float)) and s.get("percent") >= 0
    ]
    waste = [
        s.get("percent")
        for s in supplies
        if s.get("kind") == "waste" and isinstance(s.get("percent"), (int, float)) and s.get("percent") >= 0
    ]
    if any(word in text for word in error_words):
        return "error"
    if any(percent <= 0 for percent in remaining):
        return "error"
    if any(percent >= 95 for percent in waste):
        return "error"
    if any(word in text for word in warn_words):
        return "warning"
    if any(percent <= 20 for percent in remaining):
        return "warning"
    if any(percent >= 80 for percent in waste):
        return "warning"
    return "ok"


def finalize(status: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    alerts_cfg = (config or {}).get("alerts") or {}
    status["health"] = compute_health(
        status,
        nongenuine_toner_as_warning=bool(alerts_cfg.get("nongenuine_toner_as_warning", True)),
    )
    if status["online"] and status.get("status") in (None, "", "Unreachable"):
        status["status"] = "Ready"
    status["updated_at"] = utc_now_iso()
    return status
