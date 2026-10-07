"""The `.env` block `runbooks/first-deploy.md` tells an operator to type, against the gate
that reads it.

`scripts/check_deploy_env` refuses a deploy without the carrier leg's env-only keys, and the
runbook is the only place a first-time operator learns which keys to write. A key the gate
demands and the runbook omits is a first deploy refused at its preflight with no step that
says where the value comes from; `VOBIZ_CALLBACK_SECRET` (D-673) shipped exactly that way.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.check_deploy_env import (
    CARRIER_CLAIM_KEY,
    CARRIER_CREDENTIAL_KEYS,
    VOBIZ_CALLBACK_SECRET_KEY,
)

RUNBOOK = Path(__file__).resolve().parent.parent / "runbooks" / "first-deploy.md"

#: The env-only keys of the owned runtime's carrier leg. `PIPECAT_STREAM_BASE_URL` and
#: `WEBHOOK_BASE_URL` are console-managed, so the runbook sets them in the console (§9a).
ENV_ONLY_CARRIER_KEYS = (CARRIER_CLAIM_KEY, *CARRIER_CREDENTIAL_KEYS, VOBIZ_CALLBACK_SECRET_KEY)


def _env_block_keys() -> set[str]:
    text = RUNBOOK.read_text(encoding="utf-8")
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, flags=re.DOTALL)
    host_env = [b for b in blocks if re.search(r"^APP_ENV=prod$", b, flags=re.MULTILINE)]
    assert len(host_env) == 1, "expected exactly one host .env block (the one with APP_ENV=prod)"
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", host_env[0], flags=re.MULTILINE))


def test_the_host_env_block_carries_every_env_only_carrier_key() -> None:
    missing = [k for k in ENV_ONLY_CARRIER_KEYS if k not in _env_block_keys()]
    assert missing == [], f"first-deploy.md's .env block omits {missing}"


def test_the_host_env_block_leaves_the_carrier_switch_to_the_console() -> None:
    # The environment beats the console, so a `CARRIER=` line would make the console's
    # carrier switch accept a change and do nothing (the runbook says so beside the block).
    assert "CARRIER" not in _env_block_keys()
