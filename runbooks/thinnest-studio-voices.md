# Studio voices on ThinnestAI: turning them on, and moving off the developer-workspace switch

D-717 (founder, 10 Oct 2026). Studio is Cartesia on OUR key through ThinnestAI's voice-only
BYOK (`scope: "voice"`). Our key is switched on ONLY in the customer workspace of a client that
uses Studio; our developer workspace HOLDS the key with its own-keys switch OFF, so no client
inherits it. Vendor basis: "A customer can bring a complete set of its own for that choice
(three keys, or a voice key), which then overrides yours … A customer with its own complete set
and its own switch on keeps using its own" (`thinnest-findings/mirror/snapshots/2026-10-08/
pages/api-reference/bring-your-own-keys.md:132-133`, re-read live 10 Oct 2026). That this works
while OUR switch is off is stated, not proved: OPERATIONS gate T-27.

Everything below is done from the admin console, Voices page, "Studio voices" card. No
ThinnestAI console change is needed and none should be made: a change there is what the hourly
check alarms on.

## 1. Before Studio can be sold (founder)

1. Save the Cartesia API key in the ops console Secrets panel (`cartesia_api_key`). Test it
   there first.
2. Attest the `byok_voice` per-minute rate (ops console, Per-minute rates; VENDOR-STATED
   ₹1.50/min, `bring-your-own-keys.md:21`).
3. Attest the Cartesia TTS price (ops console). A Studio minute carries Cartesia's synthesis as
   a second cost, so a Studio voice is refused until it is attested (hard rule 7).

The card's "missing" list says which of these are still open.

## 2. Turn Studio on

1. Press **Studio ready** (step-up). Leave the client field empty the first time: it installs
   our key in the developer workspace and leaves its own-keys switch OFF. Check the card:
   "Held in our developer workspace: Yes · own keys off".
2. Studio voices can only be listed from a workspace that runs on its own keys
   (`bring-your-own-keys/list-byok-voices.md:7` answers `409` otherwise). So press **Studio
   ready** again naming the first client that will use Studio (its account id, from the admin
   tenant page). Its own workspace must be active. In that workspace, in this order: every
   published Clear agent is set `byok: off` and read back (nothing is switched on if one is
   not), our key is installed, voice-only BYOK is switched on, and `GET /byok` is read back.
   The client appears under "Client workspaces on Studio".
3. Press **Refresh** on the Voices page. The Cartesia voices are listed under "Every voice on
   the platform". Store a preview for each one you will offer, then add and enable them.
4. The card now reads **Ready**. Every other client is switched on automatically at its first
   Studio publish. If that fails, the client sees "Studio voices could not be set up for this
   account" and the client's last error code appears on the card.

Trial accounts live in our developer workspace (D-697), so their agents are Clear only. They
can still play Studio previews; the picker tells them Studio is available once they go live.

## 3. Moving off the old developer-workspace switch (production, if "Enable Studio voices" was ever run)

Before D-717, "Enable Studio voices" switched voice-only BYOK ON in our developer workspace and
every client workspace inherited it. The card shows this as "own keys on" with a warning, and
the hourly check raises `studio_developer_switch_on`. Do NOT switch the developer workspace off
first: every Studio agent still inheriting our key would stop speaking its voice, with no
fallback (`bring-your-own-keys.md:122-127`).

1. Read the card: "Published Studio agents" and "Client workspaces on Studio".
2. Republish every published Studio agent (each client's agent page, "Put it live"). Each
   publish switches Studio on in that client's own workspace with its own key and records it.
   An agent still living in the developer workspace (made before D-693) is recreated in its
   client's workspace by that same publish.
3. Press **Switch developer workspace off**. It is refused with `studio_clients_not_moved`
   while any published Studio agent lives in the developer workspace or in a client workspace
   not on its own key, and the sentence says which. Fix those and press it again.
4. Check: the card reads "own keys off"; each Studio client's `GET /byok` (with its
   `Thinnest-Workspace` header) still reads `enabled: true`, `scope: "voice"`, `using: "own"`;
   one Studio test call per client speaks Cartesia at the voice-only rate (gates T-15, T-27).

## 4. Alarms

- `studio_workspace_repaired` (attention): the hourly check found a Studio client workspace
  off our key and switched it back on, Clear agents confirmed off first. Find out who changed
  it.
- `studio_workspace_drift` (page): it could not switch it back on. The card shows the client's
  last error code: `engine_voice_key_rejected` is the Cartesia key (test and save it again);
  `studio_agents_not_kept_off` is a Clear agent that would not stay off (republish it); a
  dependency code is ThinnestAI unreachable (the next hourly run retries; or press Studio ready
  naming the client).
- `studio_voice_key_push_failed` (page): a rotated key did not reach our developer workspace
  or one client workspace (`tenant_id` names it). Save the key again to retry every push.
- `studio_developer_switch_on` (attention): §3.

## 5. A client that stops using Studio

Nothing is switched off. Its workspace keeps our key with BYOK on, and every Clear agent is
`byok: off` on every publish and repaired by the drift sweep, so nothing follows it and it
costs nothing; the next Studio publish needs no setup.
