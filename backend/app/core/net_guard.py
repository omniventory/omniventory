"""SSRF guard for outbound URLs and bare broker hosts (M6 Step 7 §4.7).

``validate_outbound_url(url)``
    Validates a full URL (scheme + host) for outbound webhook use.  Raises
    ``UnsafeUrlError`` on any rejection.

``validate_broker_host(host)``
    Applies the same IP block-list to a bare MQTT broker host.

Block set
---------
Any resolved IP that matches **any** of the following is rejected:

- Loopback          (127.0.0.0/8, ::1)
- Link-local / APIPA (169.254.0.0/16 incl. 169.254.169.254, fe80::/10)
- Unspecified       (0.0.0.0, ::)
- Multicast         (224.0.0.0/4, ff00::/8)
- Reserved          (240.0.0.0/4 — IANA experimental; via ``ip.is_reserved``)

Allow set (NOT blocked)
-----------------------
- Private LAN: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7
  (these have ``ip.is_private=True`` but ``ip.is_reserved=False`` in Python)
- All public IPs

Rationale (§4.7)
-----------------
The guard is defense-in-depth for admin-configured URLs.  It blocks the
AWS metadata endpoint (169.254.169.254) and loopback-to-self attacks, but
intentionally **allows private LAN** so Home Assistant on 192.168.x.x or
a local webhook on 10.x.x.x keeps working.

DNS TOCTOU note
---------------
There is an inherent resolve-then-connect race (DNS rebinding); the guard
accepts this limitation because the webhook URL is admin-configured and
rarely changes.

Scheme check
------------
Only ``http`` and ``https`` are allowed for outbound webhook URLs.
``ftp://``, ``file://``, missing schemes, and URLs without a host are
rejected before DNS resolution.
"""

from __future__ import annotations

import ipaddress
import socket
import warnings
from urllib.parse import urlparse

# Schemes accepted for outbound webhook calls.
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(ValueError):
    """Raised by ``validate_outbound_url`` / ``validate_broker_host`` when the
    target fails the SSRF guard.

    Subclasses ``ValueError`` so it is caught by broad ``except Exception``
    handlers (e.g. the webhook delivery ``except`` block) without needing a
    special import at each call site.
    """


# ---------------------------------------------------------------------------
# IP classification helpers
# ---------------------------------------------------------------------------


def _is_reserved_compat(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return ``True`` if the IP is in an IANA-reserved range.

    ``ip.is_reserved`` was deprecated in Python 3.11 and emits a
    ``DeprecationWarning`` in 3.13.  We suppress the warning here and fall
    back to ``False`` if the attribute is removed in a future version.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            return bool(ip.is_reserved)
        except AttributeError:  # pragma: no cover — safety for future Python
            return False


def _is_blocked_ip(addr: str) -> bool:
    """Return ``True`` if *addr* must be blocked by the SSRF guard.

    Private LAN (RFC 1918 + fc00::/7 ULA) is **not** blocked.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # Unparseable → reject defensively.

    if ip.is_loopback:
        return True
    if ip.is_link_local:
        return True
    if ip.is_unspecified:
        return True
    if ip.is_multicast:
        return True
    # is_reserved covers IANA-experimental ranges (240.0.0.0/4 etc.).
    # Private LAN addresses are NOT reserved in Python's ipaddress, so the
    # "allow private LAN" rule is implicitly satisfied by not blocking on is_private.
    return bool(_is_reserved_compat(ip))


def _resolve_and_validate(host: str) -> None:
    """Resolve *host* to IP addresses and reject any blocked one.

    Raises
    ------
    UnsafeUrlError
        If DNS resolution fails **or** any resolved address is blocked.
    """
    try:
        results = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Host {host!r} could not be resolved: {exc}") from exc

    if not results:
        raise UnsafeUrlError(f"Host {host!r} resolved to no addresses.")

    for _family, _type, _proto, _canonname, sockaddr in results:
        # sockaddr[0] is the IP address string for both AF_INET and AF_INET6.
        addr = str(sockaddr[0])
        if _is_blocked_ip(addr):
            raise UnsafeUrlError(f"Host {host!r} resolves to blocked address {addr!r}.")


# ---------------------------------------------------------------------------
# Public validators
# ---------------------------------------------------------------------------


def validate_outbound_url(url: str) -> None:
    """Validate a full outbound URL before the webhook POST.

    Checks performed (in order):
    1. Scheme must be ``http`` or ``https``.
    2. A non-empty host must be present.
    3. DNS resolution must succeed and no resolved IP may be blocked.

    Parameters
    ----------
    url:
        The webhook URL to validate (e.g. ``"https://hooks.example.com/…"``).

    Raises
    ------
    UnsafeUrlError
        On any validation failure.  The caller's ``except Exception`` block
        records this as a failed delivery (best-effort; the webhook is skipped).
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:  # pragma: no cover
        raise UnsafeUrlError(f"URL parse error: {exc}") from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Scheme {parsed.scheme!r} is not allowed (must be http or https).")

    host = parsed.hostname  # None when netloc is empty.
    if not host:
        raise UnsafeUrlError("URL has no host component.")

    _resolve_and_validate(host)


def validate_broker_host(host: str) -> None:
    """Validate a bare MQTT broker hostname before connecting.

    Applies the same IP block-list as ``validate_outbound_url`` to a bare
    host string (no scheme or path).

    Parameters
    ----------
    host:
        The MQTT broker hostname or IP (e.g. ``"mqtt.example.com"`` or
        ``"192.168.1.10"``).

    Raises
    ------
    UnsafeUrlError
        If *host* is empty, cannot be resolved, or resolves to a blocked address.
    """
    if not host or not host.strip():
        raise UnsafeUrlError("Broker host is empty.")

    _resolve_and_validate(host.strip())
