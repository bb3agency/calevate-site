# ThinnestAI: API requests and documentation questions (draft, 10 Oct 2026)

Sent by the founder on 10 Oct 2026, followed by a second email the same evening that
corrected item 10 (we want `voice.surfaces` writable, not forced off, because website and
WhatsApp answering is a planned feature), withdrew item 15, and added: when a `PATCH` takes
effect during a call in progress (OPERATIONS T-28), test-chat action markers, owned Cartesia
clones (item 22) and the forwarded-call test calls. No secret, key or workspace id is
included.

On 11 Oct 2026 ThinnestAI answered the separate 9 Oct email (summary in rememory, "ThinnestAI
reply 11 Oct 2026") and said this email needs another day. The founder replied the same day
asking the four points that reply left open: whether forwarding works with the agent off,
fixed IPs for action requests, Pro limits and raising the customer cap above 5, and the signed
DPA with the sub-processor list, plus training off in writing.

**Queued for a separate email, to send only after ThinnestAI replies to the current one**
(founder, 11 Oct 2026). All three come from a production call on 11 Oct:

1. **A time line spoken aloud.** The agent read out "[It is 11:03 am now.]". Our instructions
   contain no such line. Where is it added, can it be turned off, and does your pipeline strip
   bracketed or stage-direction text (for example "(Waiting for your reply.)") before speech?
2. **Turns the caller talked over.** When a caller interrupts, the transcript keeps the agent's
   whole generated reply. Can an interrupted turn be marked, and trimmed to what was actually
   spoken, in the transcript, in `call.analysed`, and in the model's own context for the rest
   of the call?
3. **Interrupted speech on our own voice key.** On voice-only BYOK, is a sentence that was cut
   off still synthesised in full and charged to our Cartesia account, and how far ahead of
   playback do you send text to the voice provider?
4. **Pronunciation dictionary.** Cartesia applies a pronunciation dictionary per speech
   request (`pronunciation_dict_id`, docs.cartesia.ai custom pronunciations). On voice-only
   BYOK with Cartesia, can an agent carry a dictionary id that you pass on every speech
   request, so brand, product and place names are said correctly? Is there anything similar
   for your own voices?
5. **Custom actions inside Test Chat** (from a test chat of 11 Oct 2026, D-748). When an
   agent uses one of our custom actions during `POST /agents/{id}/test-chat`: (a) is an
   `X-Call-Id` header sent, and if so, what id does it carry when there is no call?
   (b) What exactly is `tools[].output` for a custom action: our response body as parsed
   JSON, as a string, or wrapped or shortened? (c) Is there any field or header that tells
   our endpoint the request comes from a test chat rather than a real conversation? And
   (d) with the agent's language set to Match the customer, does test chat detect the
   language from the customer's message the same way a call does? A Telugu message got an
   English reply.
6. **Notes in brackets after an interruption** (production call of 11 Oct 2026, 15:33 IST,
   D-749). Agent turns in the transcript contained "[cut off before finishing]",
   "[awaiting response]", "(Waiting for user response)", "[hang_up]" and "[call hang_up]".
   Our instructions contain none of these. (a) Does your pipeline insert any of them into the
   transcript, into the model's context for the rest of the call, or both? (b) Which of them
   are yours, and which would be the model's own text? (c) Is any of it ever sent to speech?
7. **Re-generation after the caller talks over the agent.** In the same call, one agent turn
   held the same question three times glued together without spaces ("…ఎంత కావాలి?మీకు
   powder ఎంత కావాలి?[cut off before finishing]మీకు powder ఎంత కావాలి?"), and another held
   one proposal said twice. When a caller interrupts, is the model run again with its earlier
   partial reply appended to its context, and is the transcript turn the concatenation of
   several generations? If so, can the interrupted part be dropped from the context, or kept
   only as what was actually heard?
8. **How the agent ends a call.** When the agent decides the conversation is over, does the
   model call a tool or write text? Is "[hang_up]" in a transcript your record of that, or the
   model writing it? Your docs now say a new agent starts with `voice.endCallOnFinish` off
   (docs.thinnest.ai `api-reference/agents/update-agent`, read 11 Oct 2026; the 8 Oct
   snapshot said it was on for every agent): with it off, after the agent "ends" the
   conversation, does it keep answering the caller? In our call it said goodbye four times
   and kept answering. We now send `endCallOnFinish: true` on every agent.
9. **The built-in call rules.** `voice.callInstructions` "REPLACES the built-in call rules
   and is added after the agent's instructions in the call prompt" (same page). What do the
   built-in rules say (we need to know whether anything in them conflicts with ours: how to
   end a call, interruptions, the current time), and do they count towards the 8,000
   characters of `instructions`?
10. **Advance notice of automated calls on numbers you rent (TCCCPR reg. 4).** TRAI's
    regulation 4, as substituted on 12 Feb 2025, says every Sender "shall notify the
    Originating Access Provider, in advance, about the use of Auto Dialer or Robo-Calls as
    well as the intended objective of such calls in writing", and the Third Amendment
    (18 Sep 2026) makes undeclared A2P calls, artificial voice included, count as UCC. Our
    clients' numbers are rented through your API in each client's own customer workspace,
    in the client's business name. (a) Which licensed access provider (telecom operator)
    issues and originates those numbers? (b) Is that operator, or you on its behalf, the
    "Originating Access Provider" for our clients' calls? (c) How should a client give the
    notice: to you, through an endpoint or form we can call per customer workspace, or to
    the operator directly, and at what address? (d) What acknowledgement or reference comes
    back, so we can keep it as evidence? (e) Do you already declare A2P use, and the
    numbers, to the operator for calls placed by your agents, and if so per workspace or
    for your whole account? (f) Once the Third Amendment's A2P provisions take effect, will
    the declaration be recorded on the DLT platform, and by whom?

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

22. **Our own cloned voices.** Set Agent BYOK Voice checks the id "against the provider's
    list for your key". Does `GET /byok/voices` return every page of Cartesia's list
    (Cartesia pages at most 100 per page), including voices our Cartesia account owns, such
    as an instant clone we made there? Can you confirm an owned clone is accepted by
    `PUT /agents/{id}/byok-voice`?

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
23. **Reasoning text spoken on calls.** On a call of 11 Oct 2026 an agent on GPT-OSS 120B
    spoke "We should end? Caller may ask more." followed by three different goodbyes, then
    hung up before the caller said goodbye. Is the model's reasoning removed before the voice
    reads the reply, for GPT-OSS 120B and GPT-5 Nano? Do Prana and Prana [Voice] reason
    before replying, and can reasoning be switched off per agent?
24. **Own-key voice settings over the API.** Your console shows speed, volume, emotion and
    model for an own-key voice. Can we set these through the API, do they survive a
    `PATCH` of the agent, and can emotion change per sentence during a call?
25. **Time to the first word.** On outbound test calls of 11 Oct 2026 the opening line
    started 2 to 3 seconds after pickup. What makes up that
    time, does the greeting wait for our `voice.callStartUrl` answer, and what can we
    change to shorten it?
26. **Gemini.** Will you host Gemini 2.5 Flash or Flash-Lite as a call-capable model, or offer
    a scope of our own voice and our own model with your speech recognition? Under scope `all`
    with a `google` key, which Gemini ids pass your check for calls, and do you send
    `thinkingBudget: 0` on calls?
27. **Allowed models with our own voice.** Is GPT-5.4 Nano `voiceOnlyByok` (your console lists
    it, your docs do not)? What is GPT-OSS 120B's model id? Under scope `voice`, does an agent
    set to a model that is not allowed run its calls on Prana or on GPT-OSS 120B? Your pages say
    both.
28. **Reply settings on calls.** Do `temperature` and `maxReplyTokens` apply on calls, including
    for reasoning models?
29. **End of turn.** Can the Smart / Timer / Ear end-of-turn mode be set through the API, what is
    its default, and how does it combine with `turnSilenceSeconds`?
30. **Built-in do-not-call.** Can it be narrowed per agent, or report the words that triggered it?
    Today `contact.opted_out` gives us no phrase. On one of our test calls it fired on "cut the
    call" in Telugu.
31. **Speech recognition for Telugu.** Which recogniser runs for `te-IN`, do you have accuracy
    figures, and can it be chosen per agent without bringing all three keys?
32. **Price with our own voice.** Does `callPricePerMinuteMicro` mean a `voiceOnlyByok` model can
    cost more than ₹1.50/min under scope `voice`, or is that rate flat?
33. **Prana.** Do Prana and Prana [Voice] reason before replying, and how do they score on Telugu?

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
