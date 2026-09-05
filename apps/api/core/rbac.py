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

from collections.abc import Iterable, Iterator
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
    # purchase is `org:manage` on `POST /v1/billing/topups/intent`, which IS mutating, so
    # a D-22 view-as operator can see a client's wallet on the support call and can never
    # spend from it. That split is the whole permission model of this screen.
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

# Permissions that mutate. An impersonating admin (D-22, read-only "view as client")
# is refused these even though its role grants them — no acting-as, ever.
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
        # replaced it: an operator in a D-22 read-only view-as session must not be able to
        # burn a client's included allowance from the client's own screen. Dropping the
        # route from a mutating permission to a non-mutating one would have removed that
        # refusal silently — the route would still have looked guarded, and the only
        # visible symptom would have been a client's bill.
        "copilot:use",
        # ASKING THE ADMIN ASSISTANT SPENDS OUR OWN AI CREDENTIAL — `platform_ai_usage` is
        # an append-only money row and the platform brake moves — so it is a mutation for
        # the same reason `copilot:use` is, and the sweep over the route table
        # (`tests/authz_audit_test.py`) states that rule rather than trusting a habit.
        # It is then named in `IMPERSONATION_PERMITTED_MUTATIONS`, which is where the D-22
        # question is answered for it; read that constant before reading this line as a
        # licence to act inside a client's session.
        "copilot:admin",
        "ops:manage",
        "admin:tenants",
        # Creating, promoting, demoting and revoking an operator account. Listed for the
        # same reason `platform:secrets` is, one step further in: a read-only view-as
        # session must never be able to hand somebody an admin account. It makes
        # `GET /v1/admin/operators` invisible under impersonation too, which is correct —
        # the operator directory is an admin-console read with no client-realm
        # counterpart, so it is listed in `ADMIN_CONSOLE_GETS`.
        "admin:operators",
        # An impersonating admin (D-22, read-only "view as client") is refused this even
        # though `superadmin` grants it. A view-as session exists to SEE a client's
        # screens; nothing about that job needs to change what engine the platform dials
        # on. `GET /v1/ops/config` therefore also becomes invisible under impersonation,
        # which is correct and is why it is listed in `ADMIN_CONSOLE_GETS`
        # (tests/impersonation_reads_test.py): it is an admin-console read that
        # impersonation never reaches, not a view a client's screen depends on.
        "platform:config",
        # Same rule, higher stakes: a read-only "view as client" session must never be
        # able to install a vendor credential. `GET /v1/ops/secrets` returns no plaintext
        # at all, so hiding it from impersonation costs a support person nothing.
        "platform:secrets",
    }
)


# THE ONE HOLE IN THE D-22 LINE, NAMED RATHER THAN LEFT AS AN `or` IN `requires()` (D-499).
#
# `requires()` refuses an impersonating principal every permission in `MUTATING_PERMISSIONS`
# — "no acting-as, ever". That rule is unchanged and this set does not weaken it, because
# what it exempts is not an ACT inside the client's account: it is the operator asking their
# OWN assistant a question while a client's screen is on the monitor.
#
# WHY IT IS SAFE IS A PROPERTY, NOT A PROMISE, and the property is the payer. `copilot:use`
# is in `MUTATING_PERMISSIONS` because asking spends THE CLIENT'S included allowance, and
# an operator burning it from the client's own screen is the exact hazard that listing
# exists for. `copilot:admin` spends `platform_ai_usage` — ours — on every path, whether the
# operator is impersonating or not (`billing/platform_ai.py`; the founder: *"You never
# charge a client for your own support work"*). So the hazard the listing protects against
# cannot occur on this permission: there is no client balance for it to move.
#
# WHAT AN IMPERSONATING OPERATOR STILL CANNOT DO, and none of it relies on this set:
#
#   * CHANGE ANYTHING. The admin assistant's write tools are refused at the point of use by
#     `actions.may_act`, which is `requires()`'s own ladder asked from a non-route caller —
#     the same `MUTATING_PERMISSIONS` membership, the same D-22 clause, one implementation.
#     `leads:write`, `leads:dispatch`, `org:manage` and `kb:write` are all in that set, so
#     every write tool refuses to PROPOSE and `write_tools.confirm` refuses again to APPLY.
#   * CONFIRM A PROPOSAL. `copilot:admin` is not `copilot:use`, and it is deliberately not
#     the permission on either confirm route; both stay refused by the ordinary D-22 line.
#   * SPEND THE CLIENT'S ALLOWANCE. `copilot:use` is NOT in this set and never will be —
#     that is the sentence to check if this constant is ever edited.
#
# A SET RATHER THAN A SPECIAL CASE IN `requires()`, so the exemption is a value a test can
# walk (`tests/admin_copilot_billing_test.py` pins its membership) rather than a branch a
# reader has to find.
IMPERSONATION_PERMITTED_MUTATIONS: frozenset[Permission] = frozenset({"copilot:admin"})


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
    # The engine-called INBOUND caller-details fetch (D-513). Same class as the invoke
    # path one line up and unauthenticated for the same reason — Bolna holds no Calevate
    # session — but its credential is a Bearer token WE choose and paste into their agent
    # (`compliance/caller_data_routes`), because that is the mechanism their inbound data
    # -source feature offers. The trailing slash keeps this to the fetch itself.
    "/v1/engine/caller-data/",
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
    "MissingPolicyError",
    "Permission",
    "assert_policy_registry_complete",
    "iter_api_routes",
    "permission_meta",
    "role_has",
    "route_enforcement",
    "route_realms",
]
