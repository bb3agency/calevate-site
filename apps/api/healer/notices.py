"""What a client is told about their line, in their words (D-701).

Three questions, always in this order: what happened, what we did, whether they need to do
anything. Written from the client's side of the counter: no system names, no vendor names,
no internal codes. The same sentences feed the dashboard notice, the email and the
WhatsApp template variables, so the three cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from apps.api.core.console_links import CONSOLE_BASE

STATUS_PAGE_URL: Final = "https://status.calevate.tech"

#: The worst signal (`health.Verdict.worst_signal`) in a client's words.
SIGNAL_WORDS: Final[dict[str, str]] = {
    "broken": "many callers were cut off or hung up within seconds",
    "knowledge": "it often could not find answers in your business information",
    "slow": "callers waited too long before it started speaking",
    "actions": "bookings, messages or other tasks it tried during calls did not go through",
    "language": "callers often spoke a language it is not set up to use",
    "escalations": "far more callers than usual asked to be put through to a person",
}


@dataclass(frozen=True, slots=True)
class Notice:
    headline: str
    what_happened: str
    what_we_did: str
    your_part: str
    must_act: bool

    def as_text(self, *, link: str) -> str:
        return "\n\n".join(
            (
                f"What happened: {self.what_happened}",
                f"What we did: {self.what_we_did}",
                f"What you need to do: {self.your_part}",
                "See the details:",
                link,
            )
        )


def _ending(phone: str | None) -> str:
    return phone[-4:] if phone else ""


def line_notice(
    *,
    kind: str,
    protection: str,
    agent_name: str | None,
    campaigns_paused: int,
    fallback_phone: str | None,
    state: str,
    missed_calls: int,
    requeued: int,
    worst_signal: str | None = None,
    has_proposal: bool = False,
) -> Notice:
    """The notice for one `heal_client_incidents` row, open or resolved."""
    name = f"“{agent_name}”" if agent_name else "Your agent"
    paused = (
        f" {campaigns_paused} campaign{'s' if campaigns_paused != 1 else ''} using it "
        f"{'are' if campaigns_paused != 1 else 'is'} paused."
        if campaigns_paused
        else ""
    )
    if state == "resolved":
        follow_up = []
        if missed_calls:
            follow_up.append(
                f"{missed_calls} caller{'s' if missed_calls != 1 else ''} reached your line "
                "while it was not working properly. Open the details to see who to call back."
            )
        if requeued:
            follow_up.append(
                f"{requeued} campaign call{'s' if requeued != 1 else ''} that failed will be "
                "tried again."
            )
        return Notice(
            headline=f"{name} is answering calls again",
            what_happened=f"{name} had a problem taking calls. It is fixed now.",
            what_we_did="We checked it was working properly and turned it back on."
            + (" Paused campaigns have restarted." if campaigns_paused else ""),
            your_part=" ".join(follow_up) or "Nothing.",
            must_act=bool(missed_calls),
        )
    if kind == "platform_outage":
        return Notice(
            headline="Calls are affected for everyone right now",
            what_happened="Our calling service is having a problem that is not limited to "
            "your account.",
            what_we_did=(
                f"We are passing your callers to your number ending {_ending(fallback_phone)}."
                if protection == "forwarded"
                else "Callers hear a short message asking them to try again later."
            )
            + paused
            + f" Live updates are at {STATUS_PAGE_URL}.",
            your_part="Nothing. We will tell you as soon as calls are back to normal.",
            must_act=False,
        )
    if kind == "agent_unwell":
        signal = SIGNAL_WORDS.get(worst_signal or "", "its recent calls went worse than usual")
        return Notice(
            headline=f"{name} is struggling on calls",
            what_happened=f"Over the last hour {signal}.",
            what_we_did="We checked and repaired everything on our side.",
            your_part=(
                "We have suggested a change for you to review. Nothing changes until you "
                "approve it."
                if has_proposal
                else "Nothing for now. We are watching it and will tell you if that changes."
            ),
            must_act=has_proposal,
        )
    if protection == "forwarded":
        did = (
            f"Callers are being passed to your number ending {_ending(fallback_phone)} "
            f"while we fix it.{paused}"
        )
        part = "Keep that phone with you until we tell you the line is back."
    elif protection == "paused":
        did = (
            "We stopped it answering, so callers hear a short message asking them to try "
            f"again later.{paused}"
        )
        part = (
            "Nothing right now. To have callers reach your team instead next time, add a "
            "phone number under Settings, then Line protection."
            if not fallback_phone
            else "Nothing right now. We will tell you as soon as the line is back."
        )
    else:
        did = f"We are working on it.{paused}"
        part = "Nothing right now. We will tell you as soon as it is fixed."
    return Notice(
        headline=f"{name} is not taking calls properly",
        what_happened=f"Most recent calls to {name} were cut off or went silent.",
        what_we_did=did,
        your_part=part,
        must_act=False,
    )


def incident_link(slug: str) -> str:
    return f"{CONSOLE_BASE}/c/{slug}/settings/line-protection"


__all__ = ["SIGNAL_WORDS", "STATUS_PAGE_URL", "Notice", "incident_link", "line_notice"]
