"""The credential surface (PLATFORM-CONFIG §7).

    GET  /v1/ops/secrets             key, last-4, version, who, when, kek id
    PUT  /v1/ops/secrets/{key}       new version; step-up `set_secret:<key>`
    POST /v1/ops/secrets/{key}/test  dry-run against the vendor BEFORE it goes live

**THERE IS NO READ-BACK ROUTE AND THERE WILL NOT BE ONE.** §7 states the reason and it
is worth repeating where somebody would be tempted to add one: a console that can display
a credential is a console that leaks every credential through one screenshot or one
compromised session. If an operator needs the value, they hold it already — they are the
one who set it. The response models here have no field a plaintext could be assigned to,
so adding a read-back would be a visible, deliberate act rather than a slip.

**What a compromised session with `platform:secrets` can do**, stated plainly because §10
accepts this trade rather than discovering it: it can BREAK the platform, and it can point
our engine at an attacker's own vendor account. It cannot read what is already installed.
Detection, not prevention, is the answer — every write lands a `platform.secret_set` row
in the hash-chained ledger and fires an alert.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.envelope import MASKED, kek_ring, last_four
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import require_step_up
from apps.api.ops.config_service import propagate
from apps.api.ops.secret_probes import ProbeOutcome, probe_credential
from apps.api.ops.secret_service import SecretRecord, read_secrets, rewrap_all, set_secret

router = APIRouter(prefix="/v1/ops/secrets", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
SecretOperator = Annotated[Principal, Depends(requires("platform:secrets", realm="admin"))]

SecretKey = Annotated[str, Path(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]


def secret_confirmation(key: str) -> str:
    """The step-up string for installing ONE credential.

    §7 names it (`set_secret:<key>`) and a runbook will print it, so it is a function
    with a test pinning the literal rather than an f-string inline — the same treatment
    `spend_cap_confirmation` gets, for the same reason.

    Bound to the key: consent to rotating the Sarvam key is not consent to replacing the
    Bolna key with one an attacker controls.
    """
    return f"set_secret:{key}"


class SecretOut(BaseModel):
    """One credential, as much as anyone may ever see of it.

    NO VALUE FIELD, ON ANY ROUTE, EVER. `last_four` is the only fragment that exists, and
    `core/envelope.last_four` masks it entirely below eight characters.

    No field carries a default: the console must not have to write `installed ?? true`
    for a fact that decides whether it offers to rotate or to install.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The variable that sets this credential in the environment. Shown so an operator
    #: can put it back there if they need to take control from the console.
    env_var: str
    #: False when this deployment has never stored one. Distinct from an empty
    #: `last_four`, which a very short credential also produces.
    installed: bool
    #: 0 when nothing is installed; otherwise the live version.
    version: int
    #: How many versions exist. Rotation history without any of its content.
    versions: int
    #: The last four characters, or `••••` for anything too short to have four.
    last_four: str
    #: Which KEK's wrapping this row carries — a FINGERPRINT of the key, not a counter
    #: (D-96). 0 when nothing is installed. The key-management panel counts DEKs by it.
    kek_id: int
    created_at: str | None
    created_by: str | None
    #: True when the ENVIRONMENT also sets this key, in which case the stored value is
    #: INERT: the environment always wins (§4). Without this the console would let an
    #: operator rotate a credential and watch the platform keep using the old one.
    shadowed_by_env: bool
    #: True when this build can ask the vendor whether a candidate works. False means
    #: `/test` will answer `no_probe` rather than a green tick.
    testable: bool
    #: WHEN A ROTATION ACTUALLY REACHES THE CODE THAT USES THIS CREDENTIAL.
    #:
    #: `live` for most, and `on_restart` for the ones a process captures once —
    #: `bolna_api_key` is the important one: the adapter copies it when `get_engine()`
    #: builds it and that instance is cached for the life of the process, so a key
    #: rotated here does NOT reach the code placing calls until every process restarts.
    #: Without this field the Secrets panel implied the opposite, and the symptom of the
    #: gap — the vendor rejecting our calls — sends an operator to the vendor's dashboard
    #: rather than to a restart. Same vocabulary and same source as the config panel's
    #: `applies` (`core/platform_config.FIELD_APPLIES`).
    applies: str
    #: What the operator must still do after rotating, or null. Non-null unless `live`.
    caveat: str | None


class SecretsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secrets: list[SecretOut]


class SecretSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The credential. It is sealed before anything else touches it and is never
    #: returned, logged or traced (§3 rule 6).
    value: str = Field(min_length=1, max_length=8192)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("a reason is required — say why this credential changed")
        return stripped


class SecretTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The CANDIDATE. Tested and discarded — this route stores nothing, which is the
    #: whole point of testing before setting.
    value: str = Field(min_length=1, max_length=8192)


class SecretTestOut(BaseModel):
    """The vendor's verdict, in OUR vocabulary.

    `outcome` is one of `accepted` / `rejected` / `unreachable` / `no_probe`, and the
    last two are deliberately NOT collapsed into a failure: "we could not check this" and
    "the vendor said no" send an operator to different systems.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    # The server's CLOSED set, declared as one so the console can switch on it
    # exhaustively. It was a bare `str` and the generated TypeScript was therefore
    # `string`, which is the untyped-2xx defect D-84 swept three times: a console
    # indexing a lookup table by it cannot be told at compile time that it has missed a
    # case. Unlike `credit_ledger.reason` (a database enum a migration can widen) this
    # set is exhausted by `ProbeResult` in-process, so narrowing it is honest.
    outcome: ProbeOutcome
    #: The vendor's HTTP status, when there was one. Null otherwise.
    status: int | None
    detail: str
    #: False when this probe's refusal behaviour has not been observed against the live
    #: vendor from this build (OPERATIONS §2). An unverified premise is stated, never
    #: hidden behind a tick.
    verified: bool
    #: The last four characters of the CANDIDATE, echoed so an operator can confirm they
    #: tested the value they are about to install. Four characters they typed seconds
    #: ago, masked below eight, and it is the only fragment any route returns.
    candidate_last_four: str


def _out(record: SecretRecord, *, testable: bool) -> SecretOut:
    return SecretOut(
        key=record.key,
        env_var=record.env_var,
        installed=record.version > 0,
        version=record.version,
        versions=record.versions,
        last_four=record.last_four,
        kek_id=record.kek_id,
        created_at=record.created_at or None,
        created_by=record.created_by,
        shadowed_by_env=record.shadowed_by_env,
        testable=testable,
        applies=record.applies,
        caveat=record.caveat,
    )


def _testable(key: str) -> bool:
    from apps.api.ops.secret_probes import PROBES

    return key in PROBES


@router.get(
    "",
    response_model=SecretsOut,
    openapi_extra=permission_meta("platform:secrets"),
    summary="Which credentials are installed — key, last-4, version, who, when",
    description=(
        "Lists every vendor credential this deployment uses, whether one is installed, "
        "its last four characters and who installed it. **No plaintext, ever, on any "
        "route.** A credential the environment also sets is reported "
        "`shadowed_by_env: true` — the environment wins, so the stored value is inert."
    ),
)
async def list_secrets(session: GlobalSession, _: SecretOperator) -> SecretsOut:
    return SecretsOut(
        secrets=[_out(r, testable=_testable(r.key)) for r in await read_secrets(session)]
    )


@router.post(
    "/{key}/test",
    response_model=SecretTestOut,
    openapi_extra=permission_meta("platform:secrets"),
    summary="Ask the vendor whether a candidate credential works — stores nothing",
    description=(
        "Sends ONE cheap authenticated request to the vendor with the candidate value "
        "and reports whether they accepted it. Nothing is stored, so a wrong key is "
        "refused at the screen rather than at the next call. `no_probe` means this build "
        "cannot test that vendor — which is an answer, not a pass."
    ),
)
async def test_secret(
    payload: SecretTestIn,
    request: Request,
    session: GlobalSession,
    principal: SecretOperator,
    key: SecretKey,
) -> SecretTestOut:
    """No step-up, deliberately, and the asymmetry is the argument.

    Every other write on this router changes what the platform authenticates with. This
    one stores NOTHING — it is a read against a vendor with a value the caller already
    holds. Demanding a typed confirmation to run a check would push operators to skip the
    check and set the key directly, which is the exact behaviour `/test` exists to
    prevent. `GET /v1/ops/audit/verify` is unconfirmed for the same reason.

    IT IS STILL AUDITED. §9 lists `platform.secret_tested`, and it matters more than it
    looks: this route sends an operator-supplied value to a third party, so "who sent
    what, to which vendor, when" has to be answerable. The row records the key and the
    outcome — never the candidate.
    """
    result = await probe_credential(key, payload.value)
    await write_audit(
        session,
        action="platform.secret_tested",
        actor=principal,
        object_type="platform_secrets",
        object_id=key,
        ip=client_request_ip(request),
        # The key, the verdict, and four characters the operator typed. No candidate.
        summary={
            "config_key": key,
            "outcome": result.outcome,
            "vendor_status": result.status,
            "candidate_last_four": last_four(payload.value),
        },
    )
    return SecretTestOut(
        key=key,
        outcome=result.outcome,
        status=result.status,
        detail=result.detail,
        verified=result.verified,
        candidate_last_four=last_four(payload.value) or MASKED,
    )


@router.put(
    "/{key}",
    response_model=SecretOut,
    openapi_extra=permission_meta("platform:secrets"),
    summary="Install or rotate a credential (step-up confirmed, audited, alerted)",
    description=(
        "Seals the value with a fresh DEK and stores it as a NEW VERSION — the previous "
        "version is retired, never overwritten, so which key was live when a call was "
        "billed stays answerable. Requires `X-Confirm-Action: set_secret:<key>`. The "
        "value is never returned, logged or traced. Test it first: "
        "`POST /v1/ops/secrets/{key}/test`."
    ),
)
async def set_secret_route(
    payload: SecretSetIn,
    session: GlobalSession,
    request: Request,
    tasks: BackgroundTasks,
    principal: SecretOperator,
    key: SecretKey,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> SecretOut:
    """One version in, one audit row, one alert, and the fleet re-reads within seconds."""
    require_step_up(x_confirm_action, secret_confirmation(key))
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="secret_actor_unknown",
            title="This session has no admin identity",
            detail="Installing a credential has to be attributable to an operator.",
        )

    record = await set_secret(session, key=key, value=payload.value, actor_id=principal.user_id)
    await write_audit(
        session,
        action="platform.secret_set",
        actor=principal,
        object_type="platform_secrets",
        object_id=key,
        ip=client_request_ip(request),
        # §9: "no value and no fragment beyond last_four".
        summary={
            "config_key": key,
            "version": record.version,
            "last_four": record.last_four,
            "kek_id": record.kek_id,
            "reason": payload.reason,
            "shadowed_by_env": record.shadowed_by_env,
        },
    )
    # §10's RESIDUAL RISK, and the control it rests on. An attacker with an admin session
    # can replace a vendor key with one they control — pointing our engine at their own
    # account — and `/test` makes that easy to do convincingly. Prevention is not
    # available; detection is, and it is not optional: this alert is what makes the
    # residual risk an accepted one rather than an unmonitored one. Fired for every
    # environment, not just production, because a staging deploy that silently rotates a
    # key is the rehearsal nobody would notice either.
    alert(
        "CORE_LOGIC",
        "platform_secret_set",
        detail=(
            f"A platform credential was installed or rotated: {key} "
            f"(version {record.version}). If this was not you, treat it as an incident: "
            "an attacker with an admin session can point this platform at their own "
            "vendor account."
        ),
        config_key=key,
        actor_id=str(principal.user_id),
    )
    tasks.add_task(propagate)
    return _out(record, testable=_testable(key))


class KekOut(BaseModel):
    """The key-management panel's read (§8 panel 4): which KEK is live, and what is
    still wrapped under something else.

    `pending` is the number that decides whether a rotation is FINISHED. While it is
    above zero the retired KEK must stay in the environment, because removing it would
    make those rows permanently unreadable — and that is a decision an operator makes
    from this number, so it is published rather than implied.
    """

    model_config = ConfigDict(extra="forbid")

    #: The fingerprint of the KEK this deployment wraps with (D-96).
    active_kek_id: int
    #: True when PLATFORM_KEK_RETIRED is configured. A rotation needs it; a settled
    #: deployment should not have one.
    has_retired_kek: bool
    #: Secret versions in total.
    versions: int
    #: Versions already wrapped under the ACTIVE key.
    current: int
    #: Versions still wrapped under something else. Zero means the rotation is complete
    #: and the retired key can be removed from the environment.
    pending: int


class RewrapOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    examined: int
    rewrapped: int
    #: Versions no configured KEK opens, named. These are the rows that will be lost if
    #: the retired key is removed, so they are reported rather than counted away.
    unreadable: list[str]
    active_kek_id: int


REWRAP_CONFIRMATION = "rewrap_platform_keks"


@router.get(
    "/kek",
    response_model=KekOut,
    openapi_extra=permission_meta("platform:secrets"),
    summary="Which KEK is live, and how many DEKs are still wrapped under another",
)
async def read_kek(session: GlobalSession, _: SecretOperator) -> KekOut:
    ring = kek_ring()
    row = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE kek_version = :active) "
                "FROM platform_secrets"
            ),
            {"active": ring.active.kek_id},
        )
    ).first()
    versions = int(row[0]) if row else 0
    current = int(row[1]) if row else 0
    return KekOut(
        active_kek_id=ring.active.kek_id,
        has_retired_kek=bool(ring.retired),
        versions=versions,
        current=current,
        pending=versions - current,
    )


@router.post(
    "/kek/rewrap",
    response_model=RewrapOut,
    openapi_extra=permission_meta("platform:secrets"),
    summary="Re-wrap every DEK under the current KEK (step-up confirmed, audited)",
    description=(
        "Runs after a KEK rotation: every stored secret version has its DEK unwrapped "
        "with whichever configured key opens it and re-wrapped under the current one. "
        "The credentials themselves are NEVER decrypted — only the 32-byte DEKs — so "
        "this is safe to run against a live platform. Requires `X-Confirm-Action: "
        "rewrap_platform_keks`. Until `pending` reaches 0, PLATFORM_KEK_RETIRED must "
        "stay set."
    ),
)
async def rewrap_keks(
    session: GlobalSession,
    request: Request,
    principal: SecretOperator,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> RewrapOut:
    """Superadmin-only by virtue of `platform:secrets`, and confirmed like every write here.

    It writes to every row of an append-only ledger, which is the most invasive thing on
    this router even though it changes no credential — so it is confirmed, audited, and
    reports what it could NOT do rather than only what it did.
    """
    require_step_up(x_confirm_action, REWRAP_CONFIRMATION)
    result = await rewrap_all(session)
    await write_audit(
        session,
        action="platform.kek_rewrapped",
        actor=principal,
        object_type="platform_secrets",
        ip=client_request_ip(request),
        summary={
            "examined": result.examined,
            "rewrapped": result.rewrapped,
            "unreadable": list(result.unreadable),
            "kek_id": result.kek_id,
        },
    )
    return RewrapOut(
        examined=result.examined,
        rewrapped=result.rewrapped,
        unreadable=list(result.unreadable),
        active_kek_id=result.kek_id,
    )


__all__ = ["REWRAP_CONFIRMATION", "router", "secret_confirmation"]
