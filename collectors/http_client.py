from __future__ import annotations

import warnings
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

USER_AGENT = "PrinterButler/1.1.0"


def make_session(verify_tls: bool, timeout: float) -> requests.Session:
    session = requests.Session()
    session.verify = verify_tls
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
        }
    )
    session.request_timeout = timeout
    return session


def fetch(
    session: requests.Session,
    url: str,
    *,
    timeout: float | None = None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: Any = None,
    allow_redirects: bool = True,
) -> requests.Response:
    return session.request(
        method,
        url,
        timeout=timeout or getattr(session, "request_timeout", 5),
        headers=headers,
        data=data,
        allow_redirects=allow_redirects,
    )
