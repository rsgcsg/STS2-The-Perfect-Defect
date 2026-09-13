"""Cloudflare Access application JWT verification; device Bearer auth stays separate."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import jwt

from ..json_boundary import BoundaryError


@dataclass(frozen=True)
class ConsolePrincipal:
    role: str
    devices: tuple[str, ...]
    subject: str = "device"

    @property
    def research(self) -> bool:
        return self.role in {"reviewer", "operator"}

    def public(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "device_ids": list(self.devices),
            "research_metadata": self.research,
            "read_only": True,
        }


class AccessVerifier:
    """Fixed-origin bounded JWKS cache, fail closed on invalid or expired credentials."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        principals: list[dict[str, Any]],
        *,
        fetch_keys: Callable[[], Any] | None = None,
    ) -> None:
        if re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer) is None:
            raise BoundaryError("console", "invalid_access_issuer")
        if re.fullmatch(r"[a-f0-9]{64}", audience) is None:
            raise BoundaryError("console", "invalid_access_audience")
        if not isinstance(principals, list) or not 1 <= len(principals) <= 50:
            raise BoundaryError("console", "invalid_access_allowlist")
        self.principals: dict[str, tuple[str | None, ConsolePrincipal]] = {}
        for item in principals:
            if not isinstance(item, dict) or set(item) - {"email", "subject", "role", "devices"}:
                raise BoundaryError("console", "invalid_access_allowlist")
            email, subject = item.get("email"), item.get("subject")
            devices, role = item.get("devices"), item.get("role")
            if (
                not isinstance(email, str)
                or re.fullmatch(r"[^\s@]+@[^\s@]+", email) is None
                or len(email) > 254
                or email.casefold() in self.principals
                or (subject is not None and (not isinstance(subject, str) or not subject))
                or not isinstance(role, str)
                or role not in {"collector", "reviewer", "operator"}
                or not isinstance(devices, list)
                or not 1 <= len(devices) <= 128
                or any(not isinstance(d, str) or not d or len(d) > 128 or d == "*" for d in devices)
                or len(set(devices)) != len(devices)
            ):
                raise BoundaryError("console", "invalid_access_allowlist")
            self.principals[email.casefold()] = (
                subject,
                ConsolePrincipal(role, tuple(devices), email.casefold()),
            )
        self.issuer, self.audience = issuer, audience
        self.fetch_keys = fetch_keys or self._fetch_keys
        self._keys: dict[str, Any] = {}
        self._refresh_at = 0.0
        self._lock = threading.Lock()

    def _fetch_keys(self) -> Any:
        request = Request(
            self.issuer + "/cdn-cgi/access/certs", headers={"Accept": "application/json"}
        )
        with urlopen(request, timeout=3) as response:
            # Fixed configured origin only, including redirect destination validation.
            if response.geturl() != request.full_url:
                raise BoundaryError("console", "access_key_origin_changed")
            raw = response.read(65537)
        if len(raw) > 65536:
            raise BoundaryError("console", "access_keys_too_large")
        return json.loads(raw)

    def authenticate(self, token: str) -> ConsolePrincipal:
        try:
            if not token or len(token) > 16384:
                raise ValueError("invalid token")
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError("invalid algorithm")
            with self._lock:
                now = time.monotonic()
                if now >= self._refresh_at:
                    # Negative cache also bounds network work for attacker-controlled kid values.
                    self._refresh_at = now + 60
                    self._keys = {}
                    keys = jwt.PyJWKSet.from_dict(self.fetch_keys()).keys
                    self._keys = {
                        key.key_id: key.key
                        for key in keys
                        if key.key_id is not None
                        and key.key_type == "RSA"
                        and key.public_key_use in {None, "sig"}
                    }
                key = self._keys.get(header["kid"])
            if key is None:
                raise ValueError("unknown key")
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "email", "type"]},
            )
            if claims["type"] != "app" or not isinstance(claims["email"], str):
                raise ValueError("invalid application token")
            required_subject, principal = self.principals[claims["email"].casefold()]
            if required_subject is not None and claims["sub"] != required_subject:
                raise ValueError("subject mismatch")
            return principal
        except Exception:
            # Token, email and provider response must never enter error bodies/logs.
            raise BoundaryError("console", "unauthorized") from None


def configured_access(environment: Mapping[str, str]) -> AccessVerifier | None:
    names = ("STPD_ACCESS_ISSUER", "STPD_ACCESS_AUDIENCE", "STPD_ACCESS_ALLOWLIST")
    values = tuple(environment.get(name, "") for name in names)
    if not any(values):
        return None
    if not all(values):
        raise BoundaryError("console", "access_configuration_incomplete")
    path = Path(values[2])
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or (os.name != "nt" and info.st_mode & 0o077)
        or info.st_size > 65536
    ):
        raise BoundaryError("console", "private_bounded_access_allowlist_required")
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict) or set(payload) != {"schema", "principals"}:
        raise BoundaryError("console", "invalid_access_allowlist")
    if payload["schema"] != "stpd/console-access-v1":
        raise BoundaryError("console", "invalid_access_allowlist")
    return AccessVerifier(values[0], values[1], payload["principals"])
