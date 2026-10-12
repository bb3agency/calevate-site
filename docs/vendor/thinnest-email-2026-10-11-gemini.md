# Email to Ashutosh (ThinnestAI), draft of 11 Oct 2026

Sent on 11 Oct 2026 and answered in part (`thinnest-replies-2026-10-12.md`); its open questions are carried into `thinnest-email-2026-10-12-consolidated.md`.

For the founder to send from the Calevate address. It carries the Gemini request and every
question not yet sent: the ten queued after the 11 Oct production calls and questions 23-33.
Questions already in the 10 Oct emails, still awaiting an answer, are left out. Evidence:
`docs/evidence/in-call-model-trials-2026-10-11.md`, `in-call-model-research-2026-10-11.md`,
`specimen-call-raghava-2026-10-11.md`. No key, secret, workspace id, phone number or margin is
included, and no other telephony provider is named.

---

**Subject:** Gemini on our own key, and what we learned from our first Telugu calls

Hi Ashutosh,

Thank you for the quick answers yesterday, and for confirming forwarding with the agent off,
the fixed IP and the Pro limits. No rush on the 10 Oct emails; I see the new `voice` fields in
your docs already cover most of them.

We have now run our first real Telugu test calls through your API, and they raised a few new
questions. None of these repeat the 10 Oct emails. The most important is the language model.

## 1. Gemini on our own key

Our agents speak Telugu first, often mixed with English. On our test calls, using the models
your platform allows while the agent speaks our own Cartesia voice:

- **GPT-OSS 120B** sounded the most natural and was quick, but at the end of one call it spoke
  its own reasoning aloud ("We should end? Caller may ask more.") and then three different
  goodbyes, and hung up before the caller had said goodbye.
- **GPT-4.1 Nano** was natural but weak at following an order flow.
- **GPT-5 Nano** produced unnatural Telugu, read out its own instructions, asked several
  questions in one turn and took about 1.5 seconds per reply.

From what we can find published, Gemini 2.5 Flash and Flash-Lite are the strongest small
models for Indian languages, can switch thinking fully off, and reach the first token quickly.
We would like to run our agents on Gemini through our own Google key while keeping your speech
recognition, and keeping either your voices or our Cartesia voice. Today the only way to bring
our own model is scope `all`, which also needs our own speech recognition, and we would rather
keep yours.

Could you enable these two arrangements, per customer workspace as scope `voice` is today?

- **A. Our model only:** your speech recognition and your voices, our Gemini key for the model.
- **B. Our model and our voice:** your speech recognition, our Gemini key, our Cartesia voice.

And for each:

1. What would the call minute cost, on pay-as-you-go and on Pro and Scale, and does the wallet
   top-up fee apply as it does now?
2. Which Gemini ids would pass your check for calls? We would use `gemini-2.5-flash` and
   `gemini-2.5-flash-lite`.
3. Would you send `thinkingBudget: 0` on calls, so no thinking time is added and no reasoning
   can reach the voice?
4. An agent's instructions, steps and tool definitions are re-read on every reply. Would you use
   Gemini's explicit context caching for them, or keep them as an unchanged prefix at the start
   of each request so Google's implicit caching applies? That cuts the model's cost to about a
   quarter.
5. If our Google key is refused mid-call, what happens: the reply fails as with scope `all`, or
   does it fall back to one of your models?
6. Would the per-agent model choice (`PUT /agents/{id}/byok-model`) and `temperature` /
   `maxReplyTokens` work the same way?

If you would rather host Gemini 2.5 Flash or Flash-Lite yourselves as call-capable models
allowed with our own voice, that would work for us too; please tell us the price.

## 2. The models you host today

7. Is the reasoning of GPT-OSS 120B and GPT-5 Nano removed before the voice reads the reply?
   The text we heard looked like the model's analysis channel. Can reasoning be turned off or
   down per agent?
8. Do Prana and Prana [Voice] reason before replying, and have you measured them on Telugu?
9. Is GPT-5.4 Nano allowed with our own voice (your console lists it, your docs do not)? With
   our own voice, does an agent set to a model that is not allowed run its calls on Prana or on
   GPT-OSS 120B? Your pages say both.
10. Do `temperature` and `maxReplyTokens` apply on calls, including for reasoning models?
11. Does `callPricePerMinuteMicro` mean one of the models allowed with our own voice can cost
    more than ₹1.50 a minute, or is that rate flat?

