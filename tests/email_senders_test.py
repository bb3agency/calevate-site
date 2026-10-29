"""Each email is sent from the sender of its purpose, and an unset purpose changes nothing.

D-933 splits the From address by purpose (security, notifications, billing, alerts,
operator). Until a sender is set, every purpose must send from `notifications_from`
exactly as before, which is what keeps live mail unchanged until rename day.
`docs/EMAILS.md` is the inventory these call sites are held to.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from apps.api.core import transport as transport_module
from apps.api.core.platform_config import FIELD_APPLIES, LIVE
from apps.api.core.settings import get_settings
from apps.api.ops.config_catalog import FIELD_META
from apps.workers import auth_email
from calevate_shared.config import EMAIL_SENDER_FIELDS, EmailPurpose, Settings, email_sender

REPO = Path(__file__).resolve().parents[1]

#: Every module that sends mail, and the purposes it sends under. A new sender, or a
#: purpose changed at a call site, fails here until `docs/EMAILS.md` and this map agree.
SENDERS: dict[str, frozenset[EmailPurpose]] = {
    "apps/api/core/alerting.py": frozenset({EmailPurpose.OPERATOR}),
    "apps/workers/alerts.py": frozenset({EmailPurpose.OPERATOR}),
    "apps/workers/account_closure.py": frozenset(
        {EmailPurpose.SECURITY, EmailPurpose.NOTIFICATIONS}
    ),
    "apps/workers/auth_email.py": frozenset({EmailPurpose.SECURITY, EmailPurpose.NOTIFICATIONS}),
    "apps/workers/billing.py": frozenset({EmailPurpose.BILLING}),
    "apps/workers/comp_notices.py": frozenset({EmailPurpose.OPERATOR, EmailPurpose.BILLING}),
    "apps/workers/credit_expiry.py": frozenset({EmailPurpose.BILLING}),
    "apps/workers/healer.py": frozenset({EmailPurpose.NOTIFICATIONS}),
    "apps/workers/kb_aggregation.py": frozenset({EmailPurpose.NOTIFICATIONS}),
    "apps/workers/maintenance.py": frozenset({EmailPurpose.NOTIFICATIONS}),
    "apps/workers/notifications.py": frozenset({EmailPurpose.ALERTS}),
    "apps/workers/number_holds.py": frozenset({EmailPurpose.NOTIFICATIONS}),
    "apps/workers/rate_card_notice.py": frozenset({EmailPurpose.BILLING}),
    "apps/workers/razorpay_jobs.py": frozenset({EmailPurpose.BILLING}),
    "apps/workers/team_alerts.py": frozenset({EmailPurpose.ALERTS, EmailPurpose.SECURITY}),
    "apps/workers/trial_notices.py": frozenset({EmailPurpose.NOTIFICATIONS}),
    "apps/workers/wallet_alerts.py": frozenset({EmailPurpose.BILLING}),
    "scripts/bootstrap_admin.py": frozenset({EmailPurpose.SECURITY}),
}


def _calls_get_transport(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "get_transport")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "get_transport")
        )
    ]


def _purposes_named(tree: ast.AST) -> set[EmailPurpose]:
    return {
        EmailPurpose[node.attr]
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "EmailPurpose"
        and node.attr in EmailPurpose.__members__
    }


def _sending_modules() -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for root in ("apps", "scripts"):
        for path in (REPO / root).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel.endswith("_test.py") or "/tests/" in rel or rel == "apps/api/core/transport.py":
                continue
            source = path.read_text(encoding="utf-8")
            if "get_transport(" not in source:
                continue
            tree = ast.parse(source)
            if _calls_get_transport(tree):
                found[rel] = tree
    return found


def test_every_sending_module_is_in_the_inventory() -> None:
    """FAILS IF: a module starts sending mail without a purpose decided for it."""
    assert set(_sending_modules()) == set(SENDERS)


@pytest.mark.parametrize("rel", sorted(SENDERS))
def test_every_call_names_its_purpose(rel: str) -> None:
    """FAILS IF: a call leans on the default, or a module's purposes drift from the map."""
    tree = _sending_modules()[rel]
    for call in _calls_get_transport(tree):
        assert call.args or call.keywords, f"{rel}:{call.lineno} sends with no purpose named"
    assert _purposes_named(tree) == set(SENDERS[rel])


