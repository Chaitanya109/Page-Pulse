"""URL validation and SSRF (Server-Side Request Forgery) protections.

Because this service fetches arbitrary user-supplied URLs on the
server's behalf, it is a textbook SSRF vector: without safeguards, a
caller could ask the service to fetch ``http://169.254.169.254/`` (a
cloud metadata endpoint) or an internal-only admin panel and relay the
response back. We defend against this in two layers:

1. Structural validation — scheme allow-list, length limit, a
   syntactically valid host.
2. Network-level validation — resolve the hostname and reject any
   result that lands in a private, loopback, link-local, or otherwise
   reserved address range.

Layer 2 intentionally happens at request time (not just at the
scheme/host-string level) to also catch DNS-rebinding style attacks
where a public-looking hostname resolves to a private IP.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import Settings
from app.core.exceptions import URLNotAllowedError, URLValidationError

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def validate_url_structure(raw_url: str, settings: Settings) -> str:
    """Validate scheme, length and basic shape. Returns the normalized URL string.

    Raises ``URLValidationError`` for anything structurally invalid.
    """
    if not raw_url or not raw_url.strip():
        raise URLValidationError("The 'url' field must not be empty.")

    if len(raw_url) > settings.max_url_length:
        raise URLValidationError(
            f"URL exceeds the maximum allowed length of {settings.max_url_length} characters.",
            details={"length": len(raw_url), "max_length": settings.max_url_length},
        )

    parsed = urlparse(raw_url.strip())

    if parsed.scheme not in settings.allowed_schemes:
        raise URLValidationError(
            f"URL scheme '{parsed.scheme or ''}' is not allowed. "
            f"Allowed schemes: {', '.join(settings.allowed_schemes)}.",
            details={"scheme": parsed.scheme, "allowed_schemes": list(settings.allowed_schemes)},
        )

    if not parsed.hostname:
        raise URLValidationError("URL must include a valid hostname.")

    return parsed.geturl()


def _is_blocked_address(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def enforce_ssrf_guard(raw_url: str, settings: Settings) -> None:
    """Resolve the hostname and reject requests targeting non-public networks.

    Raises ``URLNotAllowedError`` if the resolved address (or any of
    its resolved addresses) is private, loopback, link-local, or
    otherwise not routable on the public internet.
    """
    if not settings.block_private_networks:
        return

    hostname = urlparse(raw_url).hostname
    if hostname is None:
        raise URLValidationError("URL must include a valid hostname.")

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise URLNotAllowedError(
            "This hostname is not permitted for auditing.",
            details={"hostname": hostname},
        )

    # If the hostname is already a literal IP, validate it directly.
    try:
        ipaddress.ip_address(hostname)
        if _is_blocked_address(hostname):
            raise URLNotAllowedError(
                "This URL resolves to a private or reserved network and cannot be audited.",
                details={"hostname": hostname},
            )
        return
    except ValueError:
        pass  # not a literal IP; fall through to DNS resolution

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise URLValidationError(
            f"Could not resolve hostname '{hostname}'.",
            details={"hostname": hostname, "reason": str(exc)},
        ) from exc

    for _family, _, _, _, sockaddr in resolved:
        ip = sockaddr[0]
        if _is_blocked_address(ip):
            raise URLNotAllowedError(
                "This URL resolves to a private or reserved network and cannot be audited.",
                details={"hostname": hostname, "resolved_ip": ip},
            )
