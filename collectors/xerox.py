from __future__ import annotations

import uuid
from typing import Any
from xml.etree import ElementTree as ET

import requests

from collectors.http_client import fetch

SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
WSA_NS = "http://www.w3.org/2005/08/addressing"

OPERATIONS = [
    {
        "path": "/ssm/Management/Anonymous/DeviceInformation",
        "action": "/2011/01/ssm/management/deviceinformation#GetDeviceInformation",
        "operation": "GetDeviceInformation",
        "namespaces": [
            "http://www.fujixerox.co.jp/2011/01/ssm/management/deviceinformation",
            "http://www.fujifilm.com/fb/2011/01/ssm/management/deviceinformation",
        ],
    },
    {
        "path": "/ssm/Management/Anonymous/Status",
        "action": "/2011/01/ssm/management/status#GetStatus",
        "operation": "GetStatus",
        "namespaces": [
            "http://www.fujixerox.co.jp/2011/01/ssm/management/status",
            "http://www.fujifilm.com/fb/2011/01/ssm/management/status",
        ],
    },
    {
        "path": "/ssm/Management/Anonymous/Supplies",
        "action": "/2014/08/ssm/management/supplies#GetSupplies",
        "operation": "GetSupplies",
        "namespaces": [
            "http://www.fujixerox.co.jp/2014/08/ssm/management/supplies",
            "http://www.fujifilm.com/fb/2014/08/ssm/management/supplies",
        ],
    },
    {
        "path": "/ssm/Management/Anonymous/Tray",
        "action": "/2014/08/ssm/management/tray#GetPaperTrayCapability",
        "operation": "GetPaperTrayCapability",
        "namespaces": [
            "http://www.fujixerox.co.jp/2014/08/ssm/management/tray",
            "http://www.fujifilm.com/fb/2014/08/ssm/management/tray",
        ],
    },
]


def collect(session: requests.Session, printer: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    result: dict[str, Any] = {"source": "http", "alerts": [], "supplies": [], "trays": [], "errors": []}
    reachable = _ping_home(session, printer, timeout)
    soap_timeout = min(timeout, 2.0)
    soap = _soap_collect(session, printer, soap_timeout)
    if soap:
        for key, value in soap.items():
            if key in {"supplies", "trays", "alerts", "errors"}:
                result[key].extend(value or [])
            elif value not in (None, "", []):
                result[key] = value
    if reachable:
        result["errors"] = []
        result["online"] = True
        result.setdefault("status", "Ready")
        result["status_priority"] = 1 if soap.get("online") else 0
        return result
    if soap.get("online"):
        result["online"] = True
        result.setdefault("status", "Ready")
        result["status_priority"] = 1
        return result
    if result["errors"]:
        result["online"] = False
        return result
    return None


def _ping_home(session: requests.Session, printer: dict[str, Any], timeout: float) -> bool:
    for url in (f"http://{printer['ip']}/home/index.html", f"http://{printer['ip']}/"):
        try:
            response = fetch(session, url, timeout=timeout)
            if response.status_code < 400 and ("xuxInitialize" in response.text or "Xerox" in response.text or response.status_code == 200):
                return True
        except requests.RequestException:
            continue
    return False


def _soap_collect(session: requests.Session, printer: dict[str, Any], timeout: float) -> dict[str, Any]:
    merged: dict[str, Any] = {"alerts": [], "supplies": [], "trays": [], "errors": []}
    for spec in OPERATIONS:
        payload = None
        for namespace in spec["namespaces"]:
            envelope = _envelope(printer["ip"], spec["path"], spec["action"], spec["operation"], namespace)
            try:
                response = fetch(
                    session,
                    f"http://{printer['ip']}{spec['path']}",
                    method="POST",
                    timeout=timeout,
                    headers={
                        "Content-Type": "application/soap+xml; charset=utf-8",
                        "SOAPAction": spec["action"],
                    },
                    data=envelope.encode("utf-8"),
                )
            except requests.RequestException as exc:
                merged["errors"].append(f"SOAP {spec['operation']}: {exc}")
                break
            if response.status_code >= 400 or not response.content:
                continue
            if b"Envelope" not in response.content[:200] and b"Body" not in response.content:
                continue
            parsed = _parse_soap(response.text)
            if parsed:
                payload = parsed
                break
        if not payload:
            continue
        merged["online"] = True
        _absorb_soap(merged, payload)
    return merged


def _envelope(ip: str, path: str, action: str, operation: str, namespace: str) -> str:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_NS}" xmlns:a="{WSA_NS}">'
        "<s:Header>"
        f'<a:Action s:mustUnderstand="1">{action}</a:Action>'
        f"<a:MessageID>{message_id}</a:MessageID>"
        "<a:ReplyTo><a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address></a:ReplyTo>"
        f'<a:To s:mustUnderstand="1">http://{ip}{path}</a:To>'
        "</s:Header>"
        "<s:Body>"
        f'<{operation} xmlns="{namespace}"/>'
        "</s:Body>"
        "</s:Envelope>"
    )


def _parse_soap(xml_text: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    fields: dict[str, list[str]] = {}
    for node in root.iter():
        local = _local(node.tag)
        text = (node.text or "").strip()
        if not text:
            continue
        fields.setdefault(local, []).append(text)
    if not fields:
        return None
    return fields


def _absorb_soap(target: dict[str, Any], fields: dict[str, list[str]]) -> None:
    mapping = {
        "model": ("Model", "ProductName", "MachineName", "DeviceName"),
        "serial": ("SerialNumber", "MachineSerialNumber", "SerialNo"),
        "firmware": ("FirmwareVersion", "SoftwareVersion", "SystemVersion"),
        "status": ("Status", "PrinterStatus", "DeviceStatus", "State"),
        "console": ("Message", "StatusMessage", "Notification"),
    }
    for dest, names in mapping.items():
        if target.get(dest):
            continue
        for name in names:
            values = fields.get(name)
            if values:
                target[dest] = values[0]
                break
    if fields.get("LifeRemaining") or fields.get("TonerName"):
        names = fields.get("TonerName") or fields.get("Name") or []
        levels = fields.get("LifeRemaining") or fields.get("Level") or []
        for i, name in enumerate(names):
            percent = _int(levels[i]) if i < len(levels) else None
            target["supplies"].append(
                {
                    "id": f"soap-{i}",
                    "name": name,
                    "kind": "waste" if "waste" in name.lower() else "toner",
                    "color": _color(name),
                    "percent": percent,
                }
            )


def _color(name: str) -> str:
    text = name.lower()
    if "cyan" in text:
        return "cyan"
    if "magenta" in text:
        return "magenta"
    if "yellow" in text:
        return "yellow"
    if "waste" in text:
        return "waste"
    return "black"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit() or ch == "-")
    if digits in {"", "-"}:
        return None
    try:
        return int(digits)
    except ValueError:
        return None
