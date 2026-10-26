"""What a live change note may say, and which tables say it (D-774).

A note is a TOPIC — a family of things a screen shows — never a row. Every table the
application writes is classified here exactly once: it either names the topic a write to
it changes, or it is quiet and says why. `tests/live_topics_test.py` holds that against
`Base.metadata`, so a table added later cannot silently miss live updates any more than a
web query key can (`apps/web/tests/liveTopics.test.ts` is the browser's half).

The note carries the topic, the instant and — on the operator stream only — the tenant
id. It carries no row id, no name, no phone number, no amount and no text (hard rule 6):
the page refetches through its normal, authorised routes and reads the change there.
"""

from __future__ import annotations

from typing import Final, Literal

Topic = Literal[
    "account",
    "agents",
    "alerts",
    "assistant",
    "callbacks",
    "calls",
    "campaigns",
    "conversation",
    "dnc",
    "healer",
    "integrations",
    "knowledge",
    "knowledge_gaps",
    "leads",
    "numbers",
    "platform",
    "quality",
    "wallet",
]

#: Topics that belong to ONE PERSON rather than to an account (D-782). A person's Pip
#: conversation is theirs alone, so its notes go to that person's channel and never to the
#: tenant or operator channel, where every colleague's open panel would hear them.
PERSON_TOPICS: Final[frozenset[Topic]] = frozenset({"conversation"})

#: Topics a client's own stream can carry. The rest describe the platform, not one
#: client, and only the operator stream carries them.
TENANT_TOPICS: Final[frozenset[Topic]] = frozenset(
    {
        "account",
        "agents",
        "assistant",
        "callbacks",
        "calls",
        "campaigns",
        "dnc",
        "healer",
        "integrations",
        "knowledge",
        "knowledge_gaps",
        "leads",
        "numbers",
        "quality",
        "wallet",
    }
)