## 3. What the caller hears

12. **Time to the first word.** On outbound test calls the opening line started 2 to 3 seconds
    after pickup. Part of that was voicemail detection, which we have now switched off. What
    else makes up that time, and what can we change to shorten it?
13. **End of turn.** Can the Smart / Timer / Ear end-of-turn mode be set through the API, what is
    its default, and how does it combine with `turnSilenceSeconds`?
14. **Telugu speech recognition.** Which recogniser runs for `te-IN`, do you have accuracy
    figures, and can it be chosen per agent without bringing all three keys?
15. **Our voice's settings.** Your console shows speed, volume, emotion and model for our own
    Cartesia voice. Can we set these through the API, and do they survive a `PATCH` of the
    agent? The voice sounded quiet and fast on our calls.
16. **Pronunciation dictionary.** Cartesia applies a dictionary per speech request
    (`pronunciation_dict_id`). Could an agent carry a dictionary id that you pass on every
    request, so brand, product and place names are said correctly? Is there anything similar for
    your own voices?
17. **A time line spoken aloud.** One agent said "[It is 11:03 am now.]". Our instructions contain
    no such line. Where is it added, can it be turned off, and does your pipeline strip bracketed
    or stage-direction text before speech?
18. **Notes in brackets.** Agent turns in one transcript contained "[cut off before finishing]",
    "[awaiting response]", "(Waiting for user response)", "[hang_up]" and "[call hang_up]". Which
    of these does your pipeline add, are they in the model's context for the rest of the call,
    and is any of it ever spoken?

## 4. Interruptions

19. When a caller talks over the agent, the transcript keeps the agent's whole generated reply.
    Can an interrupted turn be marked and trimmed to what was actually spoken, in the transcript,
    in `call.analysed`, and in the model's context for the rest of the call?
20. In one call a single agent turn held the same question three times glued together without
    spaces, and another call ended with several goodbyes glued the same way. Is the transcript
    turn several generations joined: after an interruption, or when a turn re-runs on the backup
    model as you described? Can the earlier part be dropped from the context, or kept only as
    what was heard?
21. With our own voice, is a sentence that was cut off still synthesised in full and charged to
    our Cartesia account, and how far ahead of playback do you send text to the voice?

## 5. Ending calls and do-not-call

22. When the agent decides the conversation is over, does the model call a tool or write text,
    and is "[hang_up]" in a transcript your record of that or the model's own words? We send
    `endCallOnFinish: true` on every agent.
23. What do the built-in call rules say about ending a call, interruptions and the current
    time, and do they count towards the 8,000 characters of `instructions`?
24. **Built-in do-not-call.** On one test call a caller said, in Telugu, "okay, that's all, you
    can cut the call now, thank you", and the agent put the number on the do-not-call list. Can
    the built-in do-not-call be narrowed per agent, and could `contact.opted_out` carry the words
    that triggered it, so our clients can see why a number was added?

## 6. Test chat

25. Two additions to my test-chat question of 11 Oct: (a) what exactly is `tools[].output` for
    one of our custom actions: our response body as parsed JSON, as a string, or shortened? And
    (b) with the language set to Match the customer, does test chat detect the language the way
    a call does? A Telugu message got an English reply.

## 7. Automated-call notice (TRAI TCCCPR regulation 4)

26. Regulation 4, as substituted on 12 Feb 2025, says every sender "shall notify the Originating
    Access Provider, in advance, about the use of Auto Dialer or Robo-Calls as well as the
    intended objective of such calls in writing". Our clients' numbers are rented through your
    API in each client's own customer workspace and business name. (a) Which licensed operator
    issues and originates those numbers? (b) Is that operator, or you on its behalf, the
    Originating Access Provider for our clients' calls? (c) How should a client give the notice:
    to you, through an endpoint or form we can call per workspace, or to the operator directly?
    (d) What acknowledgement comes back that we can keep as evidence? (e) Do you already declare
    automated calls, and the numbers, to the operator, per workspace or for your whole account?
    (f) Once the Third Amendment's A2P provisions take effect, who records the declaration on the
    DLT platform?

The Gemini question matters most to us; the rest can come as you have answers. Happy to get on
a call if that is quicker.

Thanks,
Umesh Chandra J
Calevate
