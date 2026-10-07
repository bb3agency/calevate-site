# ThinnestAI documentation mirror (read-only)

This is a byte-exact snapshot of the ThinnestAI developer documentation. ThinnestAI is being evaluated as a second voice engine beside our own Pipecat runtime (D-678).

This mirror is the **VERIFIED-VENDOR-DOCS** evidence class for every ThinnestAI claim in this repository. Cite it as `thinnest-findings/mirror/pages/<path>.md:<line>`.

## Source

- **Vendor:** ThinnestAI, at `https://docs.thinnest.ai/`.
- **Page list:** every `.md` link in `https://docs.thinnest.ai/llms.txt`, the docs site's own index, saved here as `llms.txt`.
- **Fetching:** each page was fetched as raw Markdown at its listed `.md` URL on 6 Oct 2026. The per-run UTC timestamp is in `MANIFEST.json`.
- **Result:** 90 of 90 pages fetched, with no failures.

## Layout

| Path | What it is |
| --- | --- |
| `pages/<path>.md` | One page per docs URL, with its path preserved (`/api-reference/agents.md` becomes `pages/api-reference/agents.md`) |
| `llms.txt` | The docs site's index, as fetched |
| `MANIFEST.json` | The URL, path, sha256 and byte count of every page |

## Rules

- **Never edit, reformat or move a file here.**
  - Ruff excludes this tree (`pyproject.toml`).
  - Git stores it with `-text` (`.gitattributes`), so line endings are never rewritten.
  - The large-file hook skips it (`.pre-commit-config.yaml`).
- **Refreshing the mirror is a new fetch and a new MANIFEST, committed as one change.** Pages cited by line number must then be re-checked.
- **What the docs do not say is not evidence.** Several commercial terms are founder-relayed and recorded in `docs/evidence/thinnest-ai-evaluation.md` with their own evidence class, never as documentation:
  - BYOK at ₹1/min including telephony;
  - concurrency raised on request;
  - the per-minute prices quoted on the call.

## Snapshot of 7 Oct 2026 (`snapshots/2026-10-07/`)

The docs site was restructured after the first fetch. `llms.txt` now lists 252 pages, and the API reference is split into one page per endpoint. For example, `api-reference/get-call.md` moved to `api-reference/calls/get-call.md`; most old paths now return an empty page.

`snapshots/2026-10-07/` is a complete new fetch with its own `llms.txt` and `MANIFEST.json` (252 of 252 pages, 0 failures). The pages under `pages/` are unchanged, so existing line citations into them stay valid as a record of what the docs said on 6 Oct 2026. **Cite the snapshot for anything current**: `thinnest-findings/mirror/snapshots/2026-10-07/pages/<path>.md:<line>`.

Facts that are new in the snapshot, or that it changes:
- **BYOK** has a full API (`api-reference/bring-your-own-keys/*`) and per-agent BYOK model and voice (`agents/set-agent-byok-*`). Every BYOK endpoint takes `Thinnest-Workspace`. It is still all three keys or none (`agents/set-agent-byok-voice.md:155-157`).
- **Customers** (`api-reference/customers*`, `guides/build-a-platform.md`) are isolated workspaces per end customer, addressed with the `Thinnest-Workspace` header. One `includeCustomers` webhook covers all of them, with `data.workspaceId` in the signed body.
- **Webhooks:** deliveries are `{event, sentAt, data}`, so a signed send time is in the body (`webhooks/create-webhook.md:162`).
- **Call log:** `GET` usage call log carries `costMicro`, the amount actually charged per call (`usage/list-call-log.md:533-540`).
- **Phone numbers:** they can be rented, imported and released through the API, and carrier accounts can be saved for `plivo`, `vobiz`, `twilio` and `telnyx` (`phone-numbers/*`).

**One deliberate edit in the snapshot.** In `snapshots/2026-10-07/pages/api-reference/phone-numbers/save-carrier-account.md`, the vendor's example Twilio account id (an `example:` value, lines 278 and 380) is replaced with `ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`, at the same byte length. GitHub push protection reads any value of that shape as a credential and refuses the push. `MANIFEST.json` carries the hash of the edited file. Every other byte is as fetched.

## Snapshot of 7 Oct 2026, evening (`snapshots/2026-10-07b/`)

This is a full re-fetch after ThinnestAI's founder answered our questions: 268 of 268 pages, 0 failures, with its own `llms.txt` and `MANIFEST.json`. New pages since `2026-10-07/`:
- `agent/after-the-call`;
- `api-reference/do-not-call/*`;
- `api-reference/sms/*`;
- `api-reference/webhooks/redeliver-webhook-events`;
- `channels/sms`;
- `guides/text-the-caller`.

Example account ids of the form `AC` + 32 hex were masked at fetch time (one file), for the push-protection reason above, and the manifest hashes are of the masked files. Cite this snapshot for anything current. What it confirms and contradicts in the founder's email is in `docs/evidence/thinnest-ai-evaluation.md` §10.
