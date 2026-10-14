"""The account page's "up to 14 days" is the server's `STAY_SIGNED_IN_TIMEOUTS.absolute` (D-766).

The switch's label states how long a session may last with it on. That number lives in
`apps/web` as a literal, so it is read out of the source and compared, the shape of
`tests/step_up_window_mirror_test.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.authn.sessions import STAY_SIGNED_IN_TIMEOUTS

ROW = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "src"
    / "components"
    / "authn"
    / "staySignedInRow.tsx"
)

_WEB_CONSTANT = re.compile(r"export const STAY_SIGNED_IN_DAYS\s*=\s*(\d+)\s*;")


def test_the_switch_states_the_lifetime_the_api_enforces() -> None:
    match = _WEB_CONSTANT.search(ROW.read_text(encoding="utf-8"))
    assert match is not None, f"{ROW.name} no longer exports STAY_SIGNED_IN_DAYS"
    assert int(match.group(1)) == STAY_SIGNED_IN_TIMEOUTS.absolute.days
