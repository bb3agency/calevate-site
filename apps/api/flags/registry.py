"""WHAT A FEATURE FLAG IS HERE, AND — more importantly — WHAT IT IS NOT.

SURFACES §1 asks for "per-tenant feature flags (config rows, TRD conventions) — enable
beta features or debug modes per client without deploys", and CLAUDE.md fixes the shape:
**"Feature flags via plain config rows, not a flag SaaS."** This module is the list of
flags that exist; `service.py` resolves them and `routes.py` is the operator's surface.

A flag here is: **a per-tenant, reversible, operator-owned switch on OUR OWN product
behaviour, whose OFF position is what every tenant already gets.** That definition is
narrow on purpose, because this repo already carries four mechanisms that look like flags
and are not. A fifth is only justified if it replaces none of them.

WHAT THESE FLAGS DO NOT REPLACE
-------------------------------
1. **`Settings.self_serve_signup_enabled` and its siblings** (`whatsapp_enabled`,
   `payment_provider`, `google_sheets_provider`, `number_provider`). These are PLATFORM
   configuration: one value for the whole deployment, injected from the environment, read
   at boot. R-11's kill switch is the clearest case — its own comment says "closing it
   during an incident is an environment change, not a deploy", and moving it into a
   database row would make closing the front door depend on the database being writable
   and on a console being reachable. They are also read where no tenant exists (bootstrap,
   the public signup intake), which a per-tenant table cannot answer for by construction.
   **Not migrated, and should not be**: a platform switch has no tenant to key on.

2. **The big red switch and the load-shed mode** (`platform_state`, `core/loadshed.py`).
   An INCIDENT CONTROL, not a product toggle: it is global by design ("a per-tenant copy
   of it would be N copies of one fact"), it is on `ALWAYS_ALLOWED_PREFIXES` so an
   operator cannot lock themselves out of it, it carries step-up confirmation bound to the
   transition, and it has a three-layer cache tuned so a halt is never more than a
   dispatch tick stale. Every one of those properties is a cost these flags deliberately
   do not pay, because a beta toggle is not worth them. **Not migrated, and should not
   be.**

3. **`PROVIDER_CREATES_ORDERS`, `LEAD_RETRIEVAL_IMPLEMENTED`, `PROVISIONING_IMPLEMENTED`.**
   These are BUILD-TIME CONSTANTS marking vendor work that does not exist — a `False`
   there is a statement that no adapter has been written, verified against the vendor and
   tested. A row in a table cannot make an unwritten adapter exist, so a flag flipped on
   would not enable a feature, it would enable a lie: the refusal these constants produce
   is the honest answer, and the thing that closes them is a code change plus a vendor
   verification (OPERATIONS §2), not a click. **Not migrated, and MUST not be** — this is
   the one of the four where migrating would actively cause an incident.

4. **Plan tiers and `plans` rows** (`organizations.plan_tier`, entitlements, caps).
   COMMERCIAL ENTITLEMENT: what a client has PAID for. It is dated (`effective_from` /
   `effective_to`), it is what the invoice is derived from, and changing it is a
   contractual act audited as `admin.record_commercial_terms`. A flag is what we choose to
   switch on for a client; an entitlement is what they bought. Collapsing the two would
   mean a beta toggle could change a bill. **Not migrated, and should not be.**

RECOMMENDATION, NOT A MIGRATION: none of the four should move onto this. The nearest
candidate is a fifth thing that does not exist yet — a per-tenant DEBUG mode (verbose
in-call tool logging, timing panels) — which is exactly what §1 asks for and what
`call_timing_breakdown` below is reserved for.

AND ONE HARD LIMIT: **a flag must never gate a compliance control.**
`campaigns.service.launch_blockers`, `compliance.service.check_dispatch`, DNC, the
disclosure line, calling hours, the first-campaign hold and the KYC gates are not
flaggable. Hard rule 5 forbids a bypass "for testing", and a per-tenant switch that can
turn a TRAI/DPDP control off for one client is that bypass with better manners. A control
that genuinely needs to vary per tenant varies through the compliance gate itself, where
it is a named rule with a client-facing reason and an audit trail — not through a boolean
whose whole design goal is to be cheap to flip.

THE REGISTRY IS THE PLATFORM DEFAULT, AND IT LIVES IN CODE
----------------------------------------------------------
Resolution is **platform default → per-tenant override**, and the platform default is the
`default` field below rather than a second table. Three reasons, and the third is the one
that decided it:

* a flag with no declaration cannot be read, so `flag_enabled(session, "typo")` fails
  `mypy` rather than returning `False` forever (the `FlagName` literal below is checked
  against `FLAGS` at import, so the two cannot drift);
* the default travels with the code that reads it and is reviewed with it, so a rollout
  is a diff a person approved rather than a row somebody set at 2am;
* **changing the platform default IS a release, and saying so is honest.** A default flip
  changes behaviour for every tenant at once, which is the blast radius of a deploy, so it
  should cost a deploy. What SURFACES §1 asks to be free of a deploy is the PER-CLIENT
  half — "enable beta features or debug modes per client" — and that half is a row.

REJECTED: a `platform_feature_flags` table so ops can flip a default for everyone. It
buys a global switch we do not need (a beta is enabled per client, that is the point),
and it costs a second write path, a second audit story, and a cache that must be
consistent with the per-tenant one. If it is ever wanted, it is a decision-log entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

# Every declared flag, as a type. A `Literal` rather than a plain `str` so a caller that
# names a flag which does not exist is a `mypy` failure at the call site, not a silent
# `False` at runtime — the same "declared and enforced cannot drift" discipline
# `core/rbac.py` applies to permissions.
FlagName = Literal["call_timing_breakdown"]

# The shape a stored flag name must have. Bounded and lower-snake because it is
# interpolated into an audit action and a URL path segment, and because the DB CHECK in
# migration 3a91c7e04d58 spells the same rule — an operator can only ever store a name
# this pattern accepts, whether or not it is DECLARED (see `service.clear_flag`).
FLAG_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]{2,63}$"


@dataclass(frozen=True, slots=True)
class FlagSpec:
    """One declared flag: what it does, what it does by default, and who reads it."""

    #: What flipping it ON changes, in the operator's words. Rendered on the console.
    description: str
    #: What every tenant gets without a row. See the module docstring on why this is
    #: code rather than a table.
    default: bool
    #: The module that CONSUMES this flag, or None while nothing does.
    #:
    #: It is a field rather than a comment because the console renders it: an operator
    #: must never flip a switch believing it does something, when the code that would
    #: read it has not been written. A declared-but-unread flag is a legitimate state —
    #: it is how a flag is landed before the feature it gates — but it is not a state
    #: anybody should have to discover from a grep.
    consumed_by: str | None
    #: What has to happen before `consumed_by` can be filled in. REQUIRED exactly when
    #: `consumed_by` is None, and forbidden otherwise, enforced by
    #: `assert_flag_registry_wellformed`.
    #:
    #: CLAUDE.md: "A deferral is a decision-log entry naming what closes it, or it is not
    #: a deferral." `consumed_by: None` was that deferral without the naming half — a
    #: switch an operator can flip, that does nothing, with no statement anywhere of what
    #: would make it do something. The rule is not "flags must be consumed": landing the
    #: mechanism before the feature is deliberate and stays legal. The rule is that the
    #: unconsumed state has to say what ends it, which is the difference between a plan
    #: and a leftover.
    blocked_by: str | None = None


# KEYED BY `str`, NOT BY `FlagName`, and the asymmetry is the point. Every name that
# reaches this dict at runtime came from outside the type system — a URL path segment, a
# row written by an older release — so a `FlagName`-keyed dict would force a
# `# type: ignore` at every lookup, and a silenced error is how a real one eventually
# hides. `FlagName` guards the CALL SITES instead (`service.flag_enabled` takes it), which
# is where a typo is a bug rather than a legitimate unknown, and
# `assert_flag_registry_wellformed` proves at boot that the two lists are the same list.
FLAGS: Final[dict[str, FlagSpec]] = {
    "call_timing_breakdown": FlagSpec(
        description=(
            "Show the per-call timing breakdown (STT, LLM and TTS segments, and the "
            "engine's own turn latency) on this client's call detail screen, once those "
            "numbers exist. A DEBUG VIEW: it would change nothing about how a call is "
            "placed, answered, metered or billed, and is invisible to the client's own "
            "callers. Leave it off — there is nothing behind it yet."
        ),
        default=False,
        # NOTHING READS THIS, and the console says so beside the switch. It is declared
        # here so the mechanism ships with a real subject rather than an empty screen;
        # wiring the view is its own change, because introducing a mechanism and rewiring
        # a feature in one diff is unreviewable.
        consumed_by=None,
        # This description USED TO SAY the view "renders numbers we already record on the
        # call row", and that stopped being true when `calls.latency` — the column that
        # held {stt_ms, llm_ttft_ms, tts_ttfa_ms, turn_p50, turn_p95} and was written by
        # nothing — was dropped in migration f1a7c39d5be2. So the flag gated a screen
        # that had no data, over a sentence promising data that did not exist.
        blocked_by=(
            "the numbers themselves. The in-call audio path runs inside the rented engine "
            "(D-33), so nothing we trace is inside it, and the vendor's own per-component "
            "timings are neither the same measurements nor validated against a stopwatch "
            "— which is OPERATIONS §2 pilot gate 4, and needs a Bolna account placing a "
            "real call. `calls.latency` was dropped in migration f1a7c39d5be2 for exactly "
            "this reason; the gate is what re-opens both."
        ),
    ),
}


def spec_for(name: str) -> FlagSpec | None:
    """The spec for a name that came from OUTSIDE the type system, or None.

    A named function rather than `FLAGS.get(...)` at four call sites, because "the
    registry does not declare this" is a decision each caller answers differently and the
    question should read the same everywhere it is asked.

    None means "this build does not declare that flag" — a legitimate answer for a row
    written by an older release, not an error. Callers decide what to do about it:
    `resolve_flags` ignores it, `clear_flag` removes it, `routes.put_feature_flag`
    refuses to SET it.
    """
    return FLAGS.get(name)


class FlagRegistryError(RuntimeError):
    """Boot-time failure: the flag registry contradicts itself."""


def assert_flag_registry_wellformed() -> None:
    """Called from `main.py` beside the RBAC assertion — same reason, same moment.

    A registry that disagrees with its own type is worse than no registry: `FLAGS` drives
    what the console offers and what the resolver returns, `FlagName` drives what `mypy`
    accepts, and a name in one and not the other is a flag that is either unreachable
    from code or unsettable from the console. Asserted at startup rather than discovered
    at first use (BACKEND-PATTERNS §7).
    """
    import re

    declared = set(get_args(FlagName))
    registered = set(FLAGS)
    if declared != registered:
        raise FlagRegistryError(
            "FlagName and FLAGS disagree — "
            f"only in FlagName: {sorted(declared - registered)}; "
            f"only in FLAGS: {sorted(registered - declared)}. "
            "Every declared flag needs both a Literal member and a FlagSpec."
        )
    pattern = re.compile(FLAG_NAME_PATTERN)
    for name, spec in FLAGS.items():
        if not pattern.match(name):
            raise FlagRegistryError(
                f"flag {name!r} does not match {FLAG_NAME_PATTERN} — the same rule the "
                "database CHECK enforces, so this name could never be stored."
            )
        if len(spec.description.strip()) < 20:
            raise FlagRegistryError(
                f"flag {name!r} has no usable description. The console renders it beside "
                "the switch; an operator deciding whether to flip it has nothing else."
            )
        blocked = (spec.blocked_by or "").strip()
        if spec.consumed_by is None and len(blocked) < 20:
            raise FlagRegistryError(
                f"flag {name!r} is declared, settable and read by nothing, and does not "
                "say what would change that. Give it a `blocked_by` naming what closes "
                "it — a vendor gate, a measurement, a decision — or delete the flag. "
                "CLAUDE.md: a deferral is a statement of what closes it, or it is not a "
                "deferral."
            )
        if spec.consumed_by is not None and blocked:
            raise FlagRegistryError(
                f"flag {name!r} names both a consumer ({spec.consumed_by}) and a blocker. "
                "The blocker is what stands in the way of a consumer; once one exists the "
                "sentence is stale, and a stale blocker is how an operator concludes a "
                "live switch does nothing."
            )


__all__ = [
    "FLAGS",
    "FLAG_NAME_PATTERN",
    "FlagName",
    "FlagRegistryError",
    "FlagSpec",
    "assert_flag_registry_wellformed",
    "spec_for",
]
