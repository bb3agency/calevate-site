"""Calevate API — FastAPI modular monolith.

Run: uv run uvicorn apps.api.main:app --reload --port 8000

Module boundaries (TRD §1): tenancy, agents, engine, campaigns, ingest, postcall,
crm, analytics, billing, kb, integrations, compliance, audit. Each module owns its
tables; no cross-module SQL; they talk through service interfaces.

The bootstrap order is locked in `core/bootstrap.py` (BACKEND-PATTERNS §2) — this
file only declares WHICH routers the monolith mounts.
"""

from collections.abc import AsyncIterator

from fastapi import FastAPI

from apps.api.core.bootstrap import create_app
from apps.api.core.errors import install_error_handlers
from apps.api.core.platform_config import start_config_refresher
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.flags.registry import assert_flag_registry_wellformed
from apps.api.ops.fx_rates import start_fx_refresher
from apps.api.ops.pricing_snapshot import start_pricing_refresher


async def _startup() -> AsyncIterator[None]:
    """Begin polling `platform_config_version` (PLATFORM-CONFIG §6).

    ONE LINE, and it is the whole adoption surface: from here on, a value changed in the
    ops console — or in psql at 3am — reaches this process within a few seconds with no
    restart, through the `get_settings()` every handler already calls. A deployable that
    does NOT call this runs on `os.environ` plus code defaults, exactly as it did before
    this feature existed, which is what makes the adoption per-service and reversible.

    It is started here rather than inside `create_app` deliberately. `create_app` is
    shared with voice-runtime, and putting a background poll into every service by
    default would decide hard rule 3's question — what may run beside the webhook path —
    on that service's behalf, in a file its owner does not read. `start_config_refresher`
    is idempotent, so adopting it there later is the same single line.

    `start_pricing_refresher` is the same adoption for the attested-price seam: it installs
    the two sync readers billing/ and the picker consume (`ops/pricing_snapshot.py`) and
    begins polling `platform_model_prices`. Started HERE and not in `create_app` for the
    identical reason — it is a background poll, and voice-runtime must not inherit one. The
    worker process (`apps/workers/settings.py::startup`) prices the dashboard assist and
    should call it too once an OpenAI/Google model is selectable; until then only Azure is
    offerable and it bills off its verified catalogue reading with no reader installed.

    `start_fx_refresher` is the third, and it puts the PUBLISHED USD→INR rate into this
    process's memory so `engine/bolna.py::_cost` can convert a vendor's dollars at it
    without a database round trip. The worker calls it too and needs it more — that is
    where a call's cost is actually metered — but the API converts on every `list_calls`
    and cost preview it serves, and a process reading a different rate from its neighbour
    is exactly the disagreement this seam exists to prevent. voice-runtime deliberately
    does NOT: it parses a webhook into a `CallEvent` and never meters, so it would inherit
    a background poll for a number it does not use (hard rule 3), and its parse falls back
    to the configured rate as it always has.
    """
    start_config_refresher()
    start_pricing_refresher()
    start_fx_refresher()
    yield


app: FastAPI = create_app(service="api", title="Calevate API", version="0.1.0", on_startup=_startup)
install_error_handlers(app)


