"""RBAC as a policy registry VALIDATED AT BOOT (BACKEND-PATTERNS §7).

The pattern that matters: the endpoint→permission map is asserted at startup, not
discovered at first request. A new route that forgets its permission fails the boot
assertion in CI, not silently in production with an open door.

Role tables (DATA-MODEL §2):
- client realm `owner` — everything in their own tenant, including raw transcripts
  (role check + audit_log write, hard rule 5) and billing.
- client realm `staff`  — no billing, no org settings, no raw transcripts. ONE exception
  since 2 Sep 2026, and it is deliberately narrow: `wallet:read`, the prepaid balance and
  its ledger, because the thing that stops a staff member dialling is an empty wallet and
  a refusal whose explanation only the owner can see is a refusal with no words in it.
  Buying credit remains the owner's (`org:manage`).
- admin realm `operator`   — runs onboarding and support across tenants, and since the
  founder's correction to D-457 that includes the per-tenant reads support actually
  needs: raw transcripts and recordings (role check + audit row, hard rule 5) and the
  authority to dispatch a campaign.
- admin realm `superadmin` — the four PLATFORM authorities, each of which additionally
  needs step-up confirmation. There is one of these accounts.

═══ THE ADMIN REALM IS TWO TIERS, AND THE BOUNDARY IS FOUR PERMISSIONS LONG ═══

`superadmin` holds EVERY permission, and it holds them by DERIVATION (`SUPERADMIN_
PERMISSIONS = KNOWN_PERMISSIONS`) rather than by a hand-kept list that used to be
maintained beside `operator`'s. That is the product rule — the person who owns the
platform can do everything on it — expressed once, in the one place it can never drift
from the `Permission` type.

THE OTHER TIER IS THE FOUNDER'S SENTENCE, NOT A SENIORITY LADDER: "the other normal
admins can do literally everything that a super admin can except ops config and other
things that are vital in that level". So the difference between the two tiers is
`SUPERADMIN_ONLY_PERMISSIONS` — four names, listed and argued below — and NOTHING ELSE.
A permission that is not one of those four and is withheld from `operator` is a bug in
this file, not a policy; `tests/admin_operators_test.py` states that as an equation over
these constants rather than over a hand-typed list, so a permission added to the
`Permission` type tomorrow cannot land in the wrong tier unnoticed.

WHAT IS STILL DENY-BY-DEFAULT, AND WHY THE EQUATION DOES NOT WEAKEN IT. `operator`'s set
stays HAND-KEPT rather than being computed as `SUPERADMIN_PERMISSIONS -
SUPERADMIN_ONLY_PERMISSIONS`. Deriving it would read tidier and would invert the default:
a new permission would reach every admin the moment it joined the type, silently. Written
out, a new permission reaches `superadmin` by construction and a normal admin only by an
explicit line — and the equation in the test then FAILS until somebody decides which side
it belongs on. Deny is the default; the test is what stops the default from being
accidental. So a route can never be "neither super-admin-only nor normal-admin-allowed":

  * a permission no role holds fails `assert_policy_registry_complete` (a lock with no
    key — the route would 403 the entire population);
  * a permission `operator` does not hold is superadmin-only, which is the safe end;
  * an admin-path route that forgot `realm="admin"` fails the same assertion, because
    the realm — not the permission — is what keeps a client `owner` out of a surface
    whose permission their role also happens to hold (`org:manage`, `agents:write`).

The old shape wrote `superadmin`'s set out longhand, which meant adding a permission and
forgetting that list produced a superadmin who could not use their own console, and
adding it to `operator` and forgetting `superadmin` produced the reverse. Neither is
possible now: the only editorial decision left when a permission is added is whether the
NORMAL admin tier gets it, and that decision is one line in one dict.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Final, Literal, cast, get_args

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

Permission = Literal[
    "agents:read",
    "agents:write",
    "calls:read",
    "calls:read_raw",
    "leads:read",
    "leads:write",
    "leads:dispatch",
    "billing:read",
    # SEEING THE PREPAID WALLET — the balance, its ledger, the runway and the top-up
    # attempts behind them (`billing/wallet_routes.py`), and nothing else.
    #
    # A NEW PERMISSION RATHER THAN A WIDENING OF `billing:read`, and the precedent is
    # `copilot:use` three lines down: the founder decided (2 Sep 2026) that everyone on a
    # client's team must be able to see the balance and the ledger — "so an operator
    # understands why dialling stopped" — while only the owner may BUY. `staff` does not
    # hold `billing:read`, and granting it would have carried the spend breakdown, the
    # spend caps and the monthly tax-shaped statement (`billing/routes.py::my_invoice`)
    # with it: SEC-COMP §5 scopes those to the owner, and the founder decided nothing
    # about them. Largest possible widening for the narrowest possible ask, refused for
    # the same reason it was refused for the assistant.
    #
    # IT IS NOT IN `MUTATING_PERMISSIONS`, and that is not an oversight. It reads; the
    # purchase is `org:manage` on `POST /v1/billing/topups/intent`, which IS mutating. A
    # view-as operator sees a client's wallet on the support call and still cannot spend
    # from it — since D-587 that second half is `VIEW_AS_WITHHELD_ACTS["billing.topup"]`
    # rather than a consequence of this membership, because `org:manage` itself is now
    # writable under view-as. That split is the whole permission model of this screen.
    "wallet:read",
    "org:read",
    "org:manage",
    "kb:write",
    # OPENING THE IN-APP ASSISTANT — `POST /v1/copilot/ask` and `POST /v1/copilot/confirm`,
    # and nothing else.
    #
    # A NEW PERMISSION RATHER THAN A REUSE OF `org:manage`, which is what both routes
    # declared until the founder's decision that staff must be able to use the assistant.
    # `org:manage` was never chosen for the copilot's sake — it was chosen because the
    # route SPENDS the account's AI allowance and therefore needed a member of
    # `MUTATING_PERMISSIONS` (`copilot/routes.py`, `crm/routes.py::assist_call`), and
    # `org:manage` was the mutating permission a client role happened to hold. Granting
    # staff `org:manage` to unlock a chat panel would have carried billing, members and
    # every organization setting with it: the largest possible widening for the narrowest
    # possible ask.
    #
    # **IT IS IN `MUTATING_PERMISSIONS`, AND THAT IS NOT AN ACCIDENT OF COPYING.** The
    # property `org:manage` was carrying on these two routes is the one that must survive
    # the swap: a D-22 read-only view-as session must not be able to spend a client's AI
    # allowance from a client's own screen. Asking the assistant is metered
    # (`require_ai_assist` → `usage_events`), so it IS a mutation of the account's balance
    # however read-only the answer looks, and `tests/authz_audit_test.py::
    # test_every_mutating_route_is_gated_by_a_mutating_permission` states that as a rule
    # over the whole route table rather than as a habit.
    #
    # IT UNLOCKS THE DOOR AND NEVER WHAT IS BEHIND IT. `write_tools.confirm` re-checks the
    # permission the equivalent BUTTON declares — `leads:write` for a lead's status,
    # `kb:write` for a knowledge entry — so a staff member may ASK the assistant anything
    # and can still only COMPLETE the changes their own role (plus, for knowledge, their
    # owner's switch) already admits.
    "copilot:use",
    # OPENING THE ADMIN-REALM ASSISTANT — `POST /v1/admin/copilot/ask` and
    # `POST /v1/admin/copilot/confirm`, and nothing else (D-499).
    #
    # A SEPARATE NAME FROM `copilot:use`, AND THE SPLIT IS LOAD-BEARING RATHER THAN
    # TIDY. The two copilots have different tools, different memories, different knowledge
    # and — the half that decides this — DIFFERENT PAYERS: the client assistant spends the
    # account's own AI allowance, the admin assistant spends ours (`billing/platform_ai.py`,
    # `platform_ai_usage`). One permission over both would have meant one D-22 answer over
    # both, and the two need opposite ones (see `IMPERSONATION_PERMITTED_MUTATIONS`).
    #
    # HELD BY ADMIN ROLES ONLY. Every route declaring it is `realm="admin"`, so a client
    # `owner` could not reach one anyway (`ADMIN_REALM_PREFIXES` is what keeps them out,
    # never the permission) — but a client role that HELD it would read, in the schema and
    # in the generated client, as a client-facing capability, which it is not.
    "copilot:admin",
    "admin:tenants",
    "admin:impersonate",
    # THE OPERATOR ALLOWLIST ITSELF — creating an operator account, changing its role,
    # revoking it, and re-issuing its setup link (`admin/operator_routes.py`).
    #
    # SUPERADMIN-ONLY, AND THAT IS THE WHOLE SECURITY PROPERTY OF THE TWO TIERS. If a
    # normal admin could reach this surface they could give themselves `platform:secrets`
    # in one request, and every other line of this file would be decoration: the tiers
    # would differ only in how many clicks the escalation took. So the permission that
    # edits the role table is the one permission that must never be in
    # `ROLE_PERMISSIONS["operator"]`, and `tests/admin_operators_test.py` drives an
    # `operator` at all five routes to prove it.
    #
    # A SEPARATE PERMISSION RATHER THAN A REUSE OF `admin:tenants`, on the same argument
    # `platform:config` makes above: `admin:tenants` is "act on one client" and is held
    # by everybody who onboards. This is "decide who may act on the platform at all",
    # which is the authority that CONTAINS every other authority here.
    "admin:operators",
    "ops:manage",
    # Reading and changing PLATFORM configuration — the engine selection, the calling
    # windows, the rate limits (PLATFORM-CONFIG §7).
    #
    # A NEW PERMISSION RATHER THAN A REUSE OF `admin:tenants`, and the spec argues why:
    # the blast radii are not comparable. `admin:tenants` is "act on one client";
    # this is "change what every client's platform does at the same instant" — switch
    # the voice engine, move a calling window outside TRAI's permitted hours, raise a
    # rate limit. An operator who onboards clients does not need it, and the whole
    # point of a separate name is that it can be held by fewer people.
    #
    # It is deliberately NOT `ops:manage` either, even though both are superadmin-only
    # today and both live under `/v1/ops`. `ops:manage` is the INCIDENT surface — the
    # big red switch, the DLQ replay, the audit-chain check — and its holders are
    # whoever is on call. Config is a change-management surface. Merging them would mean
    # the next person given the pager could also switch the engine, which is exactly the
    # separation §7 asks for and the one phase 4's `platform:secrets` deepens.
    "platform:config",
    # Installing and rotating VENDOR CREDENTIALS (PLATFORM-CONFIG §7).
    #
    # SEPARATE FROM `platform:config`, and the separation is the mitigation §10 rests on
    # rather than tidiness. The trade this console makes is stated plainly there: today,
    # stealing every vendor credential requires VPS access; after this, one compromised
    # admin session is enough. What keeps that acceptable is that the permission is held
    # by fewer people than any other on this list, that no route returns plaintext — so
    # a session gives WRITE access, never READ access — and that every write is audited
    # into the hash-chained ledger with an alert on `platform.secret_set` in production.
    #
    # A holder can BREAK the platform or point it at their own vendor account; they
    # cannot quietly exfiltrate what is already installed. That asymmetry is deliberate
    # and is why this is not merged into `platform:config`, whose blast radius stops at
    # "the platform misbehaves visibly".
    "platform:secrets",
]

#: Every string the `Permission` Literal admits. Read off the type rather than restated,
#: so widening the type cannot leave the boot assertion — or `superadmin` — behind.
KNOWN_PERMISSIONS: frozenset[str] = frozenset(get_args(Permission))

#: THE SUPER ADMIN HOLDS EVERYTHING, LITERALLY EVERYTHING — the founder's own words for
#: the tier that owns the platform, and the module docstring argues why it is derived
#: from the type rather than written out beside `operator`'s set.
#:
#: IT IS `KNOWN_PERMISSIONS`, cast — the same object, not a second computation of it, so
#: "the super admin holds every permission" is true by identity rather than by two
#: expressions that happen to agree. The cast is needed only because `get_args` is typed
#: `tuple[Any, ...]`; the alternative is restating every string in the `Permission` type,
#: which is precisely the hand-kept list this replaces.
SUPERADMIN_PERMISSIONS: frozenset[Permission] = cast("frozenset[Permission]", KNOWN_PERMISSIONS)

#: THE ENTIRE DIFFERENCE BETWEEN THE TWO ADMIN TIERS, named once so it can be asserted.
#:
#: The founder was asked to draw the line and drew it here: "only super admin has access
#: to ops config panel ... the other normal admins can do literally everything that a
#: super admin can except ops config and other things that are vital in that level."
#: Four permissions, and each is on this list because losing it costs the PLATFORM rather
#: than one client:
#:
#:   `platform:secrets` + `platform:config` — the ops config panel, where every vendor
#:     credential and every platform-wide setting is installed. PLATFORM-CONFIG §10's
#:     risk acceptance rests verbatim on `platform:secrets` being "held by fewer people
#:     than any other on this list"; §7 argues `platform:config`'s own blast radius
#:     ("change what every client's platform does at the same instant").
#:   `admin:operators` — the role table itself. It is the load-bearing one: a normal
#:     admin who could edit it could grant themselves the other three in one request, and
#:     every other line here would be decoration.
#:   `ops:manage` — the global kill switches (big red switch, load-shed, DLQ replay,
#:     audit-chain verify, `/healthz/ready` detail). Two routes ALSO read it as the
#:     superadmin marker rather than declaring it — tenant erasure
#:     (`compliance/tenant_erasure_routes.py`) and raising or removing a client's spend
#:     ceiling (`admin/routes.py::record_commercial_terms`) — so those two acts ride this
#:     entry and are superadmin-only as a consequence of it.
#:
#: IT IS NOT ENFORCEMENT AND MUST NEVER BECOME IT. `role_has` is the enforcement and
#: reads `ROLE_PERMISSIONS`; this constant is the STATEMENT of the boundary that the
#: test compares that dict against. Two dicts either of which could grant a permission
#: would be exactly the drift `SUPERADMIN_PERMISSIONS` was derived to remove.
SUPERADMIN_ONLY_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        "admin:operators",
        "ops:manage",
        "platform:config",
        "platform:secrets",
    }
)

#: The two roles `ck_admin_users_role_enum` admits, in one place because three modules
#: name them — this one, `tenancy/models` (which renders the CHECK constraint) and
#: `authn/bootstrap` (which validates `--role`) — and a fourth spelling is how a role
#: table and the constraint built from it come to disagree about what a role is called.
SUPERADMIN_ROLE: Final = "superadmin"
NORMAL_ADMIN_ROLE: Final = "operator"

#: The pair, in the order `ck_admin_users_role_enum` spells it. `tenancy/models` builds
#: that CHECK constraint from this tuple and `authn/bootstrap` validates its `--role`
#: argument against it, so the database's vocabulary and the role table's are one string
#: each. The ORDER is load-bearing only in that the constraint's stored text is rendered
#: from it — reversing it would make the model's constraint and the migrated one differ
#: textually while meaning the same thing, which is a diff no reviewer should have to read.
ADMIN_ROLES: Final[tuple[str, str]] = (SUPERADMIN_ROLE, NORMAL_ADMIN_ROLE)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    # `copilot:use` is here because the founder decided staff must be able to use the
    # assistant, and it is the ONLY thing this change added. It is deliberately NOT
    # accompanied by `kb:write`: what a staff member may CURATE is not a role fact at all
    # but a per-account switch their owner controls
    # (`organizations.staff_may_curate_knowledge`, `kb/curation.py`), so this dict stays
    # the answer to "what does every staff member on the platform hold" and the column
    # stays the answer to "what did THIS owner additionally allow".
    "staff": frozenset(
        {
            "agents:read",
            # EDITING AN AGENT'S SETTINGS — its voice and how long one call may run (D-587),
            # and whatever else joins that class. The founder's decision: a client's own team
            # runs its own phone line, and the person who notices a call stuck at nine
            # minutes is as likely to be staff as the owner.
            #
            # A GRANT OF AN EXISTING PERMISSION, NOT A NEW ONE, and not a widening of
            # `org:manage` — which is the shape this could have taken and the wrong one. Both
            # settings already had a permission that names exactly this authority;
            # `org:manage` names billing, members and every account setting, and granting it
            # to staff to unlock a voice picker would be the largest possible widening for
            # the narrowest possible ask — the refusal `copilot:use` and `wallet:read` are
            # both here for.
            #
            # IT OPENS NO ADMIN SURFACE. Every OTHER route declaring `agents:write` — publish,
            # apply, undo, the prompt writer, the script experiments, the onboarding wizard —
            # is `realm="admin"`, and the realm, never the permission, is what keeps a client
            # out of the console (this module's docstring says so, naming `agents:write` as
            # the example). `tests/agent_settings_live_edit_test.py` walks the live route
            # table and asserts that, so a future client-realm route declaring it has to be
            # a deliberate act rather than an inherited one.
            "agents:write",
            "calls:read",
            "copilot:use",
            "leads:read",
            "leads:write",
            "org:read",
            # SEEING THE WALLET, and only the wallet. The founder's 2 Sep 2026 decision:
            # everyone on the team sees the balance and the ledger so that "outgoing calls
            # stopped" has its explanation on the same screen as the thing that stopped
            # them; only the owner may buy. `billing:read` stays absent — see the comment
            # on `wallet:read` in the `Permission` type for why the narrow grant was
            # chosen over widening that one.
            "wallet:read",
        }
    ),
    "owner": frozenset(
        {
            "agents:read",
            # D-587 — see the note on `staff` above, which carries the whole argument. The
            # owner holds it for the obvious reason and staff for the decided one.
            "agents:write",
            "calls:read",
            "calls:read_raw",
            "copilot:use",
            "leads:read",
            "leads:write",
            "leads:dispatch",
            "billing:read",
            "wallet:read",
            "org:read",
            "org:manage",
            "kb:write",
        }
    ),
    # THE NORMAL ADMIN TIER, and the ONLY hand-kept set in this dict. Everything a new
    # permission does NOT appear in here is superadmin-only, which is the deliberate
    # default (module docstring). Adding a line here is the whole act of widening the
    # normal tier, and it is reviewable as one line.
    #
    # WHAT IS DELIBERATELY ABSENT IS EXACTLY `SUPERADMIN_ONLY_PERMISSIONS` AND NOTHING
    # ELSE — asserted as an equation in `tests/admin_operators_test.py`, so this comment
    # cannot come to describe a set the dict no longer has.
    #
    # `calls:read_raw` AND `leads:dispatch` LIVE HERE, AND D-457 HAD THEM ON THE OTHER
    # SIDE. The founder corrected that: "the other normal admins can do literally
    # everything that a super admin can except ops config and other things that are vital
    # in that level", and neither of these is vital at that level — both are PER-TENANT
    # support work with their own controls already in front of them:
    #
    #   `calls:read_raw` — every route that declares it is client-realm, so a normal
    #     admin reaches it only through a D-22 view-as session, which needs an
    #     impersonation grant minted behind a second factor (D-210) and writes an
    #     `audit_log` row of its own on every raw read (hard rule 5). This IS a real
    #     widening and is worth naming rather than burying: an operator in a view-as
    #     session can now read an unredacted transcript, play a recording, take the
    #     unmasked CSV export, produce a data-subject export and open a delivered webhook
    #     payload — six routes, each audited, none of them reachable before. The tests
    #     that pinned the old boundary were rewritten to pin the new one rather than
    #     deleted (`tests/impersonation_audit_test.py`), so the day this stops being
    #     audited, something goes red.
    #   `leads:dispatch` — it is in `MUTATING_PERMISSIONS`, so D-22 refuses it to an
    #     impersonating admin, and `current_any` resolves the admin realm ONLY when the
    #     impersonation header is present. Every route declaring it is client-realm.
    #     So this grant opens no request that can be sent today; what it does is put the
    #     tier boundary where the founder drew it, so a future ADMIN-realm dispatch
    #     surface does not have to re-litigate it.
    NORMAL_ADMIN_ROLE: frozenset(
        {
            "agents:read",
            "agents:write",
            "calls:read",
            "calls:read_raw",
            # HELD, AND STILL UNREACHABLE, AND BOTH ARE STILL CORRECT — but the reason
            # changed with D-499 and this comment used to give the old one. The tier
            # boundary is exactly `SUPERADMIN_ONLY_PERMISSIONS` and `copilot:use` is not in
            # it, so withholding it here would be a bug in this file by the equation the
            # docstring states. It opens no request an admin can send: the admin realm now
            # HAS a copilot, but it is `copilot:admin` on `/v1/admin/copilot/ask`, and
            # reaching the CLIENT route means impersonating — which `MUTATING_PERMISSIONS`
            # refuses for this permission and deliberately does not exempt, because a
            # client's own AI allowance is what that route spends.
            "copilot:use",
            # THE ADMIN ASSISTANT, and unlike `copilot:use` above this one is REACHABLE
            # (D-499): `/v1/admin/copilot/ask` is an admin-realm route whose payer is the
            # platform. It is not superadmin-only by the equation the module docstring
            # states — asking an assistant about platform state is not one of the four
            # vital authorities — and an operator who cannot use the console's own
            # assistant is the tier boundary drawn in the wrong place.
            "copilot:admin",
            "leads:read",
            "leads:write",
            "leads:dispatch",
            "billing:read",
            "wallet:read",
            "org:read",
            "org:manage",
            "kb:write",
            "admin:tenants",
            "admin:impersonate",
        }
    ),
    SUPERADMIN_ROLE: SUPERADMIN_PERMISSIONS,
}

# Permissions that mutate.
#
# ⚠ **THIS SET IS NO LONGER "WHAT A VIEW-AS SESSION IS REFUSED" (D-587, supersedes D-22).**
# It used to be both facts at once — "this permission writes" and "an impersonating admin
# may not have it" — and the second half moved out to `VIEW_AS_MUTATIONS` below, which
# classifies every member of this set individually. Membership here still means exactly one
# thing: the permission WRITES, so a GET may never be gated on it (a read hidden from a
# support session is the bug `tests/impersonation_reads_test.py` exists for) and
# `guard_agent_write` runs before it.
MUTATING_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        "agents:write",
        "leads:write",
        "leads:dispatch",
        "org:manage",
        "kb:write",
        # ASKING THE ASSISTANT SPENDS THE ACCOUNT'S AI ALLOWANCE, so it is a mutation of
        # the balance however read-only the answer looks. Listed here for exactly the
        # property `org:manage` was carrying on those two routes before `copilot:use`
        # replaced it: an operator must not be able to burn a client's included allowance
        # from the client's own screen. Dropping the route from a mutating permission to a
        # non-mutating one would have removed that refusal silently — the route would still
        # have looked guarded, and the only visible symptom would have been a client's bill.
        # That refusal now lives in `VIEW_AS_MUTATIONS`, where it is a sentence rather than
        # an inference from this membership.
        "copilot:use",
        # ASKING THE ADMIN ASSISTANT SPENDS OUR OWN AI CREDENTIAL — `platform_ai_usage` is
        # an append-only money row and the platform brake moves — so it is a mutation for
        # the same reason `copilot:use` is, and the sweep over the route table
        # (`tests/authz_audit_test.py`) states that rule rather than trusting a habit.
        "copilot:admin",
        "ops:manage",
        "admin:tenants",
        # Creating, promoting, demoting and revoking an operator account.
        "admin:operators",
        "platform:config",
        "platform:secrets",
    }
)


# ══════════════════════════════════════════════════════════════════════════════════════
# WHAT A "VIEW AS CLIENT" SESSION MAY WRITE — THE REGISTRY, NOT A MEMORY (D-587).
#
# D-22 made impersonation READ-ONLY and gave one reason: "no dual attribution" — an audit
# trail that could not say whether the client or an operator wearing their face had acted.
# D-587 reverses it because that reason was answered rather than accepted: every audited
# write now carries the operator's `admin_users.id` AS THE ACTOR, the tenant it landed in,
# and the `jti` of the view-as grant that authorised it (`compliance/audit.py::write_audit`,
# `audit_log.via_grant_id`), which joins the write to the `admin.impersonation_started` row
# naming who entered and when. The attribution is now BETTER than an admin-realm write's,
# not worse: an admin-realm row names the operator; these name the operator, the client and
# the session. What D-22 actually bought — an unambiguous ledger — is what this preserves;
# what it cost was an operator who could see a client's broken screen and not fix it.
#
# THIS MAPPING IS THE WHOLE ANSWER TO "MAY A VIEW-AS SESSION DO X". One entry per member of
# `MUTATING_PERMISSIONS`; the value is `None` when a view-as session may exercise it and a
# SENTENCE — the ground for withholding, which is never "caution" — when it may not.
#
# HOW A FUTURE ROUTE KNOWS WHICH IT IS: it does not have to. A permission absent from this
# mapping is WITHHELD by `withheld_from_view_as` (fail closed), and
# `tests/authz_audit_test.py::test_every_mutating_permission_is_classified_for_view_as`
# refuses a build where a mutating permission has no entry. So the choice is made once, by
# name, with its reason beside it — the shape hard rule 4's table list already uses.
#
# THE TWO GROUNDS FOR WITHHOLDING, and neither of them is D-22's:
#
#   1. **IT IS NOT THIS SESSION'S ACCOUNT TO SPEND OR TO GOVERN.** `copilot:use` moves the
#      CLIENT's balance; the platform permissions move every client at once and belong to
#      the operator's own console, which is where they are already reachable as themselves.
#   2. **SOMEBODY'S PERSONAL ACT CANNOT BE PERFORMED BY A PROXY.** Accepting an agreement,
#      consenting to messages, attesting to a compliance statement: these are not settings,
#      they are acts by a named person. Those are refused at the WRITE SITE rather than by
#      permission (the permission also covers ordinary settings) — see
#      `core/context.Principal.client_user_id`, which is the one way a route obtains the
#      `users.id` of the person acting and answers `None` for an operator.
VIEW_AS_MUTATIONS: Mapping[Permission, str | None] = MappingProxyType(
    {
        # ─────────── writable: the client's own account, changed by a named operator ────
        # The support job this exists for: an agent that is answering wrongly, a lead stuck
        # in the wrong state, a knowledge base with a stale price, an opening notice the
        # client asked to have switched off while on the phone to us.
        "agents:write": None,
        "leads:write": None,
        "leads:dispatch": None,
        "org:manage": None,
        "kb:write": None,
        # The operator's OWN assistant, which spends `platform_ai_usage` — ours — on every
        # path (`billing/platform_ai.py`; the founder: *"You never charge a client for your
        # own support work"*). Permitted since D-499, for a reason that survives D-587
        # unchanged: there is no client balance for it to move.
        "copilot:admin": None,
        # ─────────── withheld, each for a ground that is not "caution" ──────────────────
        "copilot:use": (
            "Asking this account's assistant spends the account's own AI allowance. Ask "
            "from the operator console instead — that spends ours, which is whose it is."
        ),
        "ops:manage": (
            "The incident surface is platform-wide and is not inside any client's account. "
            "Use it from the operator console as yourself."
        ),
        "admin:tenants": (
            "Acting on a client's record is an operator-console act and is already "
            "reachable there as yourself; doing it through the client's own screens would "
            "record a tenant-scoped act for a platform-scoped one."
        ),
        "admin:operators": (
            "Handing somebody an admin account is not something any client's account "
            "contains. Do it from the operator console."
        ),
        "platform:config": (
            "Platform configuration changes what EVERY client's platform does at the same "
            "instant, so it is not a change to the account you are viewing."
        ),
        "platform:secrets": (
            "Installing a vendor credential is platform-wide and is deliberately the "
            "narrowest authority here. Do it from the operator console."
        ),
    }
)

#: Mutating permissions a view-as session MAY exercise. Derived, so the two views of
#: `VIEW_AS_MUTATIONS` cannot disagree. Kept under its pre-D-587 name because every caller
#: and test already asks for it by that name and its meaning is unchanged — "the mutations
#: impersonation is permitted" — only its membership grew.
IMPERSONATION_PERMITTED_MUTATIONS: frozenset[Permission] = frozenset(
    permission for permission, ground in VIEW_AS_MUTATIONS.items() if ground is None
)


#: What `withheld_from_view_as` answers for a mutating permission nobody classified. A
#: sentence rather than a bare `True`, because this refusal reaches an operator's screen and
#: "no reason given" is the one refusal they cannot act on.
_UNCLASSIFIED_MUTATION: Final = (
    "This action has not been cleared for a view-as session. Perform it from the operator "
    "console, and tell us — a mutating permission with no view-as ruling is our defect."
)


def withheld_from_view_as(permission: Permission) -> str | None:
    """WHY a view-as session may not exercise this permission, or `None` if it may.

    THE ONE PREDICATE, asked by `core/auth.requires`, `copilot/actions.may_act` and
    `kb/curation.may_curate_knowledge`. All three used to spell the rule themselves as
    `impersonating and permission in MUTATING_PERMISSIONS`, which was three copies of one
    policy — fine while the policy was "all of them" and a drift waiting to happen the
    moment it stopped being.

    FAIL CLOSED ON AN UNCLASSIFIED PERMISSION: a mutating permission with no entry in
    `VIEW_AS_MUTATIONS` is withheld, so forgetting to classify a new one costs a support
    person a refusal rather than costing a client an unreviewed decision. The build refuses
    it separately (`tests/authz_audit_test.py`), so the fail-closed arm is a backstop and
    not the mechanism.
    """
    if permission not in MUTATING_PERMISSIONS:
        return None
    return VIEW_AS_MUTATIONS.get(permission, _UNCLASSIFIED_MUTATION)


# ══════════════════════════════════════════════════════════════════════════════════════
# THE SECOND HALF OF THE VIEW-AS RULING: ACTS, NOT PERMISSIONS (D-587).
#
# `VIEW_AS_MUTATIONS` rules on a PERMISSION, which is the right grain for almost
# everything: `org:manage` is "the owner's settings" and an operator fixing a client's
# settings is the whole point of the reversal. It is the wrong grain for a handful of
# acts that sit BEHIND a writable permission and are not settings at all:
#
#   * a payment — the client's money, and nobody spends it but them;
#   * a consent — given by the person who will receive the messages;
#   * an attestation — a named person's statement about a compliance fact;
#   * an IRREVERSIBLE DESTRUCTION of a client's records about a third party;
#   * a SPEND of the client's AI allowance under a permission that is otherwise settings
#     (`copilot:use` is withheld as a permission for this reason; two `org:manage` routes
#     meter the same wallet and had to be named);
#   * an ACCESS GRANT — an invitation or a role change, which mints a credential that
#     outlives the view-as session and is reachable from the operator console anyway;
#   * a personal UI row — owned by a `users.id` a view-as session does not have.
#
# Splitting a permission per act would put a second RBAC vocabulary in the schema and the
# generated client for four endpoints. Naming the acts does not: each site asks
# `core/auth.assert_view_as_may(principal, "<key>")`, the ground is written here once, and
# `tests/impersonation_writes_test.py` walks this mapping so the set is enumerable rather
# than a habit spread over four modules.
#
# THE LAST TWO ENTRIES ARE ALSO ENFORCED STRUCTURALLY and the guard is the message rather than the
# lock: `Principal.client_user_id` answers `None` for an operator, so neither row can be
# written with an operator's id even if that check were deleted. The check exists so the
# operator reads a sentence instead of meeting an FK violation.
#
# THIS IS THE SHORT LIST BECAUSE THERE IS A SECOND, OLDER MECHANISM AND IT ALREADY COVERS
# MOST OF THIS GROUND: `requires(..., realm="client")`, which `core/auth.current_principal`
# refuses to a request carrying `X-Impersonate-Org` before any permission is read. Four acts
# are withheld that way and are UNCHANGED by D-587 — `POST /v1/billing/topups/intent` (the
# client's money), `PUT /v1/billing/caps`, `POST /v1/compliance/whatsapp-alerts` (a person's
# consent) and `POST /v1/legal/acceptances` ("nobody signs for the client but the client").
# They are named here so the withheld set is readable in ONE place; the lock stays where it
# is, because a realm declaration is stronger than a call somebody has to remember and it is
# already what those four routes carry.
VIEW_AS_WITHHELD_ACTS: Mapping[str, str] = MappingProxyType(
    {
        "compliance.caller_memory_attestation": (
            "Attesting to what this account's calls collect is a statement the account "
            "makes about its own callers, not a setting. Ask the client to switch caller "
            "memory on from their own console — they are the ones a DPDP request about "
            "those notes will be answered by."
        ),
        "billing.ai_assist": (
            "Running the assistant over this account's call or script spends the "
            "account's own AI allowance, the same as its in-app assistant does. Ask the "
            "client to run it, or read the transcript yourself — support work is not "
            "billed to the client."
        ),
        "org.membership": (
            "Who may sign in to this account is the account's own decision, and an "
            "invitation outlives your view-as session. Use the client's invitation "
            "surface in the operator console, where it is recorded as your act."
        ),
        "kb.self_approve": (
            "Publishing knowledge under the client's own name is their approval to give. "
            "Approve it from the operator console's queue for this client, where the "
            "record shows that WE approved it."
        ),
        "compliance.erasure_request": (
            "Filing an erasure destroys this account's records of a person irreversibly, "
            "and it is the account's decision to make about their own customer. Ask the "
            "client to file it from their console — confirming that one has been done is "
            "a read and stays available to you."
        ),
        "leads.saved_view": (
            "A saved view belongs to one signed-in person of this account, and a view-as "
            "session is not one of them — there is no `users` row for it to belong to."
        ),
    }
)


# Routes exempt from the boot assertion: unauthenticated by design.
#
# `/openapi.json`, `/docs` and `/redoc` USED TO BE LISTED HERE and are not public any
# more: `create_app` serves them only outside `prod` (see the block that builds the
# FastAPI instance). Their entries were never load-bearing either — FastAPI mounts the
# doc endpoints as plain `starlette.routing.Route`s, which `iter_api_routes` does not
# yield, so the exemption exempted nothing while reading as a standing declaration that
# the whole schema is a public surface. `integrations/routes.py` cites that declaration
# as the reason one handler's docstring was rewritten.
PUBLIC_PREFIXES: tuple[str, ...] = (
    # The status word and the status code only — `core.health` gates the detail behind
    # `ops:manage` itself, which is why the prefix can stay exempt from the registry.
    "/healthz",
    "/hooks",
    "/v1/auth/",
    # The engine-called in-call ACTION execution endpoint. Unauthenticated by nature — Bolna
    # holds no Calevate session — and gated exactly like the webhook receiver: source-IP
    # allowlist, then the tenant is resolved from the injected agent ref through
    # `engine_agent_routes` and the tool is loaded under that tenant's RLS
    # (`apps/api/actions/routes.invoke_action`). The trailing slash keeps this to the invoke
    # path; the client-realm `/v1/actions/calendar/**` routes declare `org:manage` normally.
    "/v1/actions/invoke/",
    # The Content-Security-Policy violation collector (D-541). Unauthenticated in a
    # stronger sense than anything else on this list: a browser's reporting agent holds no
    # credential and cannot be given one, so there is no signature, no shared secret, no
    # source-IP allowlist and no cookie behind it. What stands in is ADMISSION CONTROL —
    # a strict content type, a 16 KiB bounded read, its own rate-limit profile, and a
    # refusal of any report whose `document-uri` is not one of our own console origins —
    # and `apps/api/security/routes.py` says in its own docstring that this is weaker than
    # a credential rather than pretending otherwise. The trailing slash keeps the
    # exemption to the reporting surface; there is exactly one route under it.
    "/reports/v1/",
    # The engine-called INBOUND caller-details fetch (D-513). Same class as the invoke
    # path one line up and unauthenticated for the same reason — Bolna holds no Calevate
    # session — but its credential is a Bearer token WE choose and paste into their agent
    # (`compliance/caller_data_routes`), because that is the mechanism their inbound data
    # -source feature offers. The trailing slash keeps this to the fetch itself.
    "/v1/engine/caller-data/",
    # The public SELF-SERVE RATE CARD (D-545): the list rate and the credit-pack ladder,
    # read by the marketing site's server to put "from ₹X/min" on `/pricing` and the live
    # rate into the ROI calculator. Unauthenticated because its only reader holds no
    # session and its only content is five code constants and one console setting,
    # identical for everyone — there is no tenant, no principal and nothing about the
    # caller in the body, and the same builder serves the authenticated `/packs` read
    # (`billing/payment_routes.rate_card_out`). A GET that mutates nothing; the trailing
    # slash keeps the exemption to this surface, and `check_public_routes` requires every
    # route mounted under it to be declared by name.
    "/v1/public/",
)

#: Path prefixes whose every route must enforce `realm="admin"`.
#:
#: THE PERMISSION IS NOT WHAT KEEPS A CLIENT OUT OF THE ADMIN CONSOLE, and this is the
#: check that says so. `ROLE_PERMISSIONS` is one flat dict over both realms, so a client
#: `owner` holds `org:manage`, `agents:write` and `kb:write` — the same strings a dozen
#: `/v1/admin/**` routes declare. What refuses them is `requires(..., realm="admin")`,
#: which resolves the caller against `admin_users` instead of `memberships`; a route
#: that declares the permission and omits the realm reads as guarded in the schema, in
#: the generated client and in review, and is open to every tenant owner on the platform.
#:
#: Asserted one-directionally: an admin-realm route may live outside these prefixes
#: (`/v1/organizations/{org_id}/llm-defaults`, the billing and compliance admin routers),
#: and this says nothing about those. What it forbids is the reverse — a route sitting
#: under the console's own paths that any signed-in client could call.
ADMIN_REALM_PREFIXES: tuple[str, ...] = ("/v1/admin/", "/v1/ops/")


# The attribute `auth.requires()` stamps on the dependency it returns, and the names of
# the dependencies that resolve an identity without checking a permission. Read by
# attribute rather than imported, because `core.auth` imports THIS module.
PERMISSION_ATTR = "calevate_permission"
REALM_ATTR = "calevate_realm"
IDENTITY_DEPENDENCIES: frozenset[str] = frozenset(
    {"current_any", "current_admin", "current_principal", "current_identity"}
)


#: Every permission SOME role holds. A permission held by no role names a lock with no
#: key: `role_has` answers False for every role the DB enums allow, so the route is a
#: 403 for the entire population — a dead route that reads as a guarded one.
GRANTED_PERMISSIONS: frozenset[str] = frozenset[str]().union(*ROLE_PERMISSIONS.values())


def role_has(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


class MissingPolicyError(RuntimeError):
    """Boot-time failure: a route neither declares a permission nor is public."""


def iter_api_routes(app: FastAPI) -> Iterator[APIRoute]:
    """Every APIRoute the app will actually serve.

    FastAPI 0.140 stopped flattening `include_router` at mount time: `app.routes` now
    holds opaque `_IncludedRouter` wrappers that resolve lazily at request time. A
    naive `isinstance(route, APIRoute)` loop over `app.routes` therefore sees ONLY the
    four built-in doc routes and silently passes — which would turn the boot assertion
    below into decoration. So walk anything that exposes nested routes, wrapper or not.
    """
    seen: set[int] = set()

    def _walk(routes: Iterable[object]) -> Iterator[APIRoute]:
        for route in routes:
            if id(route) in seen:
                continue
            seen.add(id(route))
            if isinstance(route, APIRoute):
                yield route
                continue
            nested = getattr(route, "original_router", None) or getattr(route, "routes", None)
            if nested is not None:
                yield from _walk(getattr(nested, "routes", nested))

    yield from _walk(app.routes)


def route_enforcement(route: APIRoute) -> tuple[frozenset[str], bool]:
    """What a route ACTUALLY checks: (permissions verified, is an identity resolved).

    Walks the whole dependency tree, so a permission reached through a shared
    `Annotated[...]` alias or a router-level `dependencies=[...]` counts the same as
    one written on the handler.
    """
    permissions: set[str] = set()
    identified = False

    def _walk(dependant: Dependant) -> None:
        nonlocal identified
        call = dependant.call
        if call is not None:
            enforced = getattr(call, PERMISSION_ATTR, None)
            if isinstance(enforced, str):
                permissions.add(enforced)
                identified = True
            elif getattr(call, "__name__", "") in IDENTITY_DEPENDENCIES:
                identified = True
        for sub in dependant.dependencies:
            _walk(sub)

    _walk(route.dependant)
    return frozenset(permissions), identified


def route_realms(route: APIRoute) -> frozenset[str]:
    """Which realm(s) this route's permission dependencies resolve the caller against.

    Read off `requires()`'s `calevate_realm` attribute the same way `route_enforcement`
    reads `calevate_permission`, and for the same reason: the registry must compare what
    a route DOES against what it says, and importing `core.auth` here is impossible
    (that module imports this one).

    Empty means "no `requires()` in the tree" — a route that resolves a bare identity, or
    none at all. `assert_policy_registry_complete` has already refused both by the time
    it asks this, so the caller never has to decide what an empty set means.
    """
    realms: set[str] = set()

    def _walk(dependant: Dependant) -> None:
        call = dependant.call
        if call is not None:
            realm = getattr(call, REALM_ATTR, None)
            if isinstance(realm, str):
                realms.add(realm)
        for sub in dependant.dependencies:
            _walk(sub)

    _walk(route.dependant)
    return frozenset(realms)


def assert_policy_registry_complete(app: FastAPI) -> None:
    """Called from `main.py` after routers are mounted. Every non-public route must
    DECLARE a permission in its `openapi_extra` and actually enforce it.

    Declaring is not enforcing. `permission_meta()` writes a string; the lock is
    `Depends(requires(...))`, and the two are written on separate lines of the same
    decorator — so the failure mode this guards is a route that carries the label with
    no lock behind it, or a label that names a different permission than the lock
    checks. Both read as protected in the OpenAPI schema, the generated TS client and
    any review that greps for `permission_meta`.
    """
    offenders: list[str] = []
    checked = 0
    for route in iter_api_routes(app):
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        checked += 1
        name = f"{sorted(route.methods or [])} {route.path}"
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        if not declared:
            offenders.append(name)
            continue
        # THE REGISTRY MUST NOT PASS ON A NAME THAT MEANS NOTHING. Until these two
        # clauses, `permission_meta("agents:reed")` + `requires("agents:reed")` sailed
        # through: declared and enforced agreed, so the check was satisfied by two
        # copies of the same typo. `role_has` then answered False for every role, and
        # the route was a 403 for everybody — a guarded-looking dead endpoint that no
        # test of a HAPPY path would ever be written against, because there is none.
        # mypy catches the literal spelling; it does not catch a permission that is
        # spelled correctly and granted to nobody, and neither of them is a check that
        # runs at boot on the route table the process is about to serve.
        if declared not in KNOWN_PERMISSIONS:
            offenders.append(f"{name} declares {declared!r}, which is not a Permission")
            continue
        if declared not in GRANTED_PERMISSIONS:
            offenders.append(
                f"{name} declares {declared!r}, which no role in ROLE_PERMISSIONS holds — "
                "the route would refuse every caller"
            )
            continue
        enforced, identified = route_enforcement(route)
        if not identified:
            offenders.append(f"{name} declares {declared} but authenticates nobody")
        elif declared not in enforced:
            # NOT `elif enforced and declared not in enforced`. That spelling exempted an
            # EMPTY enforcement set from the comparison, which is the WORST case rather
            # than a case with nothing to compare: a route carrying
            # `Depends(current_any)` (an identity, no permission) beside
            # `permission_meta("ops:manage")` satisfied every clause here and was open to
            # every signed-in caller of that realm. That is not hypothetical — `GET
            # /v1/me` shipped in exactly that shape, and `tests/authz_audit_test.py`
            # drove a `staff` member of one tenant into an `ops:manage` route and an
            # `operator` into a `platform:secrets` one while this assertion stayed green.
            offenders.append(
                f"{name} declares {declared} but enforces "
                f"{sorted(enforced) if enforced else 'nothing — it only resolves an identity'}"
            )
        elif route.path.startswith(ADMIN_REALM_PREFIXES) and route_realms(route) != {"admin"}:
            # See `ADMIN_REALM_PREFIXES`: on the console's own paths the permission is
            # not the thing keeping clients out, the realm is. A route here that resolves
            # `realm="any"` (the `requires()` default) is reachable by any tenant `owner`
            # whose own role holds the same string — and eleven of these paths declare a
            # permission `owner` holds.
            offenders.append(
                f"{name} is an admin-console path but enforces realm "
                f"{sorted(route_realms(route))} — it must be realm='admin'"
            )
    if checked == 0:
        # A registry that checks nothing is worse than no registry: it reads as a
        # passing guardrail. If route discovery ever breaks again, fail loudly.
        raise MissingPolicyError(
            "The RBAC policy registry found no routes to check. Route discovery is "
            "broken (see iter_api_routes) — fix it rather than removing this guard."
        )
    if offenders:
        raise MissingPolicyError(
            "Routes without a declared permission (BACKEND-PATTERNS §7): "
            + "; ".join(sorted(offenders))
            + ". Add `dependencies=[Depends(requires('<permission>'))]` and "
            "`openapi_extra=permission_meta('<permission>')`, or list the path in "
            "PUBLIC_PREFIXES with a reason."
        )


def permission_meta(permission: Permission) -> dict[str, object]:
    """OpenAPI extension the boot assertion reads; also documents the requirement in
    the generated TS client."""
    return {"x-calevate-permission": permission}


__all__ = [
    "ADMIN_REALM_PREFIXES",
    "ADMIN_ROLES",
    "GRANTED_PERMISSIONS",
    "IDENTITY_DEPENDENCIES",
    "IMPERSONATION_PERMITTED_MUTATIONS",
    "KNOWN_PERMISSIONS",
    "MUTATING_PERMISSIONS",
    "NORMAL_ADMIN_ROLE",
    "PERMISSION_ATTR",
    "PUBLIC_PREFIXES",
    "REALM_ATTR",
    "ROLE_PERMISSIONS",
    "SUPERADMIN_ONLY_PERMISSIONS",
    "SUPERADMIN_PERMISSIONS",
    "SUPERADMIN_ROLE",
    "VIEW_AS_MUTATIONS",
    "VIEW_AS_WITHHELD_ACTS",
    "MissingPolicyError",
    "Permission",
    "assert_policy_registry_complete",
    "iter_api_routes",
    "permission_meta",
    "role_has",
    "route_enforcement",
    "route_realms",
    "withheld_from_view_as",
]