#: The table a write landed in → the topic that write changes.
TABLE_TOPICS: Final[dict[str, Topic]] = {
    # calls
    "calls": "calls",
    "transcript_turns": "calls",
    "call_extractions": "calls",
    "call_engine_signals": "calls",
    "call_metering_refusals": "calls",
    "handoff_attempts": "calls",
    # leads
    "leads": "leads",
    "lead_events": "leads",
    "lead_call_holds": "leads",
    "lead_call_policies": "leads",
    "lead_field_drafts": "leads",
    "lead_saved_views": "leads",
    "caller_memories": "leads",
    # campaigns
    "campaigns": "campaigns",
    "campaign_contacts": "campaigns",
    "preference_scrub_runs": "campaigns",
    "dlt_registrations": "campaigns",
    "dlt_templates": "campaigns",
    "outbound_pledge_acceptances": "campaigns",
    "outbound_sender_attestations": "campaigns",
    "autodialer_notices": "campaigns",
    # call-backs
    "scheduled_callbacks": "callbacks",
    # knowledge
    "knowledge_gaps": "knowledge_gaps",
    "knowledge_gap_occurrences": "knowledge_gaps",
    "kb_sources": "knowledge",
    "kb_documents": "knowledge",
    "kb_uploads": "knowledge",
    "kb_facts": "knowledge",
    "kb_teachings": "knowledge",
    "teach_questions": "knowledge_gaps",
    "kb_index_documents": "knowledge",
    "engine_kb_routes": "knowledge",
    "pipecat_kb_objects": "knowledge",
    # money
    "credit_ledger": "wallet",
    "credit_lots": "wallet",
    "usage_events": "wallet",
    "topup_attempts": "wallet",
    "auto_recharge_charges": "wallet",
    "auto_recharge_settings": "wallet",
    "spend_state": "wallet",
    "monthly_fee_charges": "wallet",
    "monthly_fee_payments": "wallet",
    "one_time_charges": "wallet",
    "refund_intents": "wallet",
    "payment_disputes": "wallet",
    # agents
    "agents": "agents",
    "agent_workspace_moves": "agents",
    "agent_config_versions": "agents",
    "agent_config_attestations": "agents",
    "agent_handoff_members": "agents",
    "agent_health_windows": "agents",
    "agent_rule_proposals": "agents",
    "agent_test_cases": "agents",
    "call_test_case_drafts": "agents",
    "agent_test_labels": "agents",
    "agent_test_runs": "agents",
    "prompt_versions": "agents",
    "prompt_experiments": "agents",
    "prompt_experiment_variants": "agents",
    "call_variant_assignments": "agents",
    "engine_agent_routes": "agents",
    "engine_voice_clone_copies": "agents",
    "pipecat_agents": "agents",
    "extraction_schemas": "agents",
    "action_tools": "agents",
    "action_invocations": "agents",
    "live_apply_runs": "agents",
    # numbers
    "phone_numbers": "numbers",
    "phone_number_holds": "numbers",
    "number_holders": "numbers",
    "engine_number_purchases": "numbers",
    "forwarded_lines": "numbers",
    "forwarding_tests": "numbers",
    "forwarding_test_legs": "numbers",
    "save_number_messages": "numbers",
    "carrier_compliance_applications": "numbers",
    "tenant_engine_workspaces": "numbers",
    # do-not-call and consent
    "dnc_list": "dnc",
    "consent_ledger": "dnc",
    # the account itself
    "organizations": "account",
    "memberships": "account",
    "invitations": "account",
    "users": "account",
    "tenant_trials": "account",
    "tenant_feature_flags": "account",
    "kyc_records": "account",
    "kyc_documents": "account",
    "kyc_verification_requests": "account",
    "business_profiles": "account",
    "business_contacts": "account",
    "business_copies": "account",
    "legal_acceptances": "account",
    "deletion_requests": "account",
    "tenant_erasure_requests": "account",
    "processor_erasure_tasks": "account",
    "recording_erasure_holds": "account",
    "retention_policies": "account",
    "whatsapp_alert_optin_ledger": "account",
    # integrations
    "integration_credentials": "integrations",
    "inbound_webhooks": "integrations",
    "outbound_webhooks": "integrations",
    "webhook_deliveries": "integrations",
    "whatsapp_accounts": "integrations",
    "whatsapp_templates": "integrations",
    # the assistant
    "copilot_actions": "assistant",
    "copilot_jobs": "assistant",
    "copilot_routines": "assistant",
    "copilot_routine_runs": "assistant",
    "copilot_plans": "assistant",
    "copilot_plan_targets": "assistant",
    "admin_copilot_actions": "assistant",
    # quality
    "qa_reports": "quality",
    "qa_call_samples": "quality",
    # the healer
    "heal_incidents": "healer",
    "heal_actions": "healer",
    "heal_proposals": "healer",
    "heal_client_incidents": "healer",
    "heal_fallback_phones": "healer",
    # operator alarms
    "platform_alerts": "alerts",
    # the platform's own settings and price books
    "admin_users": "platform",
    "plans": "platform",
    "reserved_slugs": "platform",
    "fx_rate_observations": "platform",
    "number_price_attestations": "platform",
    "platform_ai_spend": "platform",
    "platform_ai_usage": "platform",
    "platform_config_version": "platform",
    "platform_cost_attestations": "platform",
    "platform_dashboard_data_use": "platform",
    "platform_engine_health": "platform",
    "platform_engine_minute_prices": "platform",
    "platform_engine_model_bands": "platform",
    "platform_in_call_data_use": "platform",
    "platform_inr_llm_prices": "platform",
    "platform_list_rate_cancellations": "platform",
    "platform_list_rates": "platform",
    "platform_maintenance_windows": "platform",
    "platform_model_prices": "platform",
    "platform_secrets": "platform",
    "platform_settings": "platform",
    "platform_speaking_rate": "platform",
    "platform_state": "platform",
    "platform_tts_plan_fees": "platform",
    "platform_tts_prices": "platform",
    "platform_tts_volume": "platform",
    "platform_voice_catalog": "platform",
    "spoken_style_publications": "platform",
    "spoken_style_revisions": "platform",
}

