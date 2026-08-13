# Recorded vendor payloads (adapter fixtures)

Empty until the Bolna pilot runs. That is the honest state: OPERATIONS §2 gates 1, 2, 4,
7 and 8 each end with "capture the payload as an adapter fixture", and none of them has
been attempted (ROADMAP gate G0). `docs/evidence/bolna-pilot-scorecard.md` says the same
thing in more detail.

## Why these files matter more than they look

The Bolna adapter is hand-maintained from the vendor's documentation because **Bolna
publishes no OpenAPI spec** (TRD §5). Every field name in `apps/api/engine/bolna.py` is
therefore a *claim*. A captured payload turns claims into tests, which is how a pilot
week's value survives the pilot week.

## How a file gets here

One way only:

```
uv run python -m scripts.pilot.record --gate 4 --name execution_completed \
    --source "GET /executions/{id}" --by "ops@calevate" --input payload.json
```

`scripts/pilot/record.py` **redacts on capture** — caller numbers, transcript text,
recording links and every free-form extraction value are replaced with structurally
valid placeholders before serialisation, the result is re-scanned, and nothing is written
if anything survives. Do not hand-write or hand-edit a file in this directory: a real
payload committed here is a permanent leak (`git rm` does not remove it from history),
and `MANIFEST.json` records a sha256 that a hand-edit invalidates.

`MANIFEST.json` carries, per fixture: the gate it came from, the endpoint, who captured
it, when, its sha256 and the redaction kinds that fired.

## What the placeholders are

- Phone numbers become `+91 5XXXXXXXXX`. Indian mobile numbers begin 9/8/7/6, so a
  5-series number cannot route to a person while staying E.164-shaped for the adapter.
- Recording links become `.invalid` hosts (RFC 2606 reserves that TLD so it never
  resolves); any query string is dropped, because a presigned link's query *is* a
  credential.
- Transcript lines become a fixed synthetic Telugu-transliterated script, preserving the
  turn count and the speaker prefixes the parser is tested on.
- `extracted_data` / `user_data` keep their KEYS and lose every value — the shape is what
  the fixture is for; the values are the caller's personal data.
