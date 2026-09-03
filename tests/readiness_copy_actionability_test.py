"""Every "here is what to do next" sentence names something the reader can ACTUALLY do.

THE DEFECT THIS CAUGHT. `pe_registration_missing` told a client to "give us the
registration id on the Verification screen", and `kyc_missing` to "send us your business
registration details from the Verification screen". That screen renders no form and issues
no mutation — it is read-only by design, and both values are written by an ADMIN
(`apps/api/admin/routes.py::record_kyc_verification`, and the `pe_registration_id_required`
path beside it). So a client whose campaigns were blocked was sent to a page to perform an
action that page cannot perform, and the only thing waiting for them there was the same
blocker restated.

Nothing errored. The client is simply stuck, on the screen we sent them to, with their
outbound calls stopped — and the support ticket that follows says "I did what it said".

WHY A TEST AND NOT JUST A FIX. The copy and the screen live in different languages in
different directories and nothing connected them, so the sentence stayed true-sounding
after the screen was built read-only. This test is that connection: it fails if a
client-actioned step points at a surface that cannot take the action.

Run: uv run pytest tests/readiness_copy_actionability_test.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.legal.readiness import ROW_COPY

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_PAGE = REPO_ROOT / "apps/web/src/app/c/[slug]/verification/page.tsx"

#: Verbs that promise the reader can ENTER something where they are being sent. "Shows",
#: "says" and "displays" are fine on a read-only screen; these are not.
_ENTRY_VERBS = re.compile(
    r"\b(give us|enter|upload|submit|type|paste|fill in|add)\b[^.]{0,60}\bon the (\w+) screen",
    re.IGNORECASE,
)
_FROM_SCREEN = re.compile(
    r"\b(send|give|upload|submit)\b[^.]{0,60}\bfrom the (\w+) screen", re.IGNORECASE
)


def test_the_verification_screen_is_still_read_only() -> None:
    """The premise of the test below, asserted rather than assumed.

    If somebody gives that screen a form, this fails and the guard below should be
    re-aimed rather than deleted — the copy would then be free to point at it again.
    """
    source = VERIFICATION_PAGE.read_text(encoding="utf-8")
    assert "useMutation" not in source and "<form" not in source, (
        "the Verification screen now takes input; re-check `readiness.ROW_COPY`, whose "
        "wording was corrected precisely because that screen could not take any"
    )


def test_no_client_step_asks_for_input_on_a_screen_that_takes_none() -> None:
    """FAILS IF: copy sends a client somewhere to type something they cannot type."""
    offenders: list[str] = []
    for rule, copy in ROW_COPY.items():
        if getattr(copy, "actor", None) != "client":
            continue
        step = copy.next_step
        for pattern in (_ENTRY_VERBS, _FROM_SCREEN):
            match = pattern.search(step)
            if match and match.group(2).lower() == "verification":
                offenders.append(f"{rule}: {step!r}")
    assert not offenders, (
        "these tell a client to enter something on the Verification screen, which renders "
        "no form and issues no mutation — the value is recorded by an admin. Say what the "
        "client actually does (send it to us) and what the screen actually does (show what "
        f"we hold): {offenders}"
    )


def test_every_client_step_says_what_the_client_does() -> None:
    """A step addressed to the client that names no action is a dead end with a title.

    Deliberately weak — it asks only that SOME instruction is present, because judging
    whether an instruction is a good one is not a thing a regex should claim to do.
    """
    silent = [
        rule
        for rule, copy in ROW_COPY.items()
        if getattr(copy, "actor", None) == "client" and len(copy.next_step.split()) < 5
    ]
    assert not silent, f"{silent}: addressed to the client and tells them nothing to do"
