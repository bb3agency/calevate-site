"""The server half of the voice worker's wire contract (D-621).

`apps/voice-worker` runs on Pipecat Cloud and cannot reach our Postgres at all
(`docs/DEPLOYMENT.md` §12.5 gate 6). This module is what it speaks to instead: three
Bearer-authenticated routes under `/v1/worker` that answer one agent's published
configuration and write one call's events, turns and settlement.

The rule the whole contract is shaped by — `docs/evidence/worker-http-contract.md`:

    THE WORKER SENDS WHAT IT OBSERVED. THE SERVER DECIDES WHAT THAT MEANS.

So everything that needs a key, a rate card, a tenant resolution or a row id happens
HERE, and none of it exists in the container a vendor's runtime operates.
"""
