"""The LeadSquared transport behind `outbound_webhooks.kind = 'leadsquared'` (D-942).

`apps/workers/outbound_webhooks.py` owns the delivery id, the forensic row and the retry
ladder; this module turns one event into one Lead.Capture call and reports what happened
in the shared `DeliveryResult`. The request shape and its evidence are in
`apps/api/integrations/leadsquared.py`.

Two short reads happen before the call, each in its own transaction that closes before the
network is touched: the credential (sealed access key and secret key) and, for a call event,
the lead's number, which `call.*` bodies never carry.

Hard rule 6 throughout: the keys travel only in the request's query string, which httpx is
never asked to log; nothing here logs a number, a name, a key or a vendor error string.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import text

from apps.api.actions import credentials as creds
from apps.api.db.session import tenant_session
from apps.api.ingest.service import normalize_phone
from apps.api.integrations import leadsquared as lsq
from apps.api.integrations import service
from apps.api.integrations.egress_guard import egress_client

TIMEOUT_S: Final = 10.0


def _refused(reason: str) -> service.DeliveryResult:
    """A verdict the same request would meet again: recorded, never retried."""
    return service.DeliveryResult(
        delivered=False, status_code=None, error=reason, channel=lsq.CHANNEL, transient=False
    )


async def _context(
    *, tenant_id: UUID, credential_ref: str, data: dict[str, Any]
) -> tuple[creds.ResolvedCredential | None, str | None, str | None]:
    """`(credential, phone, name)` read under the tenant's own session (hard rule 1)."""
    try:
        credential_id = UUID(credential_ref)
    except ValueError:
        return None, None, None
    async with tenant_session(tenant_id) as session:
        try:
            credential = await creds.resolve_credential(
                session, tenant_id=tenant_id, credential_id=credential_id
            )
        except creds.CredentialUnusableError:
            credential = None
        phone = normalize_phone(str(data.get("phone") or ""))
        name = data.get("name")
        lead_id = data.get("lead_id")
        if phone is None and lead_id:
            row = (
                await session.execute(
                    text(
                        "SELECT phone_e164, name FROM leads WHERE id = :id AND deleted_at IS NULL"
                    ),
                    {"id": UUID(str(lead_id))},
                )
            ).first()
            if row is not None:
                phone, name = str(row[0]), name or row[1]
    return credential, phone, name if isinstance(name, str) else None


async def push_event(
    *,
    endpoint: dict[str, Any],
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
    client: httpx.AsyncClient | None = None,
) -> service.DeliveryResult:
    """One event → one Lead.Capture. Raises nothing; the caller owns the ladder.

    Lead.Capture is an upsert matched on the phone, so a retried attempt updates the lead
    the first one wrote; no read-back probe is needed the way a sheet append needs one.
    """
    mapping = endpoint.get("mapping") or {}
    host = lsq.host_of(mapping.get("api_host"))
    credential, phone, name = await _context(
        tenant_id=tenant_id, credential_ref=str(endpoint.get("secret") or ""), data=data
    )
    keys = lsq.open_keys(credential.secret) if credential and credential.kind == lsq.KIND else None
    if host is None or keys is None:
        return _refused(lsq.NO_CREDENTIAL_REASON)
    if phone is None:
        return _refused(lsq.NO_PHONE_REASON)
    chosen = mapping.get("fields")
    fields: dict[str, Any] = chosen if isinstance(chosen, dict) else {}
    body = lsq.capture_body(
        event=event,
        data={**data, "name": name},
        phone_e164=phone,
        fields={str(k): str(v) for k, v in fields.items()},
    )
    if body is None:
        return service.DeliveryResult(
            delivered=False,
            status_code=None,
            error=lsq.NOTHING_TO_WRITE_REASON,
            channel=lsq.CHANNEL,
            transient=False,
        )
    query = urlencode({"accessKey": keys.access_key, "secretKey": keys.secret_key})
    url = f"https://{host}{lsq.CAPTURE_PATH}?{query}"

    owns_client = client is None
    http = client or egress_client(timeout=TIMEOUT_S, follow_redirects=False)
    try:
        async with asyncio.timeout(TIMEOUT_S):
            response = await http.post(url, json=body, timeout=TIMEOUT_S, follow_redirects=False)
        status = response.status_code
        if 200 <= status < 300:
            try:
                ok = lsq.capture_ok(response.json())
            except ValueError:
                ok = False
            return service.DeliveryResult(
                delivered=ok,
                status_code=status,
                error=None if ok else lsq.REJECTED_REASON,
                channel=lsq.CHANNEL,
                transient=False if not ok else None,
            )
        if status == 401:
            return service.DeliveryResult(
                delivered=False,
                status_code=status,
                error=lsq.AUTH_FAILED_REASON,
                channel=lsq.CHANNEL,
                transient=False,
            )
        return service.DeliveryResult(
            delivered=False,
            status_code=status,
            error=f"HTTP {status}" if status >= 500 or status == 429 else lsq.REJECTED_REASON,
            channel=lsq.CHANNEL,
        )
    except (httpx.HTTPError, TimeoutError) as exc:
        return service.DeliveryResult(
            delivered=False, status_code=None, error=type(exc).__name__, channel=lsq.CHANNEL
        )
    finally:
        if owns_client:
            await http.aclose()


__all__ = ["push_event"]
