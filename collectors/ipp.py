from __future__ import annotations

import struct
from typing import Any

import requests

from collectors.http_client import fetch

IPP_GET_PRINTER_ATTRIBUTES = 0x000B
VALUE_INTEGER = 0x21
VALUE_ENUM = 0x23
VALUE_TEXT = 0x41
VALUE_NAME = 0x42
VALUE_KEYWORD = 0x44
VALUE_URI = 0x45
VALUE_CHARSET = 0x47
VALUE_LANGUAGE = 0x48

PRINTER_STATE = {3: "Idle", 4: "Printing", 5: "Stopped"}

REQUESTED = [
    "printer-name",
    "printer-make-and-model",
    "printer-info",
    "printer-location",
    "printer-state",
    "printer-state-reasons",
    "printer-state-message",
    "marker-names",
    "marker-colors",
    "marker-types",
    "marker-levels",
    "marker-high-levels",
    "marker-low-levels",
    "printer-uuid",
    "printer-device-id",
]


def collect(session: requests.Session, printer: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    payload = _build_request(printer["ip"])
    ip = printer["ip"]
    urls = [
        f"http://{ip}/ipp/print",
        f"http://{ip}:631/ipp/print",
        f"https://{ip}/ipp/print",
        f"https://{ip}:443/ipp/print",
        f"https://{ip}:631/ipp/print",
    ]
    ipp_timeout = min(timeout, 3.0)
    headers = {
        "Content-Type": "application/ipp",
        "Accept": "application/ipp",
        # Some Xerox firmware returns HTTP 406 when gzip is advertised.
        "Accept-Encoding": "identity",
    }
    for url in urls:
        try:
            response = fetch(
                session,
                url,
                method="POST",
                timeout=ipp_timeout,
                headers=headers,
                data=payload,
            )
            if response.status_code >= 400 or not response.content or response.content[:1] not in {b"\x01", b"\x02"}:
                continue
            parsed = _parse_response(response.content)
            if parsed:
                parsed["source"] = "ipp"
                parsed["online"] = True
                return parsed
        except requests.RequestException:
            continue
    return None


def _build_request(ip: str) -> bytes:
    body = bytearray()
    body += struct.pack(">BBHI", 2, 0, IPP_GET_PRINTER_ATTRIBUTES, 1)
    body.append(0x01)
    _add_attr(body, VALUE_CHARSET, "attributes-charset", "utf-8")
    _add_attr(body, VALUE_LANGUAGE, "attributes-natural-language", "en")
    _add_attr(body, VALUE_URI, "printer-uri", f"ipp://{ip}/ipp/print")
    first = True
    for name in REQUESTED:
        if first:
            _add_attr(body, VALUE_KEYWORD, "requested-attributes", name)
            first = False
        else:
            _add_attr(body, VALUE_KEYWORD, "", name)
    body.append(0x03)
    return bytes(body)


def _add_attr(buf: bytearray, tag: int, name: str, value: str) -> None:
    name_b = name.encode("utf-8")
    value_b = value.encode("utf-8")
    buf.append(tag)
    buf += struct.pack(">H", len(name_b))
    buf += name_b
    buf += struct.pack(">H", len(value_b))
    buf += value_b


def _parse_response(data: bytes) -> dict[str, Any] | None:
    if len(data) < 8:
        return None
    status_code = struct.unpack(">H", data[2:4])[0]
    if status_code > 0x00FF and status_code not in {0x0001}:
        # successful-ok / successful-ok-ignored-or-substituted-attributes
        if status_code >= 0x0400:
            return None
    attrs = _decode_attributes(data[8:])
    if not attrs:
        return None
    state = attrs.get("printer-state")
    reasons = _as_list(attrs.get("printer-state-reasons"))
    message = _first(attrs.get("printer-state-message"))
    status = message or PRINTER_STATE.get(_as_int(state), "Ready")
    alerts = [reason.replace("-", " ") for reason in reasons if reason not in {"none", "None", None}]
    supplies = _marker_supplies(attrs)
    model = _first(attrs.get("printer-make-and-model")) or _first(attrs.get("printer-name"))
    return {
        "status": status,
        "status_priority": 1,
        "model": model,
        "alerts": alerts,
        "supplies": supplies,
        "serial": _serial_from_device_id(_first(attrs.get("printer-device-id"))),
    }


def _marker_supplies(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    names = _as_list(attrs.get("marker-names"))
    levels = [_as_int(v) for v in _as_list(attrs.get("marker-levels"))]
    highs = [_as_int(v) for v in _as_list(attrs.get("marker-high-levels"))]
    types = _as_list(attrs.get("marker-types"))
    colors = _as_list(attrs.get("marker-colors"))
    count = max(len(names), len(levels), 0)
    supplies = []
    for i in range(count):
        name = _clean_name(names[i] if i < len(names) else f"Supply {i + 1}")
        level = levels[i] if i < len(levels) else None
        high = highs[i] if i < len(highs) else 100
        marker_type = types[i] if i < len(types) else ""
        color_name = colors[i] if i < len(colors) else ""
        kind = _kind(name, marker_type)
        percent = None
        if level is not None and level >= 0:
            if high and high > 0:
                percent = max(0, min(100, round(level / high * 100)))
            elif level <= 100:
                percent = level
        supplies.append(
            {
                "id": f"ipp-{i}",
                "name": name,
                "kind": kind,
                "color": _color(name, color_name, kind),
                "percent": percent,
                "level": level,
                "max": high,
            }
        )
    return supplies


def _kind(name: str, marker_type: str) -> str:
    blob = f"{name} {marker_type}".lower()
    if "waste" in blob:
        return "waste"
    if "drum" in blob or "photo" in blob:
        return "photoconductor"
    if "fuser" in blob:
        return "fuser"
    if "ink" in blob:
        return "ink"
    return "toner"


def _clean_name(name: str) -> str:
    text = str(name).split(";")[0]
    text = text.split(", PN")[0].split(",PN")[0]
    return text.strip() or str(name)


def _color(name: str, color_name: str, kind: str) -> str:
    blob = f"{name} {color_name}".lower()
    if kind == "waste":
        return "waste"
    if "black" in blob or "#000" in blob:
        return "black"
    if "cyan" in blob or "00ffff" in blob:
        return "cyan"
    if "magenta" in blob:
        return "magenta"
    if "yellow" in blob:
        return "yellow"
    return "black" if kind in {"toner", "ink"} else "other"


def _decode_attributes(data: bytes) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    i = 0
    current_name = ""
    while i < len(data):
        tag = data[i]
        i += 1
        if tag in {0x01, 0x02, 0x04, 0x05}:
            continue
        if tag == 0x03:
            break
        if i + 4 > len(data):
            break
        name_len = struct.unpack(">H", data[i : i + 2])[0]
        i += 2
        name = data[i : i + name_len].decode("utf-8", errors="replace")
        i += name_len
        value_len = struct.unpack(">H", data[i : i + 2])[0]
        i += 2
        raw = data[i : i + value_len]
        i += value_len
        if name:
            current_name = name
        value = _decode_value(tag, raw)
        if current_name in attrs:
            existing = attrs[current_name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                attrs[current_name] = [existing, value]
        else:
            attrs[current_name] = value
    return attrs


def _decode_value(tag: int, raw: bytes) -> Any:
    if tag in {VALUE_INTEGER, VALUE_ENUM} and len(raw) == 4:
        return struct.unpack(">i", raw)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.hex()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first(value: Any) -> str | None:
    items = _as_list(value)
    return str(items[0]) if items else None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serial_from_device_id(device_id: str | None) -> str | None:
    if not device_id:
        return None
    for part in device_id.split(";"):
        if part.strip().upper().startswith("SN:"):
            return part.split(":", 1)[1].strip() or None
    return None
