"""Plivo — DECLARED, NOT IMPLEMENTED, because its transfer grammar is unreadable here.

**`start_transfer` RAISES. THAT IS THE FINISHED STATE OF THIS FILE, NOT A STUB** — the
same shape `compliance/kyc_providers/setu.py` and `campaigns/provisioning.
PROVISIONING_IMPLEMENTED = False` take: refused work rather than unfinished work.
`registry.available_transfer()` never selects a provider whose contract is unattested, so
nothing reaches this method in a running deployment; it raises so that a future carrier
wired in by hand fails at the seam instead of on a caller.

WHAT IS ACTUALLY KNOWN ABOUT THIS CARRIER FROM A SOURCE WE HOLD
----------------------------------------------------------------
The one primary source readable from this container is the pinned wheel,
`pipecat-ai==1.10.0` (`uv.lock`; `.venv/lib/python3.12/site-packages/pipecat_ai-1.10.0.
dist-info`). EVIDENCE CLASS: VERIFIED-VENDOR-SDK, cited by file and line:

* A CREDENTIALLED REST PATH EXISTS AND ITS BASE SHAPE IS VISIBLE.
  `pipecat/serializers/plivo.py:184` builds
  `https://api.plivo.com/v1/Account/{auth_id}/Call/{call_id}/`, authenticates with HTTP
  Basic over `(auth_id, auth_token)` (`:187`), and hangs the call up with `DELETE`
  (`:191`), reading 204 as success and 404 as already-ended (`:192-194`).
* THAT IS THE ONLY PLIVO REST ENDPOINT IN THE ENTIRE PACKAGE. A search of the installed
  tree for `api.plivo.com` returns that one line and nothing else.
* The answer document Pipecat's own runner serves for Plivo is
  `<Response><Stream bidirectional="true" keepCallAlive="true" contentType=…>wss://…
  </Stream></Response>` (`pipecat/runner/run.py:1437-1440`). It is a STREAM element and
  says nothing about transferring, dialling a second leg, whispering or bridging.

WHAT IS UNKNOWN, IN THOSE WORDS
--------------------------------
**UNKNOWN — api.plivo.com and www.plivo.com are egress-blocked from this container**
(measured 21 Sep 2026: `curl https://www.plivo.com/docs/voice/api/call` and
`curl https://api.plivo.com/v1/` both answer `curl: (56) CONNECT tunnel failed, response
403`; `docs/evidence/pre-build-blockers-2026-09-13.md` §10 recorded the same). Therefore:

* UNKNOWN — how a live leg is redirected, or a second leg dialled and bridged to it:
  the method, the path, the parameter names and the request body are all unread.
* UNKNOWN — whether this carrier can play a private message to the CALLED party before
  bridging, and whether it can require a keypress to accept. Without those two, steps 2
  and 3 of the pattern in `base.py` cannot be expressed at all.
* UNKNOWN — which parameter presents the header on the second leg, which is the one that
  decides whether hard rule 5's neighbour, the CLI rule, can even be honoured.
* UNKNOWN — how the ending is reported back, and whether the bridged leg's duration is in
  it. Without that, the second leg is billable time this product cannot meter.

**NOTHING ABOVE IS GUESSED FROM `keepCallAlive`.** That attribute is copied from the
vendor's own template by `apps/voice-runtime/carrier_routes.py`, whose docstring states
plainly that we do not know what it means. A name that is probably right is the defect
class D-631 exists for, and this is the file where guessing would cost the most: a caller
who has been told to hold.

THE FIVE FACTS, AND THE PROMPT THAT FETCHES THEM
-------------------------------------------------
Hand this to a browser-capable agent, or read it at a terminal with egress, and paste the
answers back with the page URL and the date beside each one. This file can then be
written in an afternoon; nothing else about the seam changes.

    Read https://www.plivo.com/docs/voice/api/call and the XML reference at
    https://www.plivo.com/docs/voice/xml and answer ONLY from those pages, quoting the
    page and section for each answer. Say "not stated on these pages" rather than
    inferring:
      1. The exact HTTP request that transfers or redirects a LIVE call: method, full
         path, required headers, and every field of the request body.
      2. Whether a second leg can be dialled and bridged to a live call by API rather
         than by re-rendering XML, and if so, the exact request.
      3. Whether the called party can be played a private message before the two legs
         are bridged, and whether the bridge can be made conditional on that party
         pressing a key: the exact attribute or parameter names, and the timeouts.
      4. Which parameter sets the CALLER ID presented on that second leg, and what the
         account must hold for a given number to be presentable.
      5. How the outcome of that second leg is reported back — the callback URL
         parameter, the field carrying the ending, the field carrying the DURATION, and
         the exact values the ending field can take.

Fact 3 is a gate rather than a curiosity. If this carrier cannot whisper-and-accept, the
pattern this seam implements is not available on it, and the decision is the founder's to
take again — not this file's to work around by bridging blind.
"""

from __future__ import annotations

from apps.api.agents.transfer_providers.base import (
    TransferContractUnverifiedError,
    TransferRequest,
    TransferStarted,
)

_WHY = (
    "Plivo's call-transfer contract has not been read from Plivo's own documentation: "
    "api.plivo.com and www.plivo.com are egress-blocked from this deployment's build "
    "environment, and the pinned Pipecat wheel contains exactly one Plivo REST endpoint "
    "(the hangup). The five facts required, and the prompt that fetches them, are in this "
    "module's docstring."
)


class PlivoTransfers:
    """Placeholder for the real adapter. Selecting it is a configuration error."""

    @property
    def name(self) -> str:
        return "plivo"

    @property
    def contract_verified(self) -> bool:
        return False

    @property
    def settles_synchronously(self) -> bool:
        # NOT A CLAIM THAT THIS CARRIER CANNOT. Fact 5 of the prompt above is what would
        # answer it, and until it is read the safe answer is the one that places no leg.
        return False

    async def start_transfer(self, request: TransferRequest) -> TransferStarted:
        raise TransferContractUnverifiedError(_WHY)


__all__ = ["PlivoTransfers"]
