from __future__ import annotations

import asyncio
import threading
from typing import Any

from pysnmp.hlapi.v1arch.asyncio import (
    CommunityData,
    ObjectIdentity,
    ObjectType,
    SnmpDispatcher,
    UdpTransportTarget,
    get_cmd,
    walk_cmd,
)

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
HR_PRINTER_STATUS = "1.3.6.1.2.1.25.3.5.1.1.1"
HR_PRINTER_ERRORS = "1.3.6.1.2.1.25.3.5.1.2.1"
PRT_SERIAL = "1.3.6.1.2.1.43.5.1.1.17.1"
PRT_NAME = "1.3.6.1.2.1.43.5.1.1.16.1"
PRT_LIFE_COUNT = "1.3.6.1.2.1.43.10.2.1.4.1.1"
PRT_CONSOLE = "1.3.6.1.2.1.43.16.5.1.2.1.1"
SUPPLIES_ROOT = "1.3.6.1.2.1.43.11.1.1"
TRAYS_ROOT = "1.3.6.1.2.1.43.8.2.1"

HR_STATUS_MAP = {
    1: "Other",
    2: "Unknown",
    3: "Idle",
    4: "Printing",
    5: "Warmup",
}

HR_ERROR_BITS = [
    (0, "Low paper"),
    (1, "No paper"),
    (2, "Low toner"),
    (3, "No toner"),
    (4, "Door open"),
    (5, "Jammed"),
    (6, "Offline"),
    (7, "Service requested"),
    (8, "Input tray missing"),
    (9, "Output tray missing"),
    (10, "Marker supply missing"),
    (11, "Output nearly full"),
    (12, "Output full"),
    (13, "Input tray empty"),
    (14, "Overdue preventative maintenance"),
]

SUPPLY_TYPE = {
    3: "toner",
    4: "waste",
    9: "fuser",
    15: "photoconductor",
    21: "toner",
    32: "ink",
    36: "ink",
    37: "waste",
}

SUPPLY_CLASS_CONSUMED = 3
SUPPLY_CLASS_FILLED = 4

_COLLECT_LOCK = threading.Lock()


def collect_sync(config: dict[str, Any], printer: dict[str, Any]) -> dict[str, Any] | None:
    timeout = float((config.get("snmp") or {}).get("timeout", 1.5)) * 6 + 2
    with _COLLECT_LOCK:
        try:
            return asyncio.run(asyncio.wait_for(collect(config, printer), timeout=timeout))
        except TimeoutError:
            return {"online": False, "source": "snmp", "errors": ["SNMP timeout"]}


async def collect(config: dict[str, Any], printer: dict[str, Any]) -> dict[str, Any] | None:
    snmp_cfg = config.get("snmp") or {}
    if not snmp_cfg.get("enabled", True):
        return None
    dispatcher = SnmpDispatcher()
    try:
        target = await UdpTransportTarget.create(
            (printer["ip"], int(snmp_cfg.get("port", 161))),
            float(snmp_cfg.get("timeout", 1.5)),
            int(snmp_cfg.get("retries", 0)),
        )
        auth = CommunityData(printer.get("community") or snmp_cfg.get("community") or "public")
        scalars = await _get_many(
            dispatcher,
            auth,
            target,
            {
                "sys_descr": SYS_DESCR,
                "sys_name": SYS_NAME,
                "sys_location": SYS_LOCATION,
                "hr_status": HR_PRINTER_STATUS,
                "hr_errors": HR_PRINTER_ERRORS,
                "serial": PRT_SERIAL,
                "prt_name": PRT_NAME,
                "page_count": PRT_LIFE_COUNT,
                "console": PRT_CONSOLE,
            },
        )
        if not any(value is not None for value in scalars.values()):
            return None
        walk_timeout = max(2.0, float(snmp_cfg.get("timeout", 1.5)) * 3)
        supplies_rows: dict[tuple[str, str], Any] = {}
        tray_rows: dict[tuple[str, str], Any] = {}
        try:
            supplies_rows = await asyncio.wait_for(
                _walk_table(dispatcher, auth, target, SUPPLIES_ROOT),
                timeout=walk_timeout,
            )
        except Exception:
            pass
        try:
            tray_rows = await asyncio.wait_for(
                _walk_table(dispatcher, auth, target, TRAYS_ROOT),
                timeout=walk_timeout,
            )
        except Exception:
            pass
        return _to_status(scalars, supplies_rows, tray_rows)
    except Exception as exc:
        return {"online": False, "source": "snmp", "errors": [f"SNMP: {exc}"]}
    finally:
        dispatcher.transport_dispatcher.close_dispatcher()


