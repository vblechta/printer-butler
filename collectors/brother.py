from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from collectors.http_client import fetch

TONER_MAX_PX = 40


def collect(session: requests.Session, printer: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    urls = [
        f"http://{printer['ip']}/home/status.html",
        f"https://{printer['ip']}/home/status.html",
        f"http://{printer['ip']}/",
    ]
    last_error = None
    for url in urls:
        try:
            response = fetch(session, url, timeout=timeout)
            if response.status_code >= 400 or not response.text:
                continue
            parsed = _parse_status_html(response.text)
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


def _parse_status_html(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "lxml")
    model = _text(soup.select_one("#modelName")) or _title_model(soup)
    if not model and "Brother" not in html:
        return None
    status = _device_status(soup)
    location, contact = _location_contact(soup)
    alerts = []
    if soup.select_one(".nongenuine") or "Non Brother Toner" in html:
        alerts.append("Non-genuine toner")
    return {
        "model": model,
        "status": status or "Ready",
        "console": status,
        "supplies": _toner_levels(soup),
        "alerts": alerts,
        "location_hint": location,
        "contact": contact,
    }


def _title_model(soup: BeautifulSoup) -> str | None:
    title = soup.title.string if soup.title else None
    if not title:
        return None
    return title.replace("Brother", "").strip() or title.strip()


def _device_status(soup: BeautifulSoup) -> str | None:
    moni = soup.select_one("#moni_data span, #moni_data")
    if moni is None:
        return None
    classes = " ".join(moni.get("class") or [])
    mapping = {
        "moniOk": "Ready",
        "moniok": "Ready",
        "moniWarning": "Warning",
        "moniError": "Error",
        "moniNg": "Error",
        "moniOffline": "Offline",
    }
    for cls, label in mapping.items():
        if cls.lower() in classes.lower():
            return label
    text = moni.get_text(" ", strip=True)
    return text or None


def _toner_levels(soup: BeautifulSoup) -> list[dict[str, Any]]:
    supplies = []
    for img in soup.select("#ink_level img.tonerremain, #ink_level img"):
        alt = (img.get("alt") or "").strip()
        height = _int(img.get("height"))
        color = _color(alt)
        max_px = max(TONER_MAX_PX, height or 0) or TONER_MAX_PX
        percent = None
        if height is not None:
            percent = max(0, min(100, round(height / max_px * 100)))
        name = alt or color.title()
        if "low" in name.lower() or name.lower() in {"bk", "k"}:
            name = "Black" if color == "black" else color.title()
        supplies.append(
            {
                "id": f"http-{color}",
                "name": f"{name} Toner" if "toner" not in name.lower() else name,
                "kind": "toner",
                "color": color,
                "percent": percent,
                "level": height,
                "max": TONER_MAX_PX,
            }
        )
    return supplies


def _location_contact(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    location = soup.select_one("li.location")
    contact = soup.select_one("li.contact")
    return _colon_value(location), _colon_value(contact)


def _colon_value(node) -> str | None:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    if ":" in text:
        return text.split(":", 1)[1].strip() or None
    return text or None


def _color(label: str) -> str:
    text = label.lower()
    if text in {"bk", "k", "black"} or "black" in text:
        return "black"
    if text in {"c", "cyan"} or "cyan" in text:
        return "cyan"
    if text in {"m", "magenta"} or "magenta" in text:
        return "magenta"
    if text in {"y", "yellow"} or "yellow" in text:
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
