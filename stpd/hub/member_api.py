"""Authenticated member route composition, independent of HTTP cookies and transport.

The caller verifies browser JWT/personal token on every request and applies exact Origin
and CSRF checks to browser writes. This helper rechecks current durable membership, never
accepts a device token or uses query/body claims as an identity. Admin creation is separate.

Owner CLI hooks (not member routes):
    refresh_project_statistics(service, upload_ids=(ID,), dataset_ids=())
    grant_collection_sharing(service, upload_id=ID, approved=True,
                             evidence_ref=SHA256, actor=OWNER)
Neither hook admits training, rewrites receipts or derives consent from a timestamp.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, cast

from ..collection_activity import ENROLLMENT_SCHEMA, validate_enrollment
from ..json_boundary import BoundaryError, decode_json, digest, object_fields
from .campaigns import Campaigns
from .console_auth import ConsolePrincipal
from .console_index import pagination, timestamp
from .exports import ExportService
from .identity import IdentityService
from .statistics import refresh_decision_statistics
from .uploads import UploadService


class MemberApi:
    def __init__(self, service: UploadService, identity: IdentityService) -> None:
        if service.operations.path.resolve() != identity.ops.path.resolve():
            raise BoundaryError("member_api", "identity_store_mismatch")
        self.service, self.identity = service, identity
        self.campaigns = Campaigns(service.operations, identity.membership)
        self.exports = ExportService(service)

    def _principal(self, principal: ConsolePrincipal) -> ConsolePrincipal:
        with self.service.operations.transaction() as db:
            # Activation belongs to the signed identity boundary, not a data API request.
            return self.identity.membership.authorize(db, principal)

    def read(self, route: str, query: str, principal: ConsolePrincipal) -> dict[str, Any]:
        current = self._principal(principal)
        if route in {"campaigns", "campaigns/enrollments"}:
            limit, offset, status = pagination(query)
            if status is not None:
                raise BoundaryError("member_api", "unexpected_status_filter")
            if route == "campaigns":
                return {
                    **self.campaigns.list(current, limit=limit, offset=offset),
                    "limit": limit,
                    "offset": offset,
                    "observed_at": timestamp(),
                }
            return self._enrollments(current, limit=limit, offset=offset)
        if query:
            raise BoundaryError("member_api", "unexpected_query")
        enrollment = re.fullmatch(r"campaigns/enrollments/([a-f0-9]{32})", route)
        if enrollment:
            return cast(
                dict[str, Any], self._enrollments(current, enrollment_id=enrollment[1])["item"]
            )
        export = re.fullmatch(r"exports/([a-f0-9]{64})", route)
        if export:
            return self.exports.read(current, export[1])
        raise BoundaryError("member_api", "resource_not_found")

    def write(self, route: str, body: object, principal: ConsolePrincipal) -> dict[str, Any]:
        current = self._principal(principal)
        enrollment = re.fullmatch(r"campaigns/([a-f0-9]{64})/enroll", route)
        if enrollment:
            value = object_fields(body, {"device_id", "consent"}, "campaign.enroll")
            return self.campaigns.enroll(
                current, enrollment[1], value["device_id"], value["consent"]
            )
        if route == "exports":
            return self.exports.create(current, body)
        # No admin, compute, grants or implicit enrollment mutations on this surface.
        raise BoundaryError("member_api", "resource_not_found")

    def admin_create_campaign(self, body: object, principal: ConsolePrincipal) -> dict[str, Any]:
        """Called only after fresh browser identity + Origin + CSRF; owner repeats admin check."""
        return self.campaigns.create(principal, body)

    def payload(
        self,
        export_id: str,
        file_id: str,
        principal: ConsolePrincipal,
    ) -> tuple[dict[str, Any], Iterator[bytes]]:
        current = self._principal(principal)
        return self.exports.payload(current, export_id, file_id)

    def _enrollments(
        self,
        principal: ConsolePrincipal,
        *,
        limit: int = 25,
        offset: int = 0,
        enrollment_id: str | None = None,
    ) -> dict[str, Any]:
        # Enrollment consent is member-private. Even an administrator does not borrow
        # another member's declaration to prepare this computer's collection directory.
        where = "e.subject=? AND d.owner_subject=e.subject AND d.active=1"
        values: tuple[Any, ...] = (principal.subject,)
        if enrollment_id is not None:
            digest(enrollment_id, "campaign.enrollment_id", length=32)
            where += " AND e.id=?"
            values += (enrollment_id,)
        joined = (
            " FROM collection_enrollments e JOIN collection_activities a ON a.id=e.template_id "
            "JOIN devices d ON d.id=e.device_id WHERE " + where
        )
        with self.service.operations.transaction() as db:
            self.identity.membership.authorize(db, principal)
            total = db.execute("SELECT COUNT(*)" + joined, values).fetchone()[0]
            rows = db.execute(
                "SELECT e.*,a.template"
                + joined
                + " ORDER BY e.created_at DESC,e.id LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
        items = [
            validate_enrollment(
                {
                    "schema": ENROLLMENT_SCHEMA,
                    "enrollment_id": row["id"],
                    "template_id": row["template_id"],
                    "template": decode_json(row["template"]),
                    "device_id": row["device_id"],
                    "campaign_id": "campaign-" + row["id"],
                    "consent": decode_json(row["consent"]),
                    "declared_at": row["created_at"],
                    "human_origin_verified": False,
                }
            )
            for row in rows
        ]
        if enrollment_id is not None and not items:
            raise BoundaryError("campaign", "enrollment_not_found")
        return {
            "schema": "stpd/member-enrollments-v1",
            "items": items,
            **({"item": items[0]} if enrollment_id is not None else {}),
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
            "observed_at": timestamp(),
        }


def refresh_project_statistics(
    service: UploadService,
    *,
    upload_ids: tuple[str, ...] = (),
    dataset_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Explicit owner CLI operation; heavy bounded profiling never runs on HTTP GET."""
    return refresh_decision_statistics(service, upload_ids=upload_ids, dataset_ids=dataset_ids)


def grant_collection_sharing(
    service: UploadService,
    *,
    upload_id: str,
    approved: bool,
    evidence_ref: str,
    actor: str,
) -> dict[str, Any]:
    """Explicit owner CLI approval/revocation tied to an immutable approval evidence digest.

    This is not callable through MemberApi.write. The owner must establish the actual
    authorization before invoking it; neither membership nor upload implies consent.
    """
    exports = ExportService(service)
    exports.set_collection_access(
        upload_id, approved=approved, evidence_ref=evidence_ref, actor=actor
    )
    return {"upload_id": upload_id, **exports.collection_access([upload_id])[upload_id]}
