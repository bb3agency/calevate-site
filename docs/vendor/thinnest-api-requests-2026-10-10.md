# ThinnestAI: API requests and documentation questions (draft, 10 Oct 2026)

Draft for the founder to send to ThinnestAI. Nothing here is sent automatically, and no
secret, key or workspace id is included.

Context for our team: the agent Voice settings page in ThinnestAI's console has settings
that the REST API does not expose (mapping in
`docs/evidence/first-call-review-2026-10-10.md`, "Mapping result"). Until there is an API
field, Calevate cannot set them per agent or check them for drift, so every agent runs on
ThinnestAI's defaults for them (founder decision 16, 10 Oct 2026). Sources read on 10 Oct
2026: docs.thinnest.ai `api-reference/agents/update-agent`, `api-reference/agents/get-agent`,
`channels/voice`, `agent/behaviour`, and the 8 Oct snapshot of `guides/how-your-agent-sounds`.

---

**Subject:** API fields for agent Voice settings, per-customer voice BYOK, and a few open questions

Hi team,

We build and manage voice agents for our clients entirely through your REST API, one
customer workspace per client. Several settings on the agent's Voice page in your console
have no field on Create / Update / Get Agent, so we cannot set them per agent or confirm
they stay as set. Could you add them to `AgentVoiceInput` and the agent's `voice` object
(read and write), and tell us each one's default and allowed range?

1. **Filler lines while the agent is thinking.** The list of lines (up to 8, per language,
   under 60 characters each), whether an empty list means your default fillers, and the two
   timings: the quiet before a filler is spoken (console default 900 ms, 200-5000) and the
   gap between fillers or during a tool call (console default 2500 ms, 1000-10000). Also the
   option that removes the wait and always fills.
2. **Turn-taking.** End-of-turn silence (console default 0.25 s, 0.2-3 s) and the number of
   words a caller must say to interrupt the agent (console default 3, 1-6).
3. **Never interruptible**, so a disclosure, a compliance readout or a price is always heard
   to the end. Is it per agent only, or can it apply to one line or one step?
4. **Keep words spoken over the agent** and answer them.
5. **Let the greeting finish** on phone lines.
6. **Background ambience**: on/off and which sound.
7. **Hang up when finished**: release the line when the agent is done.
8. **Silence and ending**: the "are you still there?" prompt after N seconds (or never),
   hanging up after a silence of N seconds, and the phrases that end the call ("bye, that's
   all, thank you goodbye"), with their languages.
9. **The call-only "how it should speak" box.** How does it combine with the agent's
   `instructions`: is it appended to them, sent separately, and does it count toward the
   instructions limit? Which wins if they conflict?
10. **Where the agent answers.** `voice.surfaces` is read-only on the API. We offer our
    clients phone calls only, so we need to switch the website call button and WhatsApp calls
    off (and keep them off) per agent through the API.

Two places where your documentation disagrees with itself, so we do not know which to build
against:

11. **Studio voices: Pro or Scale?** Update Agent says "A Studio voice needs the Pro plan or
    above", and the Voice channel page says putting a Studio voice on an agent "needs the Pro
    plan or above". The "How your agent sounds" guide says "Studio is gated below Scale" and
    puts the Studio catalogue "on the Scale plan and above". Which plan is required to put a
    Studio voice on an agent today?
12. **Instructions limit: 8,000 or 20,000 characters?** Update Agent declares
    `instructions` with `maxLength: 20000`, while the console's instructions box counts to
    8,000 (we saw "8249/8000" on 10 Oct). Which limit does the API enforce, does an agent
    saved through the API with more than 8,000 characters behave differently from one saved
    in the console, and do the agent's `steps` count toward either limit?

And one capability question:

13. **Reporting the current step.** When we run a test chat or a test call against an agent
    with `steps`, can the response (or the call's record) tell us which step the
    conversation is in after each turn? We would use it to show our clients where a test
    conversation went off script.

Our own voice key, set per client workspace. We keep BYOK switched OFF in our developer
workspace and want to switch voice-only BYOK on only in the customer workspaces of clients
who choose our premium voices:

14. **A customer's own voice key while ours is off.** If our developer workspace has BYOK
    off, and we `PUT /byok/credentials` (kind `tts`, Cartesia) and `PATCH /byok
    {"enabled": true, "scope": "voice"}` with a customer's `Thinnest-Workspace` header, does
    that customer run on voice-only BYOK on its own (`GET /byok` → `using: "own"`), with
    every other customer unaffected? Does an agent there with `byok: "off"` stay on your
    voices at your rate?
15. **Listing voices with the switch off.** Can our developer workspace hold a checked
    Cartesia key with BYOK switched off and still answer `GET /byok/voices` and
    `POST /byok/voices/preview`? We use them to build the voice catalogue our clients pick
    from.
16. **Billing.** Is a voice-only BYOK minute in a customer workspace charged at ₹1.50 to our
    developer wallet, with `costMicro` on the call at that rate? Is the top-up fee the same?
17. **Keys per workspace.** May the same Cartesia key be installed in several customer
    workspaces, and is there any limit on how many?

Costs we cannot find in your docs:

18. **Test chat.** What does one reply of `POST /agents/{id}/test-chat` cost for an agent on
    your own models (not BYOK)? Is it billed like a website chat reply?
19. **Model ids and prices.** Could `GET /models` return each model's per-minute price
    band (for example GPT-5 Mini's premium surcharge) and its typical latency, as the
    console shows? We need GPT-OSS 120B's id and whether it carries any surcharge.

Open items from our earlier emails:

20. **Training off in writing.** Please confirm in writing that model training on our data
    is switched off for our developer workspace and every customer workspace, and that the
    copies already made are deleted, as offered for pay-as-you-go.
21. **Forwarded calls.** Could we schedule the test calls you offered, to confirm the caller
    ID that Airtel, Jio, Vi and BSNL pass on forwarded calls?

Two things we have built against your live docs, for you to confirm:

- **Caller lookup (`voice.callStartUrl`).** We set it to our own per-agent https endpoint,
  store the `callStartSecret` returned on that response, verify `x-thinnest-signature-v2`
  over `<x-thinnest-delivered-at>.<body>` with a five-minute window, and answer within
  0.8 s. Please confirm the secret is returned on the response to a `PATCH` that sets a new
  address on an existing agent (not only on create), and that `callStartSecret: "rotate"`
  with the unchanged address returns the new secret the same way.
- **`voice.ringSeconds`.** We send 30 on every agent and read it back. Please confirm it is
  live on every plan and applies to calls placed by campaigns and call backs as well as by
  Place Call.

Thanks,
[founder name]
Calevate
