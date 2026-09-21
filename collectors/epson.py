from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from collectors.http_client import fetch

INK_MAX_PX = 50
PRTINFO_PATH = "/PRESENTATION/HTML/TOP/PRTINFO.HTML"


def collect(session: requests.Session, printer: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    urls = [
        f"http://{printer['ip']}{PRTINFO_PATH}",
        f"https://{printer['ip']}{PRTINFO_PATH}",
    ]
    last_error = None
    for url in urls:
        try:
            response = fetch(session, url, timeout=timeout)
            if response.status_code >= 400 or not response.text:
                continue
            if not response.encoding or response.encoding.lower() in {"iso-8859-1", "ascii"}:
                response.encoding = response.apparent_encoding or "utf-8"
            parsed = _parse_prtinfo(response.text)
            if parsed:
                parsed["online"] = True
                parsed["source"] = "http"
                parsed["status_priority"] = 1
                return parsed
        except requests.RequestException as exc:
            last_error = exc
            continue
    if last_error:
        return {"online": False, "source": "http", "errors": [f"HTTP: {last_error}"]}
    return None


def _parse_prtinfo(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "lxml")
    if "SEIKO EPSON" not in html and "EPSON" not in html:
        return None
    model = _text(soup.select_one("span.header")) or (soup.title.string.strip() if soup.title and soup.title.string else None)
    status_node = soup.select_one("#PRT_STATUS .preserve-white-space, #PRT_STATUS li div, #PRT_STATUS li")
    status = _text(status_node)
    if status:
        status = re.sub(r"\s+", " ", status).strip(" .")
        if status.lower() in {"k dispozici", "available", "ready"}:
            status = "Ready"
    network = _network_table(soup)
    return {
        "model": model,
        "status": status or "Ready",
        "console": status,
        "mac": network.get("mac"),
        "supplies": _ink_levels(soup),
        "firmware": _firmware(html),
    }


def _ink_levels(soup: BeautifulSoup) -> list[dict[str, Any]]:
    supplies = []
    for tank in soup.select("ul.inksection li.tank"):
        img = tank.select_one("img.color")
        label = _text(tank.select_one(".clrname")) or ""
        src = (img.get("src") if img else "") or ""
        height = _int(img.get("height") if img else None)
        is_waste = "waste" in src.lower() or "mbicn" in str(tank)
        kind = "waste" if is_waste else "ink"
        color = "waste" if is_waste else _color(label, src)
        name = "Maintenance box" if is_waste else f"{label or color.upper()} Ink"
        percent = None
        if height is not None:
            percent = max(0, min(100, round(height / INK_MAX_PX * 100)))
        supplies.append(
            {
                "id": f"http-{color}",
                "name": name,
                "kind": kind,
                "color": color,
                "percent": percent,
                "level": height,
                "max": INK_MAX_PX,
            }
        )
    return supplies


def _network_table(soup: BeautifulSoup) -> dict[str, str]:
    info: dict[str, str] = {}
    for row in soup.select("#info-network tr"):
        key = _text(row.select_one(".item-key")) or ""
        value = _text(row.select_one(".item-value"))
        if not value:
            continue
        key_l = key.lower()
        if "mac" in key_l:
            info["mac"] = value
        elif "název" in key_l or "device name" in key_l:
            info["device_name"] = value
    return info


def _firmware(html: str) -> str | None:
    match = re.search(r"Aktuální verze:([0-9A-Z.]+)", html)
    if match:
        return match.group(1)
    match = re.search(r"Current version:([0-9A-Z.]+)", html, re.I)
    return match.group(1) if match else None


def _color(label: str, src: str) -> str:
    blob = f"{label} {src}".lower()
    if "ink_k" in blob or blob.strip() in {"bk", "k", "black"}:
        return "black"
    if "ink_c" in blob or "cyan" in blob:
        return "cyan"
    if "ink_m" in blob or "magenta" in blob:
        return "magenta"
    if "ink_y" in blob or "yellow" in blob:
        return "yellow"
    return "black"


def _text(node) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