_DERIVED = "derived from rows another table already announces"
_MACHINERY = "delivery and retry machinery; no screen lists it"
_SECRET = "credential material; no screen may be told it moved"
_PERSONAL = (
    "one person's Pip conversation; announced on that person's own channel by "
    "`copilot/live_sync.py`, never to the whole account"
)

#: Tables whose writes announce nothing, with the reason. A new table goes in one map or
#: the other; the test refuses a table in neither.
QUIET_TABLES: Final[dict[str, str]] = {
    "audit_log": "the tamper-evident ledger; read on demand, and every write would echo",
    "first_run_recordings": "a brief clip kept only until it is text; its one screen polls it",
    "first_runs": "one owner's first-run state; the first-run screen polls it while a job runs",
    "agent_test_copies": (
        "the developer-workspace copy a paid account's test call rides (D-859), republished "
        "before each call; no screen reads it"
    ),
    "announcement_dismissals": "one person's own dismissals; their screen updates on the write",
    "notification_reads": "one person's own read marks; their screen updates on the write",
    "platform_announcements": (
        "operator-written banners, read on the web's five-minute announcements poll"
    ),
    "go_live_guides": "one owner's go-live guide state; its screen refetches on its own writes",
    "auth_credentials": _SECRET,
    "auth_email_tokens": _SECRET,
    "auth_identities": _SECRET,
    "auth_otp_challenges": _SECRET,
    "auth_sessions": _SECRET + "; written on every sign-in check",
    "idempotency_records": _MACHINERY,
    "outbox_messages": _MACHINERY,
    "webhook_inbox_events": _MACHINERY
    + "; written by voice-runtime, which stays out (hard rule 3)",
    "razorpay_object_routes": _MACHINERY,
    "retention_worklist": _MACHINERY,
    "copilot_memories": "the assistant's private recall; no screen lists it",
    "admin_copilot_memories": "the assistant's private recall; no screen lists it",
    "copilot_conversation_turns": _PERSONAL,
    "admin_copilot_conversation_turns": _PERSONAL,
    "copilot_uploads": _PERSONAL,
    "admin_copilot_uploads": _PERSONAL,
    "copilot_consents": (
        "read with the conversation, which every panel re-reads when it opens and when its "
        "tab regains focus (D-788); the conversation topic stays one person's"
    ),
    "caller_chunks": _DERIVED + " (`caller_memories`)",
    "kb_chunks": _DERIVED + " (`kb_sources`, `kb_documents`)",
    "kb_retrieval_logs": "a read log; writing one is a read, not a change",
    "call_engine_latency": "no writer since D-770; dropped in a later release",
    "first_campaign_reviews": "no writer since D-783; dropped in a later release",
}

#: Redis channel names. The tenant channel carries one client's notes; the operator
#: channel carries every note with its tenant id.
CHANNEL_PREFIX: Final = "calevate:live:"
OPERATOR_CHANNEL: Final = f"{CHANNEL_PREFIX}operators"


def tenant_channel(tenant_id: object) -> str:
    return f"{CHANNEL_PREFIX}tenant:{tenant_id}"


def person_channel(realm: str, person_id: object) -> str:
    """One signed-in person's channel. The realm is part of the name because a `users.id`
    and an `admin_users.id` are two id spaces."""
    return f"{CHANNEL_PREFIX}person:{realm}:{person_id}"


__all__ = [
    "CHANNEL_PREFIX",
    "OPERATOR_CHANNEL",
    "PERSON_TOPICS",
    "QUIET_TABLES",
    "TABLE_TOPICS",
    "TENANT_TOPICS",
    "Topic",
    "person_channel",
    "tenant_channel",
]