def _today(**senders: str) -> Settings:
    """Settings with only `notifications_from` set, plus whatever senders a test names."""
    unset: dict[str, Any] = dict.fromkeys(EMAIL_SENDER_FIELDS.values())
    return get_settings().model_copy(
        update={**unset, "notifications_from": "support@example.test", **senders}
    )


@pytest.mark.parametrize("purpose", list(EmailPurpose))
def test_an_unset_purpose_sends_from_the_one_address_used_today(purpose: EmailPurpose) -> None:
    assert email_sender(_today(), purpose) == "support@example.test"


def test_every_purpose_sender_defaults_to_unset() -> None:
    """Live mail stays on `notifications_from` until somebody sets a purpose's sender."""
    for purpose, field in EMAIL_SENDER_FIELDS.items():
        if purpose is EmailPurpose.NOTIFICATIONS:
            continue
        assert Settings.model_fields[field].default is None, field


@pytest.mark.parametrize(
    ("purpose", "field"),
    [(p, f) for p, f in EMAIL_SENDER_FIELDS.items() if p is not EmailPurpose.NOTIFICATIONS],
)
def test_a_set_purpose_sends_from_its_own_address(purpose: EmailPurpose, field: str) -> None:
    settings = _today(**{field: " own@example.test "})
    assert email_sender(settings, purpose) == "own@example.test"
    others = [p for p in EmailPurpose if p is not purpose]
    assert all(email_sender(settings, p) == "support@example.test" for p in others)


@pytest.mark.parametrize("field", sorted(set(EMAIL_SENDER_FIELDS.values())))
def test_every_sender_is_a_live_console_setting(field: str) -> None:
    """Set from the ops console without a deploy, and read on every send."""
    assert FIELD_APPLIES[field].applies == LIVE
    assert field in FIELD_META


def test_the_transport_sends_from_the_purpose_and_keeps_the_reply_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_not_a_key")
    monkeypatch.setattr(settings, "notifications_from", "support@example.test")
    monkeypatch.setattr(settings, "notifications_reply_to", "reply@example.test")
    monkeypatch.setattr(settings, "sender_billing", "billing@example.test")
    monkeypatch.setattr(settings, "sender_security", None)

    billing = transport_module.get_transport(EmailPurpose.BILLING)
    security = transport_module.get_transport(EmailPurpose.SECURITY)
    assert isinstance(billing, transport_module.ResendTransport)
    assert isinstance(security, transport_module.ResendTransport)
    assert billing._sender == "billing@example.test"
    assert security._sender == "support@example.test"
    assert billing._reply_to == security._reply_to == "reply@example.test"


class _Recorder:
    name = "recorder"

    def __init__(self) -> None:
        self.purposes: list[EmailPurpose] = []

    def __call__(self, purpose: EmailPurpose) -> Any:
        self.purposes.append(purpose)
        return self

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        return True


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("otp_login_challenge", EmailPurpose.SECURITY),
        ("password_reset", EmailPurpose.SECURITY),
        ("invite_password", EmailPurpose.NOTIFICATIONS),
    ],
)
async def test_auth_mail_is_security_except_the_invitation(
    monkeypatch: pytest.MonkeyPatch, kind: str, expected: EmailPurpose
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(auth_email, "get_transport", recorder)
    payload = {"kind": kind, "realm": "client", "to": "a@example.test", "secret": "123456"}
    assert await auth_email.deliver_auth_email({"job_try": 1}, payload) == "sent"
    assert recorder.purposes == [expected]
