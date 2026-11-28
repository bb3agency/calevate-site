"""public API: tenant API keys and the API activity log (D-1047)

Revision ID: b1e7c4a9d2f3
Revises: e8b4d1f6a2c9
Create Date: 2026-11-28

`api_keys` holds one row per tenant API key: the SHA-256 of the secret (never the secret),
the scopes, the optional agent and address bindings, the per-key rate, the pinned
`Calevate-Version`, the expiry and the revocation. FORCE RLS on the tenant, with ONE
widening of READ: the row whose `secret_sha256` equals `app.api_key_sha256`, which
`db/session.api_key_session` sets from the presented key. That is how a bearer key finds
its tenant before a tenant is known; naming the digest means holding the key. WITH CHECK
stays the tenant's alone, so the widening writes nothing.

`api_requests` is the activity log: one row per public-surface request, route template and
status, never a path, query or body. FORCE RLS on the tenant, no widening.

`audit_log.actor_type` gains `api_key`: an act a key performed is recorded as the key.

Reversible: `downgrade()` drops both tables and restores the three-value actor CHECK (it
refuses while an `api_key` audit row exists, which is the ledger saying it cannot forget).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1e7c4a9d2f3"
down_revision: str | Sequence[str] | None = "e8b4d1f6a2c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = "api_keys"
REQUESTS = "api_requests"
TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
DIGEST_GUC = "NULLIF(current_setting('app.api_key_sha256', true), '')"


def _fk(table: str, column: str, target: str, ondelete: str) -> tuple[str, str]:
    name = f"fk_{table}_{column}_{target}"
    return name, (
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
        f"REFERENCES {target} (id) ON DELETE {ondelete} NOT VALID"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        KEYS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("display_prefix", sa.String(length=16), nullable=False),
        sa.Column("secret_sha256", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("agent_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("ip_cidrs", postgresql.ARRAY(postgresql.CIDR()), nullable=True),
        sa.Column("rate_per_minute", sa.Integer(), nullable=True),
        sa.Column("api_version", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("length(btrim(name)) BETWEEN 1 AND 80", name=op.f("ck_api_keys_name_bounds")),
        sa.CheckConstraint("cardinality(scopes) >= 1", name=op.f("ck_api_keys_has_scope")),
        sa.CheckConstraint(
            "rate_per_minute IS NULL OR rate_per_minute BETWEEN 1 AND 600",
            name=op.f("ck_api_keys_rate_bounds"),
        ),
        sa.CheckConstraint(
            "agent_ids IS NULL OR cardinality(agent_ids) BETWEEN 1 AND 50",
            name=op.f("ck_api_keys_agent_bounds"),
        ),
        sa.CheckConstraint(
            "ip_cidrs IS NULL OR cardinality(ip_cidrs) BETWEEN 1 AND 20",
            name=op.f("ck_api_keys_cidr_bounds"),
        ),
        sa.CheckConstraint("length(secret_sha256) = 64", name=op.f("ck_api_keys_digest_shape")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_api_keys_expires_after_created")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index("ix_api_keys_tenant_created", KEYS, ["tenant_id", "created_at"])
    op.create_index("uq_api_keys_secret_sha256", KEYS, ["secret_sha256"], unique=True)

    op.create_table(
        REQUESTS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("api_key_id", sa.UUID(), nullable=False),
        sa.Column("stream_id", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("problem_code", sa.String(length=80), nullable=True),
        sa.Column("remediation", sa.String(length=300), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("replayed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("api_version", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
            name=op.f("ck_api_requests_method_enum"),
        ),
        sa.CheckConstraint("status BETWEEN 100 AND 599", name=op.f("ck_api_requests_status_bounds")),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_api_requests_latency_bounds")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_requests")),
    )
    op.create_index("ix_api_requests_tenant_created", REQUESTS, ["tenant_id", "created_at"])
    op.create_index("ix_api_requests_key_created", REQUESTS, ["api_key_id", "created_at"])
    op.create_index("uq_api_requests_stream_id", REQUESTS, ["stream_id"], unique=True)

    fks = (
        _fk(KEYS, "tenant_id", "organizations", "RESTRICT"),
        _fk(KEYS, "created_by", "users", "CASCADE"),
        _fk(REQUESTS, "tenant_id", "organizations", "RESTRICT"),
        _fk(REQUESTS, "api_key_id", "api_keys", "CASCADE"),
    )
    for _name, statement in fks:
        op.execute(statement)
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name, _statement in fks:
        table = KEYS if name.startswith(f"fk_{KEYS}_") else REQUESTS
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")

    # Hard rule 1, in the same migration as the tables it protects.
    for table in (KEYS, REQUESTS):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {KEYS} "
        f"USING (tenant_id = {TENANT_GUC} OR secret_sha256 = {DIGEST_GUC}) "
        f"WITH CHECK (tenant_id = {TENANT_GUC})"
    )
    op.execute(f"CREATE POLICY tenant_isolation ON {REQUESTS} USING (tenant_id = {TENANT_GUC})")

    op.execute("ALTER TABLE audit_log DROP CONSTRAINT ck_audit_log_actor_enum")
    op.execute(
        "ALTER TABLE audit_log ADD CONSTRAINT ck_audit_log_actor_enum "
        "CHECK (actor_type IN ('admin', 'user', 'system', 'api_key'))"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT ck_audit_log_actor_enum")
    op.execute(
        "ALTER TABLE audit_log ADD CONSTRAINT ck_audit_log_actor_enum "
        "CHECK (actor_type IN ('admin', 'user', 'system'))"
    )
    op.drop_table(REQUESTS)
    op.drop_table(KEYS)
