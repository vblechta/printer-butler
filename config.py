from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return _with_defaults(data)


def _with_defaults(data: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(data)
    listen = cfg.setdefault("listen", {})
    listen.setdefault("host", "0.0.0.0")
    listen.setdefault("port", 8080)
    cfg.setdefault("poll_interval_seconds", 20)
    cfg.setdefault("request_timeout_seconds", 5)
    snmp = cfg.setdefault("snmp", {})
    snmp.setdefault("enabled", True)
    snmp.setdefault("community", "public")
    snmp.setdefault("port", 161)
    snmp.setdefault("timeout", 1.5)
    snmp.setdefault("retries", 0)
    http = cfg.setdefault("http", {})
    http.setdefault("enabled", True)
    http.setdefault("verify_tls", False)
    ipp = cfg.setdefault("ipp", {})
    ipp.setdefault("enabled", True)
    alerts = cfg.setdefault("alerts", {})
    alerts.setdefault("nongenuine_toner_as_warning", True)
    printers = cfg.setdefault("printers", [])
    if not isinstance(printers, list):
        raise ValueError("config.yaml: printers must be a list")
    for printer in printers:
        if not isinstance(printer, dict):
            raise ValueError("config.yaml: each printer must be a mapping")
        for field in ("name", "ip", "brand"):
            if not printer.get(field):
                raise ValueError(f"config.yaml: printer is missing '{field}'")
        printer["brand"] = str(printer["brand"]).strip().lower()
        printer.setdefault("location", "")
        printer.setdefault("community", snmp["community"])
    return cfg
