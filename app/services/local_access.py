"""Is a request (or a URL) on this machine?

Nomad Studio listens on the whole network so other computers can use it from
a browser. Some actions must still only be possible sitting at the machine
where it is installed:

- destructive ones (reset, restore or delete a backup), because a click on a
  laptop would wipe the main computer's real data;
- ones that act on the server's desktop (native folder pickers, opening a
  folder), because the window would appear on the other machine.

Routes use ``@local_only``; pages ask ``request_is_local()`` to disable the
buttons with an explanation instead of failing on click.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

from flask import jsonify, request

_OWN_TTL = 60.0
_own_cache: tuple[float, set[str]] = (0.0, set())


def _own_addresses() -> set[str]:
    """This machine's own IP addresses (cached for a minute)."""
    global _own_cache
    stamp, addrs = _own_cache
    if time.time() - stamp < _OWN_TTL and addrs:
        return addrs
    found: set[str] = set()
    try:
        name = socket.gethostname()
        found.update(info[4][0].split("%")[0] for info in socket.getaddrinfo(name, None))
    except OSError:
        pass
    # The address used to reach the network, even when the hostname lookup
    # misses it (no packet is sent: UDP connect only picks a route).
    for probe in (("10.255.255.255", 1), ("fd00::1", 1)):
        family = socket.AF_INET6 if ":" in probe[0] else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as s:
                s.connect(probe)
                found.add(s.getsockname()[0].split("%")[0])
        except OSError:
            pass
    _own_cache = (time.time(), found)
    return found


def is_local_address(addr: str) -> bool:
    addr = str(addr or "").strip().split("%")[0]
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_unspecified:
        return True
    return str(ip) in _own_addresses()


def is_local_url(url: str) -> bool:
    """True when *url* points at this machine (loopback or one of its own
    addresses)."""
    host = (urlparse(url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return any(is_local_address(a) for a in addrs)


def request_is_local() -> bool:
    """The browser making this request runs on the machine Nomad Studio is
    installed on. Uses the socket address only — never X-Forwarded-For,
    which any client could fake."""
    return is_local_address(request.remote_addr or "")


def local_only(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if not request_is_local():
            return jsonify({
                "ok": False,
                "localOnly": True,
                "error": "This action is only available on the computer where Nomad Studio is installed.",
            }), 403
        return view(*args, **kwargs)

    return wrapper
