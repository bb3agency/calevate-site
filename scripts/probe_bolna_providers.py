"""Settle OPERATIONS §2 gate 16c: will the engine hold a credential we can rotate?

WHY THIS EXISTS. Gate 16c is the last unverified premise under D-404 — the in-call LLM
leg rests on the hosted platform accepting a credential string we replace every four
hours. A read-only browser sweep (19 Aug 2026) found no Provider Keys page in the
dashboard and no `custom` entry in the agent LLM dropdown, which is evidence about the UI
and settles nothing about the API. This makes the API call.

**IT DRIVES THE REAL ADAPTER, and the first version of this file did not — which is the
part worth reading.** It hand-rolled `{"provider_name": ..., "provider_value": ...}` and
parsed `provider_name` back out of the response, and
`engine_audit_test::test_no_shipped_module_outside_the_adapters_reads_a_vendor_payload_key`
failed it correctly: hard rule 2 says only `apps/api/engine/` may see vendor payload
shapes. That guard caught a design mistake and not merely a lint violation. A probe that
reimplements the request proves that THE REIMPLEMENTATION works; a probe that calls
`engine.set_llm_credential` proves that the code which will actually rotate the
credential in production works, against the real vendor, which is the only thing gate 16c
is asking. The rule and the better test agreed.

WHAT IT DOES: builds the configured engine, asks whether the LLM leg is even ours, and
performs ONE real credential write with a marked inert value. The adapter does the
count-before / write / count-after itself and returns `LlmCredentialPlacement`, so this
file needs no knowledge of the vendor's JSON at all.

WHAT IT DELIBERATELY DOES NOT DO: publish an agent, place a call, or write a real bearer.
A live credential belongs in that store only via `scripts/rotate_llm_credential.py`, which
mints one properly. The value here is a recognisable non-secret so that a human who finds
it in the dashboard later knows what it was and that it never authenticated anything.

READ THE RESULT AS HALF AN ANSWER. A pass proves the STORE accepts and keeps a string we
can replace on a schedule. It does NOT prove a running agent receives it as `llm_key` —
that needs a published agent and one placed call, then a second call 13 hours later to
prove the rotation rather than the wiring. Both halves are gate 16c.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final

#: Obviously-not-a-credential, and it says so in its own value so that a human who finds
#: it in the dashboard six weeks from now needs no context to know it is safe to delete.
PROBE_VALUE: Final = "calevate-gate16c-probe-not-a-real-credential"


async def _run() -> int:
    from apps.api.core.settings import get_settings
    from apps.api.engine import get_engine

    settings = get_settings()
    engine = get_engine(settings)
    name = settings.bolna_llm_credential_name

    print(f"engine={engine.name}  credential name under test={name!r}\n")

    if not engine.capabilities.is_ours("llm"):
        # Not a failure of the gate — a deployment whose engine dictates its own model has
        # no credential of ours to store, and the probe would be measuring nothing.
        print(
            f"SKIPPED — the {engine.name!r} engine chooses its own model, so there is no\n"
            "credential of ours for it to hold. Gate 16c does not apply to this config."
        )
        return 0

    try:
        placement = await engine.set_llm_credential(PROBE_VALUE)
    except Exception as exc:
        # The adapter's error ladder raises here. The status and reason are the finding,
        # so they are printed — `PROBE_VALUE` is not a secret and the ladder does not put
        # the API key in the message.
        print(
            f"GATE 16c: NEGATIVE (so far) — the write failed: "
            f"{type(exc).__name__}: {str(exc)[:300]}\n\n"
            "If this is a 404, the credential store does not exist on the hosted API and\n"
            "D-404's rotation route is closed — the fallback is a first-class provider\n"
            "that takes a STATIC key and can be region-pinned (Azure OpenAI in an India\n"
            "region is the candidate), NOT D-405's proxy, which is still rejected.\n"
            "If this is a 4xx naming the provider, try the other plausible spellings:\n"
            "`bolna_llm_credential_name` is `applies: live`, so each attempt is one\n"
            "console edit and a re-run, with no deploy and no republish."
        )
        return 1

    print(
        f"GATE 16c, FIRST HALF: PASS — the store accepted a write under {name!r}.\n"
        f"  replaced_in_place={placement.replaced_in_place} "
        f"superseded_removed={placement.superseded_removed}\n\n"
        "That is D-404's premise about the STORE: it holds a string we can replace on a\n"
        "schedule. STILL UNPROVEN, and it is the half that decides the leg — that an\n"
        "agent with provider='custom' actually receives this as `llm_key`. Publish an\n"
        "agent and place ONE call; then wait 13 hours and place a second, which is what\n"
        "proves the rotation rather than the wiring.\n\n"
        f"NOTE: the probe value is still stored under {name!r}. It is inert, but let the\n"
        "next `rotate_llm_credential` run overwrite it before anything real depends on it."
    )
    return 0


def main(argv: list[str]) -> int:
    if argv:
        print(f"usage: {sys.argv[0]}  (no arguments)", file=sys.stderr)
        return 2
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))
