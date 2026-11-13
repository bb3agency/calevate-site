"""What a client is told about their line, in their words (D-701).

Three questions, always in this order: what happened, what we did, whether they need to do
anything. Written from the client's side of the counter: no system names, no vendor names,
no internal codes. The same sentences feed the dashboard notice, the email and the
WhatsApp template variables, so the three cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from apps.api.core.console_links import CONSOLE_BASE, DOMAIN

STATUS_PAGE_URL: Final = f"https://status.{DOMAIN}"

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
    if kind in ("script_fixed", "script_fix_waiting", *SCRIPT_CHECK_KINDS):
        return script_fix_notice(kind=kind, name=name, state=state, outcome=worst_signal)
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


#: The owner's notices for a fix the sweep of live scripts opened before any call (D-989),
#: the twins of `script_fixed` and `script_fix_waiting`.
SCRIPT_CHECK_KINDS: Final = frozenset({"script_check_fixed", "script_check_waiting"})


def script_fix_notice(*, kind: str, name: str, state: str, outcome: str | None = None) -> Notice:
    """A mistake fixed in the agent's own script (D-985), or waiting on the AI allowance to
    be fixed: seen on real calls, or, for the `script_check_*` kinds, found in the live
    script before any call showed it (D-989). `outcome` is the fix's incident's last step:
    put back by us, or undone by the owner. The fix and the Undo are on the Training tab."""
    early = kind in SCRIPT_CHECK_KINDS
    found = (
        f"A line in {name}'s script could cause a mistake on calls. We found it before any "
        "call did."
        if early
        else f"On real calls, {name} made a mistake that came from its script."
    )
    after = (
        "after we found a line that could cause a mistake"
        if early
        else ("after a mistake on real calls")
    )
    if kind in ("script_fix_waiting", "script_check_waiting"):
        if state == "resolved":
            return Notice(
                headline=f"A fix for {name} is no longer waiting",
                what_happened="Your AI allowance had run out, so a fix had to wait.",
                what_we_did="The agent's Training tab shows where the fix stands.",
                your_part="Nothing.",
                must_act=False,
            )
        return Notice(
            headline=f"A fix for {name} is waiting",
            what_happened=found,
            what_we_did="We have not changed it yet: your AI help for this month is used up.",
            your_part="Add more AI help on the AI help page, and we make the fix at once.",
            must_act=True,
        )
    if outcome == "undone":
        return Notice(
            headline=f"You put back {name}'s old script",
            what_happened=f"You undid a fix we made {after}.",
            what_we_did="Your script from before the fix is live again. We will not make "
            "that fix again on our own.",
            your_part="Nothing.",
            must_act=False,
        )
    if outcome == "rolled_back":
        return Notice(
            headline=f"We put back {name}'s old script",
            what_happened="A fix we made did not stop the mistake, or calls went worse after it.",
            what_we_did="Your script from before the fix is live again, and our team is "
            "looking at it.",
            your_part="Nothing.",
            must_act=False,
        )
    if state == "resolved":
        return Notice(
            headline=f"{name}'s script fix is settled",
            what_happened=f"We changed part of {name}'s script {after}.",
            what_we_did="We watched its next calls and closed this.",
            your_part="Nothing. The Training tab shows how it went.",
            must_act=False,
        )
    return Notice(
        headline=f"We fixed a mistake in {name}'s script",
        what_happened=found,
        what_we_did="We changed only that part of the script and put it live. We are "
        "watching the next calls, and put the old script back if they go worse.",
        your_part="Nothing. To keep your old script, press Undo on the agent's Training tab.",
        must_act=False,
    )


def incident_link(slug: str) -> str:
    return f"{CONSOLE_BASE}/c/{slug}/settings/line-protection"


__all__ = [
    "SCRIPT_CHECK_KINDS",
    "SIGNAL_WORDS",
    "STATUS_PAGE_URL",
    "Notice",
    "incident_link",
    "line_notice",
    "script_fix_notice",
]
