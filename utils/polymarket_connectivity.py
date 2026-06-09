"""
Polymarket connectivity helpers: DNS hijack detection, retries, shared HTTP session.

Some ISPs (e.g. Excitel in India) hijack DNS for polymarket.com domains and return
a block page IP. When system DNS differs from public DNS, we can auto-bypass by
patching socket resolution to use Cloudflare/public resolver answers.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

POLYMARKET_HOSTS = (
    "gamma-api.polymarket.com",
    "clob.polymarket.com",
    "ws-subscriptions-clob.polymarket.com",
    "data-api.polymarket.com",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; PolymarketBot/1.0; +https://polymarket.com)"
)
DEFAULT_DNS_SERVERS = ("1.1.1.1", "8.8.8.8")
REQUEST_TIMEOUT = int(os.getenv("POLYMARKET_HTTP_TIMEOUT", "20"))

_dns_patch_installed = False
_host_ip_overrides: dict[str, str] = {}
_original_getaddrinfo = socket.getaddrinfo
_connectivity_status: Optional[dict] = None
_session: Optional[requests.Session] = None


def _dns_servers() -> tuple[str, ...]:
    raw = os.getenv("POLYMARKET_DNS_SERVERS", "")
    if raw.strip():
        return tuple(s.strip() for s in raw.split(",") if s.strip())
    return DEFAULT_DNS_SERVERS


def _auto_fix_enabled() -> bool:
    return os.getenv("POLYMARKET_DNS_AUTO_FIX", "true").lower() in ("true", "1", "yes")


def _parse_host_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    raw = os.getenv("POLYMARKET_HOST_OVERRIDES", "")
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        host, ip = part.rsplit(":", 1)
        overrides[host.strip()] = ip.strip()
    return overrides


def resolve_via_dns(hostname: str, dns_server: str) -> list[str]:
    """Resolve A records using an explicit DNS server (dig)."""
    try:
        result = subprocess.run(
            ["dig", f"@{dns_server}", "+short", hostname, "A"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    ips: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and "." in line and not line.startswith(";"):
            ips.append(line)
    return ips


def resolve_system(hostname: str) -> list[str]:
    try:
        infos = _original_getaddrinfo(
            hostname, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror:
        return []
    return list({info[4][0] for info in infos})


def resolve_public(hostname: str) -> list[str]:
    for server in _dns_servers():
        ips = resolve_via_dns(hostname, server)
        if ips:
            return ips
    return []


def detect_dns_hijack(hostname: str) -> Optional[str]:
    """Return a human-readable hijack message, or None if DNS looks OK."""
    system_ips = resolve_system(hostname)
    public_ips = resolve_public(hostname)

    if not public_ips:
        if not system_ips:
            return f"Cannot resolve {hostname}"
        return None

    if not system_ips:
        return f"System DNS failed for {hostname} (public DNS: {public_ips[0]})"

    if set(system_ips).isdisjoint(set(public_ips)):
        block_hint = ""
        if any("block" in ip for ip in system_ips):
            block_hint = " (block page)"
        try:
            reverse = socket.gethostbyaddr(system_ips[0])[0]
            if "block" in reverse.lower():
                block_hint = f" ({reverse})"
        except (socket.herror, OSError):
            pass
        return (
            f"ISP DNS hijack on {hostname}: system={system_ips[0]}{block_hint}, "
            f"expected CDN IP like {public_ips[0]}. Use VPN or set POLYMARKET_DNS_SERVERS=1.1.1.1"
        )
    return None


def build_host_overrides() -> dict[str, str]:
    """Build hostname -> IP overrides for blocked Polymarket hosts."""
    overrides = _parse_host_overrides()
    if overrides:
        return overrides

    if not _auto_fix_enabled():
        return {}

    for host in POLYMARKET_HOSTS:
        if host in overrides:
            continue
        hijack = detect_dns_hijack(host)
        if not hijack:
            continue
        public_ips = resolve_public(host)
        if public_ips:
            overrides[host] = public_ips[0]
            logger.warning("%s — auto-fixing via public DNS -> %s", hijack, public_ips[0])
    return overrides


def install_dns_patch(force: bool = False) -> bool:
    """Patch socket.getaddrinfo to bypass ISP DNS hijacks. Idempotent."""
    global _dns_patch_installed, _host_ip_overrides

    if _dns_patch_installed and not force:
        return bool(_host_ip_overrides)

    _host_ip_overrides = build_host_overrides()
    if not _host_ip_overrides:
        _dns_patch_installed = True
        return False

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and host in _host_ip_overrides:
            ip = _host_ip_overrides[host]
            return _original_getaddrinfo(
                ip, port, family, type, proto, flags,
            )
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = patched_getaddrinfo  # type: ignore[assignment]
    _dns_patch_installed = True
    logger.info(
        "Polymarket DNS override active for: %s",
        ", ".join(sorted(_host_ip_overrides)),
    )
    return True


def create_requests_session() -> requests.Session:
    global _session
    if _session is not None:
        return _session

    install_dns_patch()
    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    })
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _session = session
    return session


def gamma_get(path: str, **kwargs) -> requests.Response:
    install_dns_patch()
    session = create_requests_session()
    base = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
    return session.get(url, timeout=timeout, **kwargs)


def clob_get(path: str, **kwargs) -> requests.Response:
    install_dns_patch()
    session = create_requests_session()
    base = os.getenv("POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
    return session.get(url, timeout=timeout, **kwargs)


def check_polymarket_connectivity() -> dict:
    """
    Probe Gamma HTTP + DNS state. Cached for the process lifetime unless force=True.
    """
    global _connectivity_status

    hijack_messages = []
    for host in ("gamma-api.polymarket.com", "ws-subscriptions-clob.polymarket.com"):
        msg = detect_dns_hijack(host)
        if msg:
            hijack_messages.append(msg)

    dns_auto_fixed = install_dns_patch()

    gamma_ok = False
    gamma_detail = ""
    try:
        resp = gamma_get("/events", params={"limit": 1}, timeout=REQUEST_TIMEOUT)
        gamma_ok = resp.ok
        gamma_detail = f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        gamma_detail = str(exc)

    reachable = gamma_ok
    if hijack_messages and not dns_auto_fixed and not gamma_ok:
        action = (
            "Polymarket appears blocked on your network. Try: "
            "(1) VPN to US/EU, (2) set system DNS to 1.1.1.1, "
            "(3) POLYMARKET_DNS_AUTO_FIX=true (default), or "
            "(4) POLYMARKET_HOST_OVERRIDES=gamma-api.polymarket.com:IP,..."
        )
    elif hijack_messages and dns_auto_fixed and gamma_ok:
        action = "ISP DNS hijack detected and auto-bypassed via public DNS."
    elif not gamma_ok:
        action = "Polymarket Gamma API unreachable — check firewall/VPN."
    else:
        action = "OK"

    _connectivity_status = {
        "reachable": reachable,
        "gamma_ok": gamma_ok,
        "gamma_detail": gamma_detail,
        "dns_hijack": hijack_messages,
        "dns_auto_fixed": dns_auto_fixed,
        "action": action,
    }
    return _connectivity_status


def get_ws_headers() -> dict[str, str]:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Origin": "https://polymarket.com",
    }


def ws_connect_header_kwargs(headers: dict[str, str]) -> dict[str, dict[str, str]]:
    """Return websockets.connect() kwargs for custom HTTP headers (version-compatible)."""
    import inspect

    import websockets

    param = (
        "additional_headers"
        if "additional_headers" in inspect.signature(websockets.connect).parameters
        else "extra_headers"
    )
    return {param: headers}


def host_from_ws_url(url: str) -> str:
    return urlparse(url).hostname or ""
