# Studio voices on ThinnestAI: turning them on, and keeping them on

D-727 (founder, 11 Oct 2026), over D-717 (10 Oct 2026). Studio is Cartesia on OUR key through
ThinnestAI's voice-only BYOK (`scope: "voice"`). Our key is switched on in two kinds of place:

- **our developer workspace**, where free-trial agents live (D-697), so a trial account can
  publish and test-call a Studio voice (D-727);
- **the customer workspace of each paying client that uses Studio** (D-717), switched on
  automatically at its first Studio publish.

Vendor basis (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
bring-your-own-keys.md`): with BYOK on, an agent whose `byok` is `"off"` never uses our keys and
bills at ThinnestAI's rate, and one on `"workspace"` uses our key (:69-79); `"workspace"` is
the agent default (:304-306); customer workspaces inherit our keys while our switch is on
(:128-133). So every agent we publish states `byok` (the adapter refuses one that does not,
alarm `engine_agent_byok_unstated`), and before any switch goes on every published agent that
is not on a Studio voice and would follow it is set `off` and read back.

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
4. Check `trial_studio_minutes` (ops console, Calling limits, trial; default 15): the Studio
   minutes one free-trial account may use on test calls before its Studio test calls are
   refused. Clear test calls are unaffected.

The card's "missing" list says which of these are still open.

## 2. Turn Studio on

1. Press **Studio ready** (step-up). In our developer workspace, in this order: every published
   agent that is not on a Studio voice and would follow the switch (the developer workspace's
   own, and those in client workspaces with no key of their own) is set `byok: off` and read
   back, and nothing is switched on if one is not; our key is installed; voice-only BYOK is
   switched on; `GET /byok` is read back. The card reads "Held in our developer workspace: Yes
   · switched on".
2. Press **Refresh** on the Voices page. The Cartesia voices are listed (from the developer
   workspace) under "Every voice on the platform". Store a preview for each one you will
   offer, then add and enable them. A voice cloned from a real person (the founder's own
   Instant clone, D-721): open it, switch on "A cloned voice of a real person", record the
   speaker's consent (name, date, statement, signed copy if there is one), give it the name
   clients will see, then switch it on. It cannot be offered before both are done. If it is
   not in the list, use "Find a voice by its id" in Add voices.
3. The card now reads **Ready**. Trial agents publish Studio voices in the developer workspace
   with `byok: "workspace"`. Every paying client is switched on in its own workspace at its
   first Studio publish; to do it ahead of time, press **Studio ready** naming the client (its
   account id, from the admin tenant page). If a client's switch-on fails, the client sees
   "Studio voices could not be set up for this account" and its last error code appears on
   the card.

## 3. A trial account on Studio

A trial agent on a Studio voice publishes only while the developer workspace answers ready
(read live at every publish; a trial publish never switches it on). Its test calls are metered
like any Studio minute: the `byok_voice` rate with the wallet top-up fee, plus Cartesia's
synthesis on our key. Once the account's Studio minutes on test calls reach
`trial_studio_minutes`, a Studio test call is refused before dialling
(`trial_studio_minutes_used`: "Switch this agent to a Clear voice, or add credit to keep using
Studio"). The count is read under the platform's trial-line lock, so two test calls cannot both
pass it.

## 4. Alarms

- `studio_developer_repaired` (attention): the hourly check found our developer workspace off
  our key and switched it back on, other agents confirmed off first. Find out who changed it.
- `studio_developer_drift` (attention): it could not switch it back on, so trial agents on a
  Studio voice do not speak it. The reason code is in the alarm; press Studio ready.
- `studio_workspace_repaired` (attention): the same for a paying Studio client's workspace.
- `studio_workspace_drift` (page): it could not switch a client workspace back on. The card
  shows the client's last error code: `engine_voice_key_rejected` is the Cartesia key (test
  and save it again); `studio_agents_not_kept_off` is an agent that would not stay off
  (republish it); a dependency code is ThinnestAI unreachable (the next hourly run retries;
  or press Studio ready naming the client).
- `studio_voice_key_push_failed` (page): a rotated key did not reach our developer workspace
  or one client workspace (`tenant_id` names it). Save the key again to retry every push.
- `engine_agent_byok_unstated` (attention): an agent config reached the adapter without a
  `byok` value and was refused before it was sent.

## 5. A client that stops using Studio

Nothing is switched off. Its workspace keeps our key with BYOK on, and every Clear agent is
`byok: off` on every publish and repaired by the drift sweep, so nothing follows it and it
costs nothing; the next Studio publish needs no setup.
