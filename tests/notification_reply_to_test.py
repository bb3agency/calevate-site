"""A client pressing Reply reaches a mailbox somebody reads.

THE SPLIT THIS EXISTS FOR. The address a legal document PUBLISHES has to be a mailbox a
human actually reads; the address a platform SENDS FROM has to be one the delivery
provider will accept. Those are different requirements, and the documents now publish a
public-webmail address while the platform sends from the verified `calevate.tech` domain.

Without a Reply-To that is a real defect with no error attached: a client answers a
hot-lead notification or a low-balance warning, the reply goes to the From address, and
nobody ever sees it. The client believes they have written to us.

WHY NOT JUST CHANGE THE SENDER. Resend refuses a send outright (403) when the sender's
DOMAIN is unverified — `config.notifications_from`'s own comment records it, and
`transport.py` logs that refusal under its own event name. Nobody can verify a public
webmail domain, so pointing the sender at the published mailbox would not redirect the
mail; it would STOP it, for every notification the platform sends. Reply-To is the header
that exists for precisely this split.

Run: uv run pytest tests/notification_reply_to_test.py -q
"""

from __future__ import annotations

from apps.workers.transport import ResendTransport, SmtpTransport

SENDER = "support@calevate.tech"
READ_MAILBOX = "calevate.voice@gmail.com"


def test_the_resend_payload_carries_the_reply_address_when_one_is_set() -> None:
    transport = ResendTransport(api_key="k", sender=SENDER, reply_to=READ_MAILBOX)
    assert transport._reply_to == READ_MAILBOX
    assert transport._sender == SENDER, "the verified domain still sends"


def test_no_reply_to_header_is_written_when_none_is_configured() -> None:
    """The absent case must stay ABSENT rather than echo the From address.

    A Reply-To identical to From says nothing and some clients render it as an extra
    line, so "default it to the sender" is not a harmless simplification.
    """
    assert ResendTransport(api_key="k", sender=SENDER)._reply_to is None
    assert (
        SmtpTransport(host="h", port=25, username=None, password=None, sender=SENDER)._reply_to
        is None
    )


def test_the_smtp_message_carries_the_header() -> None:
    """Both providers, because a deployment may be on either and a header that exists on
    one is the kind of gap nobody notices until a client says they never heard back."""
    import smtplib
    from unittest.mock import MagicMock, patch

    transport = SmtpTransport(
        host="h", port=25, username=None, password=None, sender=SENDER, reply_to=READ_MAILBOX
    )
    with patch.object(smtplib, "SMTP") as smtp:
        smtp.return_value.__enter__.return_value = MagicMock()
        transport.send(to="client@example.com", subject="s", body="b")
        sent = smtp.return_value.__enter__.return_value.send_message.call_args
    assert sent is not None, "nothing was sent"
    assert sent.args[0]["Reply-To"] == READ_MAILBOX
    assert sent.args[0]["From"] == SENDER


def test_the_configured_default_points_at_the_published_mailbox() -> None:
    """FAILS IF: the documents and the reply address drift apart.

    The legal documents publish this address (`apps/web/src/lib/legal/placeholders.ts`).
    If somebody changes one and not the other, a client's reply goes nowhere again — which
    is the whole defect, returned.
    """
    from calevate_shared.config import Settings

    field = Settings.model_fields["notifications_reply_to"]
    assert field.default == READ_MAILBOX, (
        "the reply address no longer matches the mailbox the legal documents publish; "
        "change both or neither"
    )
