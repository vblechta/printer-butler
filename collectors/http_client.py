from __future__ import annotations

import ssl
import warnings
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.ssl_ import create_urllib3_context

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

USER_AGENT = "PrinterButler/1.1.0"


class TLS12Adapter(HTTPAdapter):
    """Xerox IPPS often fails the default OpenSSL 3 handshake; force TLS 1.2."""

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:
            pass
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def make_session(verify_tls: bool, timeout: float) -> requests.Session:
    session = requests.Session()
    session.verify = verify_tls
    session.mount("https://", TLS12Adapter())
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
