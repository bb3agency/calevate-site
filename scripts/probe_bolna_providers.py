"""Settle the OPERATIONS §2 gate on the Azure OpenAI credential entry (D-410).

WHY THIS STILL EXISTS AFTER D-410. It was written for gate 16c — "will the engine hold a
credential we can ROTATE?" — under D-404, whose whole design rested on replacing a
12-hour Vertex bearer every four hours through a `provider: "custom"` leg. D-410 removed
both halves of that: Azure OpenAI is a FIRST-CLASS Bolna provider, so the doubtful
`custom` route is not needed, and an Azure key is STATIC, so nothing rotates and there is
no cadence to prove. Deleting the file would have been the tidy move and it would have
been wrong, because the ONE thing gate 16c was really asking survived the migration
intact: **which entry in Bolna's credential store the Azure leg reads its key from, ON A
LIVE ACCOUNT.**

**WHAT CHANGED, AND IT MOVED THIS FILE FROM GUESSWORK TO CONFIRMATION.** Their
credential-store documentation is now readable, and it names FOUR required entries for
Azure OpenAI — `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE` and
`AZURE_OPENAI_API_VERSION`, under "All these keys must be added for the respective
provider". The AUTHORITATIVE list — with its citation, its per-key source in our
settings, and the one value nothing here can derive — is
`apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS`, and it is the only place a correction
belongs. The four names above are prose for a reader of this file; no code here reads
them, which is what keeps this from being a second copy that can drift.

So this probe no longer asks "what is the entry called". It asks the narrower question a
document cannot answer: does THIS account's store behave the way the page says, under the
name we are configured to use. `bolna_llm_credential_name` is still `applies: live`, so a
disagreement is one console edit and a re-run — no deploy, no republish.

**AND THE PROBE ONLY EVER COVERS ONE OF THE FOUR.** `set_llm_credential` writes the API
key, because that is the entry that must never be typed into a console by a human and the
only one whose value the platform holds in a form it can push. The endpoint, the
deployment and the api-version are the operator's, in the vendor console, and a green
result below says nothing about them.

**IT DRIVES THE REAL ADAPTER, and the first version of this file did not — which is the
part worth reading.** It hand-rolled `{"provider_name": ..., "provider_value": ...}` and
parsed `provider_name` back out of the response, and
`engine_audit_test::test_no_shipped_module_outside_the_adapters_reads_a_vendor_payload_key`
failed it correctly: hard rule 2 says only `apps/api/engine/` may see vendor payload
shapes. That guard caught a design mistake and not merely a lint violation. A probe that
reimplements the request proves that THE REIMPLEMENTATION works; a probe that calls
`engine.set_llm_credential` proves that the code which will actually write the credential
in production works, against the real vendor, which is the only thing the gate is asking.
The rule and the better test agreed.

WHAT IT DOES: builds the configured engine, asks whether the LLM leg is even ours, and
performs ONE real credential write with a marked inert value. The adapter does the
count-before / write / count-after itself and returns `LlmCredentialPlacement`, so this
file needs no knowledge of the vendor's JSON at all.

WHAT IT DELIBERATELY DOES NOT DO: publish an agent, place a call, or write the real Azure
key. The value here is a recognisable non-secret so that a human who finds it in the
dashboard later knows what it was and that it never authenticated anything.

READ THE RESULT AS HALF AN ANSWER — a smaller half than it used to be, but still a half.
A pass proves the STORE accepts and keeps a string under the name we use. It does NOT
prove a running agent receives it as `llm_key`; that needs a published agent and ONE
placed call. Under D-404 the second half also needed a second call thirteen hours later,
to prove the rotation rather than the wiring. A static key retires that: there is no
cadence left to observe, so one call closes it.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final

#: Obviously-not-a-credential, and it says so in its own value so that a human who finds
#: it in the dashboard six weeks from now needs no context to know it is safe to delete.
PROBE_VALUE: Final = "calevate-azure-gate-probe-not-a-real-credential"


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
            "credential of ours for it to hold. The gate does not apply to this config."
        )
        return 0

    try:
        placement = await engine.set_llm_credential(PROBE_VALUE)
    except Exception as exc:
        # The adapter's error ladder raises here. The status and reason are the finding,
        # so they are printed — `PROBE_VALUE` is not a secret and the ladder does not put
        # the API key in the message.
        print(
            f"GATE: NEGATIVE (so far) — the write failed: "
            f"{type(exc).__name__}: {str(exc)[:300]}\n\n"
            "This is a question about NAMING, not about the design. Azure OpenAI is a\n"
            "first-class provider on this platform, and their docs name the entry\n"
            "`AZURE_OPENAI_API_KEY`; a failure here means this ACCOUNT disagrees with\n"
            "that page.\n"
            "  * a 4xx naming the provider  -> read the store's own listing in the\n"
            "    dashboard and set `bolna_llm_credential_name` to what it shows. It is\n"
            "    `applies: live`, so each attempt is one console edit and a re-run, with\n"
            "    no deploy and no republish.\n"
            "  * a 404 on the store itself  -> the credential store does not exist on the\n"
            "    hosted API at all, and the key has to be configured on the agent in the\n"
            "    dashboard by hand. Say so in the gate; do NOT invent a second write path."
        )
        return 1

    print(
        f"GATE, FIRST HALF: PASS — the store accepted a write under {name!r}.\n"
        f"  replaced_in_place={placement.replaced_in_place} "
        f"superseded_removed={placement.superseded_removed}\n\n"
        "That is the premise about the STORE: it holds a string under a name we choose.\n"
        "STILL UNPROVEN, and it is the half that decides the leg — that an agent on the\n"
        "Azure provider actually receives this as its key. Publish an agent and place ONE\n"
        "call. There is no second observation to make: D-410's key is static, so nothing\n"
        "expires and nothing has to be watched over time.\n\n"
        "THREE MORE ENTRIES ARE REQUIRED AND THIS PROBE INSTALLS NONE OF THEM. Their\n"
        "Azure provider documents four keys; add the endpoint, the deployment and the\n"
        "api-version by hand in the vendor console. The names, their sources, and why\n"
        "the api-version has no derivable value here are in\n"
        "`apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS`. RECORD WHAT THE CONSOLE\n"
        "ACCEPTS FOR THE API-VERSION: it is what tells us whether their Azure client is\n"
        "the v1 surface we build for or the classic one.\n\n"
        f"NOTE: the probe value is still stored under {name!r}. It is inert, but replace\n"
        "it with the real key before anything depends on the leg — and note that a\n"
        "`replaced_in_place=False` above means the store APPENDS, which is the condition\n"
        "`engine_credential_not_replaced` pages on."
    )
    return 0


def main(argv: list[str]) -> int:
    if argv:
        print(f"usage: {sys.argv[0]}  (no arguments)", file=sys.stderr)
        return 2
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))
