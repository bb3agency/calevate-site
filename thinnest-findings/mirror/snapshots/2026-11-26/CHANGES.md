# ThinnestAI docs: 2026-11-12 → 2026-11-26

Fetched 26 Nov 2026, 11:33:45–11:37:21 UTC (`MANIFEST.json`). 296 of 296 pages in `llms.txt`, every one HTTP 200 `text/markdown`, 0 failures; also `llms-full.txt` and `https://app.thinnest.ai/openapi.json`. The example `AC` + 32 hex account id is masked at the same byte length in `pages/api-reference/phone-numbers/save-carrier-account.md` (lines 480, 584) and `openapi.json` (2 occurrences); manifest hashes are of the masked files, with `sha256_as_fetched` for the unmasked ones.

Paths: `old` = `snapshots/2026-11-12/`, `new` = `snapshots/2026-11-26/`.

## Summary

- **Pages added: 1** (`channels/instagram`). **Pages removed: 0.** **Pages differing by bytes: 10 of 295.**
- `llms.txt` gains the Instagram line (new `llms.txt:27`) and the What's New blurb now runs "October 6 to November 14, 2026" (new `llms.txt:298`).
- **`openapi.json` is unchanged**: the masked spec hashes the same as on 12 Nov (`1ed8317e…5924`); only the vendor's example account id, which is masked, differs. No `api-reference/*` page changed, so no endpoint, agent field, webhook, error code or price in the API changed.
- `llms-full.txt` differs (it concatenates the pages, so it carries the changes below).

## Substantive changes, by page

### whats-new/index.md
- New entry **Nov 14** (new `13-27`): Studio voices on every plan including the free trial, only cloning needs Pro (new `19-20`); one Studio catalogue in every market, every Studio voice speaks all 63 Studio languages, no samples, and "An agent whose Studio voice is no longer listed answers in a voice of the same gender until you choose a new one" (new `21-24`); clone languages are the languages Studio speaks on a call (new `25`); Browse voices layout (new `26`).
- A link in an older entry now points to `#studio-voices-and-languages` (old `106`, new `121`).

### channels/voice.md
- Studio is on **every plan** (old `255-257`, `269-274` → new `255-257`, `269-270`). Before, putting a Studio voice on an agent needed Pro or above.
- "Voices for more languages" (old `282-297`) is replaced by **Studio voices and languages** (new `278-293`). The old fifteen-language Studio catalogue for non-India billing, with a same-gender "second set" swapped in on a call for other languages, is gone. Now every Studio voice speaks all 63 Studio languages (new `280-282`). Choosing a language lists its native voices first, Indian-accented ones for an Indian language (new `284-286`).
- **Studio voices have no sample**: use Test a call (new `236-237`, `287-288`).
- **Migration:** an agent whose Studio voice chosen before 14 Nov is no longer listed answers in a same-gender Studio voice until a new one is chosen; cloned voices were moved over (new `289-291`).
- Not changed but inconsistent: the note "Standard voices were retired on 23 October 2026" (new `265-267`) sits beside the three-tier text with a Standard tier (new `241`), as on 12 Nov.

### channels/voice-clone.md
- Clone languages are the languages Studio speaks, in every market. Languages Studio cannot speak on a call (Assamese, Konkani, Maithili, Nepali, Odia, Sindhi, Sinhala, Cantonese) are no longer offered: "a clone in one of them was answering calls in English" (old `91-95` → new `91-94`).

### workspace/regions.md
- Voice filter drops "category" and "listen"; Studio voices have no sample (old `48-49` → new `48-49`).

### channels/instagram.md (new), channels/overview.md, workspace/usage.md
- A fifth channel: Instagram DMs and comments into the Inbox, Meta login, no campaigns outside the 24-hour window (`channels/instagram.md`; `channels/overview.md:9`, `:16`, `:46-48`). No per-message fee; replies count in Replies (`workspace/usage.md:52-62`).

### whatsapp/broadcasts.md
- **Uploading a list for this broadcast** (new `126-152`): CSV upload in the broadcast itself, a required consent tick, contacts added with consent and date, opted-out people left out.

### white-label/brand-and-domains.md, white-label/clients.md, white-label/prices.md
- White label (a product we do not use): favicon and custom CSS, a branded `/docs` site per domain (`brand-and-domains.md`); per-client prices (`clients.md:71-91`); an optional per-plan call markup (`prices.md:149-156`).

## Not changed (byte-identical, old = new)
Every `api-reference/*` page (agents, BYOK, voices, calls, webhooks, errors, workflows), `openapi.json` (masked), `agent/*` (behaviour, workflows, insights, escalation), `guides/*` (multilingual, how-your-agent-sounds), `channels/phone-numbers.md`, `channels/calling-rules.md`, `channels/voice-campaigns.md`. No change to turn detection (`turnDetection`, `timer_v2`), `reaskAfterSeconds`, Ear and backchannel fields, `earlyAnswers`, `openingWaitsForCaller`, `languages`, prompt guidance, workflows, the default model or voice, BYOK, webhooks or pricing in the API.