async def _get_many(
    dispatcher: SnmpDispatcher,
    auth: CommunityData,
    target: UdpTransportTarget,
    oids: dict[str, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {key: None for key in oids}
    objects = [ObjectType(ObjectIdentity(oid)) for oid in oids.values()]
    try:
        error_indication, error_status, _error_index, var_binds = await asyncio.wait_for(
            get_cmd(dispatcher, auth, target, *objects, lookupMib=False),
            timeout=target.timeout + 1.5,
        )
    except Exception:
        return out
    if error_indication or error_status or not var_binds:
        return out
    oid_to_key = {oid.lstrip("."): key for key, oid in oids.items()}
    for var_bind in var_binds:
        oid_s = str(var_bind[0]).lstrip(".")
        key = oid_to_key.get(oid_s)
        if not key:
            continue
        value = var_bind[1]
        if value is None or value.__class__.__name__ in {"NoSuchObject", "NoSuchInstance", "EndOfMibView"}:
            continue
        out[key] = _decode(value)
    return out


async def _walk_table(
    dispatcher: SnmpDispatcher,
    auth: CommunityData,
    target: UdpTransportTarget,
    root: str,
) -> dict[tuple[str, str], Any]:
    rows: dict[tuple[str, str], Any] = {}
    try:
        async for error_indication, error_status, _error_index, var_binds in walk_cmd(
            dispatcher,
            auth,
            target,
            ObjectType(ObjectIdentity(root)),
            lookupMib=False,
            lexicographicMode=False,
        ):
            if error_indication or error_status or not var_binds:
                break
            oid, value = var_binds[0]
            oid_s = str(oid).lstrip(".")
            if not oid_s.startswith(root):
                break
            suffix = oid_s[len(root) :].lstrip(".")
            parts = suffix.split(".")
            if len(parts) < 2:
                continue
            column, index = parts[0], ".".join(parts[1:])
            rows[(column, index)] = _decode(value)
    except Exception:
        return rows
    return rows


def _decode(value: Any) -> Any:
    pretty = value.prettyPrint()
    if pretty.startswith("0x") and len(pretty) > 2:
        try:
            raw = bytes.fromhex(pretty[2:])
            text = raw.decode("utf-8", errors="replace").strip("\x00").strip()
            if text:
                return text
        except Exception:
            pass
    try:
        return int(pretty)
    except (TypeError, ValueError):
        text = str(pretty).strip()
        return text or None


def _to_status(
    scalars: dict[str, Any],
    supplies_rows: dict[tuple[str, str], Any],
    tray_rows: dict[tuple[str, str], Any],
) -> dict[str, Any]:
    hr_status = scalars.get("hr_status")
    status_text = HR_STATUS_MAP.get(hr_status, scalars.get("console") or "Ready")
    alerts = _error_bits(scalars.get("hr_errors"))
    console = scalars.get("console")
    if console:
        alerts = [item for item in alerts if item.lower() not in str(console).lower()]
    model = _model_from_descr(scalars.get("sys_descr"))
    return {
        "online": True,
        "source": "snmp",
        "status": str(console or status_text),
        "status_priority": 1 if console else 0,
        "model": model or scalars.get("prt_name") or scalars.get("sys_name"),
        "serial": _clean(scalars.get("serial")),
        "page_count": _int_or_none(scalars.get("page_count")),
        "console": _clean(console),
        "alerts": alerts,
        "supplies": _parse_supplies(supplies_rows),
        "trays": _parse_trays(tray_rows),
    }


def _model_from_descr(descr: Any) -> str | None:
    if not descr:
        return None
    text = str(descr)
    text = text.split(",")[0].split("\n")[0]
    text = text.split("; System")[0].strip()
    return text[:80] or None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _error_bits(value: Any) -> list[str]:
    bits = 0
    if isinstance(value, int):
        bits = value
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("0x"):
            try:
                raw = bytes.fromhex(text[2:])
                bits = int.from_bytes(raw, "big")
            except ValueError:
                return []
        else:
            try:
                bits = int(text)
            except ValueError:
                return []
    alerts = []
    for bit, label in HR_ERROR_BITS:
        if bits & (1 << bit):
            alerts.append(label)
    return alerts


def _parse_supplies(rows: dict[tuple[str, str], Any]) -> list[dict[str, Any]]:
    indexes = sorted({index for (_column, index) in rows}, key=_index_sort)
    supplies = []
    for index in indexes:
        description = str(rows.get(("6", index)) or "").strip()
        supply_type = _int_or_none(rows.get(("5", index)))
        supply_class = _int_or_none(rows.get(("4", index)))
        level = _signed_int(rows.get(("9", index)))
        maximum = _signed_int(rows.get(("8", index)))
        kind = _supply_kind(description, supply_type, supply_class)
        if not description and kind == "other" and level is None:
            continue
        name = _clean_name(description or kind.replace("_", " ").title())
        percent = _percent(level, maximum)
        supplies.append(
            {
                "id": f"snmp-{index}",
                "name": name,
                "kind": kind,
                "color": _color_from_name(name, kind),
                "percent": percent,
                "level": level,
                "max": maximum,
            }
        )
    return supplies


def _parse_trays(rows: dict[tuple[str, str], Any]) -> list[dict[str, Any]]:
    indexes = sorted({index for (_column, index) in rows}, key=_index_sort)
    trays = []
    for index in indexes:
        name = str(rows.get(("18", index)) or rows.get(("13", index)) or f"Tray {index}").strip()
        level = _signed_int(rows.get(("10", index)))
        maximum = _signed_int(rows.get(("4", index)))
        media = _clean(rows.get(("13", index)))
        trays.append(
            {
                "id": f"tray-{index}",
                "name": name,
                "media": media if media != name else None,
                "percent": _tray_percent(level, maximum),
                "level": level,
                "max": maximum,
                "state": _tray_state(level, maximum),
            }
        )
    return trays


def _supply_kind(description: str, supply_type: int | None, supply_class: int | None) -> str:
    text = description.lower()
    if "waste" in text or "maintenance" in text or "box" in text and "ink" in text:
        return "waste"
    if "drum" in text or "photo" in text or "pcu" in text:
        return "photoconductor"
    if "fuser" in text:
        return "fuser"
    if supply_class == SUPPLY_CLASS_FILLED:
        return "waste"
    if supply_type in SUPPLY_TYPE:
        return SUPPLY_TYPE[supply_type]
    if "ink" in text:
        return "ink"
    if "toner" in text:
        return "toner"
    return "other"


def _color_from_name(name: str, kind: str) -> str:
    text = name.lower()
    if kind == "waste":
        return "waste"
    if any(token in text for token in ("black", "bk", "k ")):
        return "black"
    if "cyan" in text or text.endswith(" c") or " c " in text:
        return "cyan"
    if "magenta" in text:
        return "magenta"
    if "yellow" in text:
        return "yellow"
    if kind in {"toner", "ink"}:
        return "black"
    return "other"


def _tray_percent(level: int | None, maximum: int | None) -> int | None:
    if level is None or level < 0:
        return None
    if maximum is None or maximum <= 0 or maximum > 5000:
        return None
    return _percent(level, maximum)


def _tray_state(level: int | None, maximum: int | None) -> str:
    if level is None:
        return "unknown"
    if level == 0:
        return "empty"
    if level < 0:
        return "ok"
    return "ok"


def _clean_name(name: str) -> str:
    text = str(name).split(";")[0]
    text = text.split(", PN")[0].split(",PN")[0]
    return text.strip() or str(name)


def _percent(level: int | None, maximum: int | None) -> int | None:
    if level is None:
        return None
    if level < 0:
        return None
    if maximum and maximum > 0:
        return max(0, min(100, round(level / maximum * 100)))
    if 0 <= level <= 100:
        return level
    return None


def _signed_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _index_sort(index: str) -> tuple:
    parts = []
    for part in index.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(part)
    return tuple(parts)
