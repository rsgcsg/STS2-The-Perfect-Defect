"""Cloudflare Access application JWT verification; device Bearer auth stays separate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
    email: str = ""
    issuer: str = ""
    access_subject: str = ""
    expires_at: float = 0
    session_binding: str = ""
    enroll_devices: bool = False
    device_quota: int = 0
    owned_devices: tuple[str, ...] = ()
    claim_devices: tuple[str, ...] = ()
    member_id: str = ""
    membership_status: str = ""
    data_device: str | None = None

    @property
    def project_shared(self) -> bool:
        return self.role in {"member", "admin"}

    @property
    def research(self) -> bool:
        return self.role in {"member", "admin"}

    def public(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "device_ids": list(self.devices),
            "research_metadata": self.research,
            "read_only": True,
            "subject": self.subject,
            "email": self.email,
            "enroll_devices": self.enroll_devices,
            "device_quota": self.device_quota,
            "owned_device_ids": list(self.owned_devices),
            "member_id": self.member_id,
            "membership_status": self.membership_status,
            "project_shared": self.project_shared,
        }


class AccessVerifier:
    """Fixed-origin bounded JWKS cache, fail closed on invalid or expired credentials."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        fetch_keys: Callable[[], Any] | None = None,
    ) -> None:
        if re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer) is None:
            raise BoundaryError("console", "invalid_access_issuer")
        if re.fullmatch(r"[a-f0-9]{64}", audience) is None:
            raise BoundaryError("console", "invalid_access_audience")
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
            if (
                claims["type"] != "app"
                or not isinstance(claims["email"], str)
                or not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 512
            ):
                raise ValueError("invalid application token")
            return replace(
                verified_identity(self.issuer, claims["sub"], claims["email"]),
                expires_at=float(claims["exp"]),
                session_binding=hashlib.sha256(token.encode()).hexdigest(),
            )
        except Exception:
            # Token, email and provider response must never enter error bodies/logs.
            raise BoundaryError("console", "unauthorized") from None


def verified_identity(issuer: str, subject: str, email: str) -> ConsolePrincipal:
    """A verified identity is not membership. Only Hub Operations may grant a role."""
    if (
        not isinstance(email, str)
        or re.fullmatch(r"[^\s@]+@[^\s@]+", email) is None
        or len(email) > 254
    ):
        raise BoundaryError("console", "unauthorized")
    stable = hashlib.sha256(json.dumps([issuer, subject]).encode()).hexdigest()
    return ConsolePrincipal(
        "authenticated",
        (),
        subject=stable,
        issuer=issuer,
        access_subject=subject,
        email=email.casefold(),
    )


def configured_access(environment: Mapping[str, str]) -> AccessVerifier | None:
    # The former file is migration input only, never a live fallback authority.
    if environment.get("STPD_ACCESS_ALLOWLIST"):
        raise BoundaryError("console", "legacy_allowlist_requires_explicit_membership_import")
    issuer = environment.get("STPD_ACCESS_ISSUER", "")
    audience = environment.get("STPD_ACCESS_AUDIENCE", "")
    if not issuer and not audience:
        return None
    if not issuer or not audience:
        raise BoundaryError("console", "access_configuration_incomplete")
    return AccessVerifier(issuer, audience)


def validate_legacy_principals(principals: Any) -> list[dict[str, Any]]:
    """Strict, bounded one-time migration codec; old roles confer no administrator grant."""
    if not isinstance(principals, list) or not 1 <= len(principals) <= 50:
        raise BoundaryError("console", "invalid_access_allowlist")
    seen: set[str] = set()
    for item in principals:
        if not isinstance(item, dict) or set(item) - {
            "email",
            "subject",
            "role",
            "devices",
            "enroll_devices",
        }:
            raise BoundaryError("console", "invalid_access_allowlist")
        email, subject = item.get("email"), item.get("subject")
        devices, role = item.get("devices"), item.get("role")
        if (
            not isinstance(email, str)
            or re.fullmatch(r"[^\s@]+@[^\s@]+", email) is None
            or len(email) > 254
            or email.casefold() in seen
            or (
                subject is not None
                and (not isinstance(subject, str) or not 1 <= len(subject) <= 512)
            )
            or not isinstance(role, str)
            or role not in {"collector", "reviewer", "operator"}
            or not isinstance(devices, list)
            or not 0 <= len(devices) <= 128
            or any(not isinstance(d, str) or not d or len(d) > 128 or d == "*" for d in devices)
            or len(set(devices)) != len(devices)
            or type(item.get("enroll_devices", False)) is not bool
        ):
            raise BoundaryError("console", "invalid_access_allowlist")
        seen.add(email.casefold())
    return principals


def load_legacy_allowlist(path: Path) -> list[dict[str, Any]]:
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
    return validate_legacy_principals(payload["principals"])
