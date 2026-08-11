"""Calevate API — FastAPI modular monolith.

Run: uv run uvicorn apps.api.main:app --reload --port 8000

Module boundaries (TRD §1): tenancy, agents, engine, campaigns, ingest, postcall,
crm, analytics, billing, kb, integrations, compliance, audit. Each module owns its
tables; no cross-module SQL; they talk through service interfaces.

The bootstrap order is locked in `core/bootstrap.py` (BACKEND-PATTERNS §2) — this
file only declares WHICH routers the monolith mounts.
"""

from fastapi import FastAPI

from apps.api.core.bootstrap import create_app
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete

app: FastAPI = create_app(service="api", title="Calevate API", version="0.1.0")
install_error_handlers(app)


def _mount_routers(application: FastAPI) -> None:
    """Imports are local so a router import error names the module that broke."""
    from apps.api.admin.routes import router as admin_router
    from apps.api.agents.prompt_routes import router as prompt_admin_router
    from apps.api.agents.routes import router as agents_router
    from apps.api.agents.voice_routes import router as voice_router
    from apps.api.billing.credit_routes import router as credits_admin_router
    from apps.api.billing.payment_routes import router as topups_router
    from apps.api.billing.payment_routes import webhook_router as razorpay_router
    from apps.api.billing.routes import router as billing_admin_router
    from apps.api.campaigns.routes import router as campaigns_router
    from apps.api.compliance.deletion_routes import router as deletion_router
    from apps.api.compliance.dnc_routes import router as dnc_router
    from apps.api.compliance.export_routes import router as subject_export_router
    from apps.api.compliance.registration_routes import router as dlt_registration_router
    from apps.api.crm.routes import router as crm_router
    from apps.api.ingest.routes import router as ingest_router
    from apps.api.ingest.routes import sources_router as lead_sources_router
    from apps.api.integrations.routes import router as integrations_router
    from apps.api.kb.routes import router as kb_router
    from apps.api.ops.routes import router as ops_router
    from apps.api.tenancy.clerk_webhooks import router as clerk_router
    from apps.api.tenancy.routes import router as tenancy_router
    from apps.api.tenancy.signup_routes import router as signup_router

    application.include_router(tenancy_router)
    application.include_router(clerk_router)
    application.include_router(admin_router)
    application.include_router(billing_admin_router)
    application.include_router(credits_admin_router)
    application.include_router(prompt_admin_router)
    # BEFORE `agents_router`: FastAPI matches in declaration order, and
    # `/v1/agents/{agent_id}` would otherwise swallow `/v1/agents/voices` and reject it
    # as a malformed UUID. Same hazard `campaigns/routes.py` calls out for `/numbers`.
    application.include_router(voice_router)
    application.include_router(agents_router)
    application.include_router(campaigns_router)
    application.include_router(crm_router)
    application.include_router(kb_router)
    application.include_router(ingest_router)
    application.include_router(lead_sources_router)
    application.include_router(integrations_router)
    application.include_router(dnc_router)
    application.include_router(subject_export_router)
    application.include_router(deletion_router)
    application.include_router(dlt_registration_router)
    application.include_router(signup_router)
    application.include_router(topups_router)
    application.include_router(razorpay_router)
    application.include_router(ops_router)


_mount_routers(app)
# RBAC as a policy registry VALIDATED AT BOOT (BACKEND-PATTERNS §7): every mounted
# route that needs a permission must declare one, asserted at startup rather than
# discovered at first use.
assert_policy_registry_complete(app)