def _mount_routers(application: FastAPI) -> None:
    """Imports are local so a router import error names the module that broke."""
    from apps.api.actions.routes import router as actions_router
    from apps.api.admin.closure_routes import router as tenant_closure_router
    from apps.api.admin.health_routes import router as client_health_router
    from apps.api.admin.holds_routes import router as hold_queue_router
    from apps.api.admin.number_routes import router as number_supply_router
    from apps.api.admin.operator_routes import router as operator_router
    from apps.api.admin.routes import router as admin_router
    from apps.api.agents.experiment_routes import router as experiment_router
    from apps.api.agents.extraction_routes import admin_router as extraction_admin_router
    from apps.api.agents.extraction_routes import router as extraction_router
    from apps.api.agents.handoff_routes import router as handoff_router
    from apps.api.agents.llm_routes import admin_router as llm_defaults_admin_router
    from apps.api.agents.llm_routes import router as llm_defaults_router
    from apps.api.agents.prompt_routes import router as prompt_admin_router
    from apps.api.agents.publishing_routes import router as publishing_router
    from apps.api.agents.routes import router as agents_router
    from apps.api.agents.script_routes import router as script_router
    from apps.api.agents.voice_routes import router as voice_router
    from apps.api.authn.routes import (
        admin_auth_router,
        client_auth_router,
        invite_router,
    )
    from apps.api.billing.ai_quota_routes import router as ai_quota_router
    from apps.api.billing.cap_routes import router as caps_router
    from apps.api.billing.credit_routes import router as credits_admin_router
    from apps.api.billing.payment_routes import refund_router
    from apps.api.billing.payment_routes import router as topups_router
    from apps.api.billing.payment_routes import webhook_router as razorpay_router
    from apps.api.billing.routes import client_router as billing_invoice_router
    from apps.api.billing.routes import router as billing_admin_router
    from apps.api.billing.spend_routes import client_router as billing_spend_router
    from apps.api.billing.spend_routes import router as spend_admin_router
    from apps.api.billing.trial_routes import router as trials_admin_router
    from apps.api.billing.wallet_routes import router as wallet_router
    from apps.api.callbacks.routes import router as callbacks_router
    from apps.api.campaigns.provisioning_routes import router as numbers_router
    from apps.api.campaigns.routes import router as campaigns_router
    from apps.api.compliance.caller_data_routes import router as caller_data_router
    from apps.api.compliance.caller_notice_routes import router as caller_notice_router
    from apps.api.compliance.consent_routes import call_router as call_consent_router
    from apps.api.compliance.consent_routes import router as messaging_consent_router
    from apps.api.compliance.deletion_routes import router as deletion_router
    from apps.api.compliance.dnc_routes import router as dnc_router
    from apps.api.compliance.export_routes import router as subject_export_router
    from apps.api.compliance.first_campaign_routes import (
        admin_router as first_campaign_admin_router,
    )
    from apps.api.compliance.first_campaign_routes import router as first_campaign_router
    from apps.api.compliance.kyc_routes import router as kyc_router
    from apps.api.compliance.national_dnd_routes import (
        campaign_router as preference_scrub_router,
    )
    from apps.api.compliance.national_dnd_routes import (
        global_router as global_dnc_router,
    )
    from apps.api.compliance.registration_routes import router as dlt_registration_router
    from apps.api.compliance.tenant_erasure_routes import router as tenant_erasure_router
    from apps.api.compliance.whatsapp_optin_routes import (
        admin_router as whatsapp_optin_admin_router,
    )
    from apps.api.compliance.whatsapp_optin_routes import router as whatsapp_optin_router
    from apps.api.copilot.admin_routes import router as admin_copilot_router
    from apps.api.copilot.routes import router as copilot_router
    from apps.api.crm.routes import router as crm_router
    from apps.api.flags.routes import router as feature_flags_router
    from apps.api.ingest.routes import router as ingest_router
    from apps.api.ingest.routes import sources_router as lead_sources_router
    from apps.api.insights.routes import router as knowledge_gaps_router
    from apps.api.integrations.routes import router as integrations_router
    from apps.api.kb.routes import router as kb_router
    from apps.api.legal.routes import router as legal_readiness_router
    from apps.api.ops.config_routes import router as ops_config_router
    from apps.api.ops.dashboard_data_use_routes import router as ops_data_use_router
    from apps.api.ops.fx_routes import router as ops_fx_router
    from apps.api.ops.model_price_routes import router as ops_model_prices_router
    from apps.api.ops.routes import router as ops_router
    from apps.api.ops.secret_routes import router as ops_secrets_router
    from apps.api.quality.routes import router as quality_router
    from apps.api.quality.sampling_routes import router as qa_sampling_router
    from apps.api.tenancy.routes import router as tenancy_router
    from apps.api.tenancy.signup_routes import router as signup_router

    application.include_router(tenancy_router)
    # D-170's first-party authentication. Mounted unconditionally and gated per request by
    # `Settings.first_party_auth_enabled` — a conditionally-mounted router would be
    # invisible to `check_wiring`, absent from the OpenAPI contract, and would answer 404
    # during the one operation where "not switched on yet" and "wrong path" must be
    # distinguishable. Three routers because the two realms are two route trees that share
    # no session logic, and the invitation redemption creates an identity rather than
    # operating on one.
    #
    # NO DEFAULT RESTATED HERE, because the one that was restated was WRONG: this said
    # "(default off)" while `calevate_shared.config` declares `= True` and
    # `authn/routes.py`'s own header says True. It is a KILL SWITCH over the only
    # authentication this product has, not a cutover gate — a deployment that came up with
    # it off would have nobody able to sign in — so a reader who believed this line
    # believed the opposite of the posture. The value lives on the field; `authn/routes.py`
    # argues what it means.
    application.include_router(admin_auth_router)
    application.include_router(client_auth_router)
    application.include_router(invite_router)
    application.include_router(admin_router)
    # The ops hold queue. Its own `/v1/admin/compliance/...` prefix rather than a path
    # under `admin_router`: `/v1/admin/tenants/{tenant_id}` would swallow any literal
    # segment added beside it (the hazard `voice_router` above calls out), and this is a
    # cross-tenant list, not a tenant's record.
    application.include_router(hold_queue_router)
    # Who may use the console at all — the superadmin tier's own surface. Its own
    # `/v1/admin/operators` prefix for the reason the two above have theirs: it is not a
    # segment under `/v1/admin/tenants/{tenant_id}`, which would swallow any literal
    # beside it, and it is about US rather than about a client.
    application.include_router(operator_router)
    # Buying, linking and releasing a phone number (D-537). Its own
    # `/v1/admin/numbers` prefix for the reason the three above have theirs:
    # `/v1/admin/tenants/{tenant_id}` would swallow a literal `/numbers` beside it,
    # and the inventory search is cross-tenant — it is about the vendor's stock, not
    # about a client. The tenant-scoped operations carry the tenant in their path
    # under this prefix instead.
    application.include_router(number_supply_router)
    # The client health board, for the same reason and with the same hazard in mind: it
    # is a cross-tenant exception report, so it gets its own `/v1/admin/client-health`
    # prefix rather than a segment under `/v1/admin/tenants/{tenant_id}`.
    application.include_router(client_health_router)
    application.include_router(billing_admin_router)
    application.include_router(credits_admin_router)
    # Beside the wallet it deliberately does not touch (D-536): a trial bypasses the credit
    # gate rather than granting credit, so these two routers share a tenant path prefix and
    # nothing else.
    application.include_router(trials_admin_router)
    application.include_router(prompt_admin_router)
    application.include_router(experiment_router)
    # BEFORE `agents_router`: FastAPI matches in declaration order, and
    # `/v1/agents/{agent_id}` would otherwise swallow `/v1/agents/voices` and reject it
    # as a malformed UUID. Same hazard `campaigns/routes.py` calls out for `/numbers`.
    application.include_router(voice_router)
    # Before `agents_router`: `/v1/agents/lanes` is a literal path and
    # `/v1/agents/{agent_id}` would swallow it if the parameterised router won.
    application.include_router(publishing_router)
    # Before `agents_router`: the structured-script builder lives under
    # `/v1/agents/{agent_id}/script/...`; mounting it first keeps its literal `script`
    # subsegment from being shadowed by any `/v1/agents/{agent_id}` route.
    application.include_router(script_router)
    # Before `agents_router`, for `script_router`'s reason (D-533): the handover list lives
    # under `/v1/agents/{agent_id}/handoff`, and mounting it first keeps that literal
    # subsegment from being shadowed by any `/v1/agents/{agent_id}` route declared later.
    application.include_router(handoff_router)
    application.include_router(agents_router)
    # The ACCOUNT-level model default (D-454). Its own paths (`/v1/organization/...`,
    # `/v1/admin/organizations/...`) collide with nothing above, so mount order is not
    # load-bearing here — unlike `voice_router`, whose literal segment lives under
    # `/v1/agents/`.
    application.include_router(llm_defaults_router)
    application.include_router(llm_defaults_admin_router)
    # Editing an agent's extraction VARIABLES (D-460). The client router's
    # `/v1/agents/{agent_id}/extraction-schema` carries a fourth segment, so it never
    # collides with `/v1/agents/{agent_id}` on `agents_router`; the admin router names its
    # tenant in the path like `prompt_admin_router` and collides with nothing under
    # `/v1/admin/tenants/{tenant_id}`.
    application.include_router(extraction_router)
    application.include_router(extraction_admin_router)
    application.include_router(campaigns_router)
    # `/v1/numbers/purchase` — its own prefix, so nothing above can swallow it. It lives
    # in the campaigns package because that module owns `phone_numbers`.
    application.include_router(numbers_router)
    application.include_router(crm_router)
    # The call-backs an agent promised on a call (D-514). Its own literal `/v1/callbacks`
    # prefix, which collides with nothing above, so mount order is not load-bearing here.
    # There is no route on it that CREATES one: a call-back exists because a caller asked
    # for it mid-call, through the in-call tool in `apps/voice-runtime`.
    application.include_router(callbacks_router)
    # The engine-called inbound caller-details fetch (D-513). Its own literal
    # `/v1/engine/caller-data` prefix — declared in `core.rbac.PUBLIC_PREFIXES` and in
    # `scripts/check_public_routes.UNAUTHENTICATED_ROUTES`, which is the reviewed line
    # that says why the world may call it. It lives in `apps/api` rather than in
    # voice-runtime because it derives a keyed caller reference and reads a tenant's
    # store, which that service's import surface forbids it to hold.
    application.include_router(caller_data_router)
    # The in-app AI copilot (`apps/api/copilot/`). Its own literal `/v1/copilot` prefix,
    # which collides with nothing above, so mount order is not load-bearing here — unlike
    # `voice_router`, whose literal segment lives under `/v1/agents/`.
    #
    # ⚠ **THIS USED TO SAY "CLIENT REALM ONLY", AND THE ADMIN TWIN NOW EXISTS (D-499).**
    # The reason there was none was that the admin realm had no PAYER, not that nobody had
    # written it; `billing/platform_ai.py` and `platform_ai_usage` are that payer, so
    # `copilot/admin_routes.py` mounts beside this one under `/v1/admin/copilot`. Two
    # routes, two realms, two tool arrays, two memories, two ledgers — one service.
    application.include_router(copilot_router)
    application.include_router(admin_copilot_router)
    # Knowledge gaps — the urgent "what the agents couldn't answer" surface. Its own
    # literal `/v1/knowledge-gaps` prefix collides with nothing above, so mount order is
    # not load-bearing here.
    application.include_router(knowledge_gaps_router)
    application.include_router(kb_router)
    application.include_router(ingest_router)
    application.include_router(lead_sources_router)
    application.include_router(integrations_router)
    # ACTIONS feature: the engine-called in-call execution endpoint + the client-realm
    # Actions tab (credentials, tools, test harness, calendar OAuth).
    application.include_router(actions_router)
    application.include_router(dnc_router)
    # The writer `dnc_list.scope='global'` never had (migration a1c8e40f27b9), and the
    # national preference-scrub record beside it. Both live in the compliance package
    # because that package owns the tables; both carry their own realm prefix —
    # `/v1/ops/dnc/global` for the platform-wide list, and the usual
    # `/v1/admin/tenants/{tenant_id}/...` for the per-tenant scrub — the same split the
    # first-campaign pair below uses.
    application.include_router(global_dnc_router)
    application.include_router(preference_scrub_router)
    application.include_router(subject_export_router)
    # All four `/v1/compliance/...` routers carry literal second segments and none has a
    # `{param}` at that position, so declaration order is not load-bearing between them
    # today — but messaging-consent goes first so that a future
    # `/v1/compliance/{something}` router added below cannot swallow it. FastAPI matches
    # in declaration order (see `voice_router` above).
    application.include_router(messaging_consent_router)
    application.include_router(call_consent_router)
    application.include_router(deletion_router)
    # The client's draft of the notice they owe their own CALLERS (D-179,
    # LEGAL-SURFACE F-8). The duty is theirs — they are the Data Fiduciary — but the
    # itemised list Rule 3 asks for is their extraction schema, which only we hold. A
    # literal `/v1/compliance/caller-notice`, declared with the other compliance routers
    # and ordered by the same rule they are.
    application.include_router(caller_notice_router)
    # The admin-realm twin: the END of an engagement rather than one data principal's
    # §12 request, and the only writer `organizations.deleted_at` has (FLOWS §9, D-120).
    application.include_router(tenant_erasure_router)
    # D-536. Mounted beside the erasure router and after `admin_router` for the same
    # reason that one is: `/v1/admin/tenants/{tenant_id}` on `admin_router` would swallow
    # any literal segment declared later, and both of these name their tenant in the path.
    application.include_router(tenant_closure_router)
    application.include_router(dlt_registration_router)
    application.include_router(kyc_router)
    # R-11's first-campaign hold: the client's view of it, and ops's release. The admin
    # half carries its own `/v1/admin/tenants/{tenant_id}/...` prefix — it lives in the
    # compliance package because that package owns the table, exactly as the agents
    # package owns its admin publishing routes.
    application.include_router(first_campaign_router)
    application.include_router(first_campaign_admin_router)
    # The CLIENT's own WhatsApp alert opt-in (FLOWS §6, migration e6b2d94f31a7) and the
    # operator's record of one given during onboarding. Two realms, one ledger: the
    # client half is the owner speaking for themselves, the admin half is an operator
    # recording that they did, with the document to show for it. Same package/prefix
    # split as the first-campaign pair above, for the same reason — the compliance
    # package owns the table.
    application.include_router(whatsapp_optin_router)
    application.include_router(whatsapp_optin_admin_router)
    # Agreements & readiness (migration a9d4e70c31b8): the four published documents this
    # client must accept, plus every organisation-level condition that stops their
    # outbound, in one client-realm read. No admin twin, deliberately — nobody accepts a
    # client's agreements but the client, so there is no operator write to mount and the
    # operator's view of the same conditions is the health board they already have.
    application.include_router(legal_readiness_router)
    # Per-tenant feature flags (SURFACES §1). Its own
    # `/v1/admin/tenants/{tenant_id}/feature-flags` prefix, like every other per-tenant
    # admin surface that owns its own table — the flags package owns `tenant_feature_flags`
    # exactly as the compliance package owns `first_campaign_reviews`.
    application.include_router(feature_flags_router)
    application.include_router(signup_router)
    # Both are literal paths under `/v1/billing` and neither carries a `{param}` at
    # that position, so declaration order is not load-bearing between them — but caps
    # goes first so that a future `/v1/billing/{something}` router added below cannot
    # swallow it. FastAPI matches in declaration order (see `voice_router` above).
    application.include_router(caps_router)
    application.include_router(topups_router)
    application.include_router(razorpay_router)
    application.include_router(refund_router)
    # The client's own invoice — the same `build_invoice` the admin route serves, in the
    # realm of the persona BRD §51 says pays it. Literal `/v1/billing/invoice`, declared
    # beside the other two `/v1/billing/*` routers for the same reason they are ordered
    # this way: a future `/v1/billing/{something}` router added below cannot swallow it.
    application.include_router(billing_invoice_router)
    # The dashboard-AI allowance and the one thing a client can buy with it (D-127
    # G-3/G-4/G-5). Literal `/v1/billing/ai-quota`, declared with the other `/v1/billing/*`
    # routers and for the same ordering reason they give.
    application.include_router(ai_quota_router)
    # Where every rupee went, per agent and per call (D-12). TWO routers because it is
    # two realms over one computation: the client's is `/v1/billing/spend` and publishes
    # only what they were CHARGED, the admin's is `/v1/admin/spend` + one per tenant and
    # adds what we PAID. Declared with the other `/v1/billing/*` routers for the ordering
    # reason they give.
    application.include_router(billing_spend_router)
    application.include_router(spend_admin_router)
    # THE CLIENT'S OWN WALLET (2 Sep 2026): balance, how long it lasts, where it went,
    # the ledger with a receipt per payment, and the payments that failed. Literal
    # `/v1/billing/wallet`, declared with the other `/v1/billing/*` routers for the
    # ordering reason they give. Its permission is `wallet:read`, which — uniquely on
    # this prefix — `staff` holds: the thing that stops a staff member dialling is an
    # empty wallet, and a refusal only the owner can read is a refusal with no words.
    application.include_router(wallet_router)
    # The client's monthly QA report (SURFACES §2 trust surfaces) and OUR weekly 5%
    # spot-check queue (SURFACES §1). Two realms, one control: the report is the claim
    # we make to the client, the queue is the evidence we collect for it.
    application.include_router(quality_router)
    application.include_router(qa_sampling_router)
    application.include_router(ops_router)
    # Platform configuration (PLATFORM-CONFIG §7). Its own router beside the ops
    # switchboard, and its own permission: `ops:manage` is the incident surface, this is
    # change management, and the two are held by different people on purpose.
    application.include_router(ops_config_router)
    # Credentials — its OWN permission (`platform:secrets`), held by fewer people than
    # anything else on this list. No route on it returns plaintext (§7).
    application.include_router(ops_secrets_router)
    # Operator-attested model prices — `platform:config` like the config panel (a price is
    # configuration, not a credential), effective-dated and append-only. What lets a model
    # whose catalogue price is unverified become offerable.
    application.include_router(ops_model_prices_router)
    # Which LLM legs the in-app assistant may run on, and the operator attestation behind it
    # (D-477). Its own router beside the price panel for `model_price_routes.py`'s reason:
    # same realm and permission, different store and a different write shape.
    application.include_router(ops_data_use_router)
    # The exchange rate every dollar of vendor cost is converted at — read-only, and on
    # `platform:config` beside the price panel for the same reason: it is a number that
    # decides money and it is not a credential. There is no write route (`ops/fx_routes.py`
    # argues why); the operator's control is the declared fallback in the config panel.
    application.include_router(ops_fx_router)


_mount_routers(app)
# RBAC as a policy registry VALIDATED AT BOOT (BACKEND-PATTERNS §7): every mounted
# route that needs a permission must declare one, asserted at startup rather than
# discovered at first use.
assert_policy_registry_complete(app)
# The feature-flag registry, asserted at the same moment and for the same reason
# (BACKEND-PATTERNS §7): `FlagName` is what `mypy` checks call sites against and `FLAGS`
# is what the console offers, so a name in one and not the other is a flag that is either
# unreachable from code or unsettable from the console.
assert_flag_registry_wellformed()
