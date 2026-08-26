"""The step-up window is one number, and the screen that explains it must say the same one.

`authn/stepup.REAUTH_MAX_AGE` decides when a proved factor goes stale. Two other places
state it in words an operator reads:

  1. the API's own refusal, which DERIVES its sentence from the constant — nothing to
     drift, and asserted here so that stays true;
  2. `components/authn/stepUpPrompt.tsx`, which tells the operator how long the code they
     are about to type will last. That one is a hand-written copy in another language's
     source tree, and it was WRONG the moment the constant moved: the panel said "the last
     five minutes" while the server was being changed to thirty. Nothing in either
     language's test suite could see the other half.

So this file is the seam. It reads the TypeScript literal out of the file rather than a
build artefact, because the artefact is only produced by a `pnpm build` that CI runs after
this suite — a guard that needs a build to run is a guard that does not run.

Same shape as `tests/agent_transitions_mirror_test.py`: one fact, two languages, one
comparison.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.authn.stepup import REAUTH_MAX_AGE, reauthentication_required

PROMPT = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "src"
    / "components"
    / "authn"
    / "stepUpPrompt.tsx"
)

#: The console's copy of the window. Anchored to the exported constant's NAME, not to a
#: line number and not to the prose around it, so reformatting the file cannot break this
#: and renaming the constant cannot silently pass it.
_WEB_CONSTANT = re.compile(r"export const REAUTH_WINDOW_MINUTES\s*=\s*(\d+)\s*;")


def test_the_console_states_the_window_the_api_enforces() -> None:
    match = _WEB_CONSTANT.search(PROMPT.read_text(encoding="utf-8"))
    assert match is not None, (
        f"{PROMPT.name} no longer exports REAUTH_WINDOW_MINUTES. The panel tells an "
        "operator how long a proved factor lasts; if that number has moved into another "
        "shape, point this test at it rather than deleting it — an unpinned copy of "
        "REAUTH_MAX_AGE is how the panel came to say 'five minutes' about a 30-minute "
        "window."
    )
    assert int(match.group(1)) == REAUTH_MAX_AGE.total_seconds() // 60, (
        f"the console says {match.group(1)} minutes and "
        f"authn/stepup.REAUTH_MAX_AGE is {int(REAUTH_MAX_AGE.total_seconds() // 60)}. "
        "Change both, in the same commit."
    )


def test_the_api_refusal_derives_its_sentence_from_the_constant() -> None:
    """The refusal must never carry a hand-written duration.

    It currently interpolates `REAUTH_MAX_AGE`, which is why it needed no edit when the
    window moved. That is a property worth holding: an operator reading the 403 is being
    told what to do, and a stale number there sends them to re-prove a factor they are
    told is already stale.
    """
    detail = reauthentication_required("view_as:acme").detail
    assert f"{int(REAUTH_MAX_AGE.total_seconds() // 60)} minutes" in detail, detail
