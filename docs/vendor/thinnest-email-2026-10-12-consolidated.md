# Email to Ashutosh (ThinnestAI), consolidated, draft of 12 Oct 2026

Sent by the founder on 12 Oct 2026. It replaces every question still open from
the 9, 10 and 11 Oct emails (list in `thinnest-replies-2026-10-12.md` §5) and adds the request
for Cartesia speed, volume and emotion controls. Cartesia facts are VENDOR-PUBLISHED
(docs.cartesia.ai capability guides "volume-speed-emotion", "clone-voices", "ssml-tags", read
11 Oct 2026). No key, secret, workspace id, phone number or margin is included, and no other
telephony provider is named.

---

**Subject:** Everything still open from our side, in one email

Hi Ashutosh,

Thank you for the detailed answers and for building so much so quickly. The 20,000-character
instructions, the voice settings on the API, the test-chat header and own-clone support all
help us directly, and we are building against them now.

To make this easier for you, this email collects everything we still need, from all our earlier
emails, so you can answer from this one alone and set the older ones aside. For each item I have
described what we saw on our calls, so the problem is clear. They are in order of importance
to us.

**1. Gemini 3.1 Flash-Lite with our voice and your speech recognition at ₹1/minute**

Thank you for the offer; we would like to take it up. Our first client's agent speaks Telugu,
mixed with English, and the model has been our biggest problem on test calls. GPT-OSS 120B spoke
its thinking at the end of a call ("We should end? Caller may ask more.") followed by three
goodbyes and hung up early, and GPT-5 Nano produced unnatural Telugu and read out its own
instructions. We will also test Prana [Voice] as you suggest.

To set it up:
1. How is it switched on through the API: which BYOK scope value, which key kind for the Google
   key, and is it per customer workspace like scope "voice"?
2. Is the ₹1/minute the same on pay-as-you-go, Pro and Scale, with only the 2.36% gateway
   charge on top-ups?
3. Google says Gemini 3 Flash-Lite cannot switch thinking fully off, and that "minimal" may still
   reason a little. Which thinking level do you send on calls, and could the thinking ever reach
   the voice (do you set includeThoughts)?
4. If our Google key is refused or rate-limited mid-call, what does the caller hear, and do we get
   a call.problem webhook (byok_failed)?
5. Do the per-agent model choice (PUT /agents/{id}/byok-model), temperature and maxReplyTokens
   work in this set-up, and does temperature apply on calls generally?
6. Since we pay Google directly in this set-up, could we also choose gemini-2.5-flash-lite on our
   own key? Google's deprecations page (updated 9 Oct) shows no shutdown date for it, and it can
   switch thinking fully off. We understand the caching cost would be ours.
7. Would the same be possible with your voices instead of ours (your speech recognition, your
   voice, our Gemini key), and at what price?

**2. Our voice's speed, volume and emotion through the API**

Our agents speak with our own Cartesia voices. On our calls the voice sounded quiet and a little
fast, and we have no way to change that per agent through your API. Your console already shows
speed, volume, emotion and model for an own-key voice, and Cartesia accepts these on every speech
request as generation_config (speed 0.6 to 1.5, volume 0.5 to 2.0, emotion from its list).
Could you:
1. Add speed, volume and emotion to the agent (for example on the byok-voice setting or the voice
   object), readable and writable through the API, and pass them to Cartesia on every speech
   request of every call?
2. Let us choose the Cartesia model (for example sonic-3.6) per agent, not only per workspace?
3. Pass a Cartesia pronunciation dictionary id (pronunciation_dict_id) on every request, set per
   agent, so brand, product and place names are said correctly? Is there anything similar for your
   own voices?
4. Confirm these settings survive a PATCH of the agent that does not mention them.

Cartesia notes that emotion currently works only for English and that speed does not apply to
Professional Voice Clones, so we would use emotion where it works and volume and speed everywhere.

**3. Time to the first word**

On outbound test calls the opening line started 2 to 3 seconds after the person picked up. Part
of that was voicemail detection, which we have switched off. What else makes up that time, and
what can we change on our side to shorten it?

**4. Turn-taking**

1. Can the Smart / Timer / Ear end-of-turn mode be set through the API? What is its default, and
   how does it combine with turnSilenceSeconds?
2. Which speech recogniser runs for Telugu (te-IN) on your models, do you have any accuracy
   figures for Telugu, and can it be chosen per agent without bringing all three keys?

**5. Text that is not speech**

1. One agent said "[It is 11:03 am now.]" on a call. Our instructions contain no such line. Where
   is it added, and can it be turned off?
2. Agent turns in one transcript contained "[cut off before finishing]", "[awaiting response]",
   "(Waiting for user response)", "[hang_up]" and "[call hang_up]". Which of these does your
   pipeline add, are they in the model's context for the rest of the call, and is any of it ever
   sent to the voice? Does your pipeline strip bracketed or stage-direction text before speech?

**6. Interruptions**

1. When a caller talks over the agent, the transcript keeps the agent's whole generated reply,
   including what was never heard. Can an interrupted turn be marked and trimmed to what was
   actually spoken, in the transcript, in call.analysed, and in the model's context for the rest
   of the call?
2. In one call a single agent turn held the same question three times glued together without
   spaces, and another call ended with several goodbyes glued the same way. Is the transcript turn
   several generations joined, after an interruption or when a turn re-runs on the backup model?
   Can the earlier part be dropped from the context, or kept only as what was heard?
3. With our own voice, is a sentence that was cut off still synthesised in full and charged to our
   Cartesia account, and how far ahead of playback do you send text to the voice?

**7. Ending calls and do-not-call**

1. When the agent decides the conversation is over, does the model call a tool or write text, and
   is "[hang_up]" in a transcript your record of that or the model's own words?
2. What do the built-in call rules say about ending a call, interruptions and the current time? We
   are considering callInstructions, and we need to know what we would be replacing.
3. On one test call a caller said, in Telugu, "okay, that's all, you can cut the call now, thank
   you", and the agent put the number on the do-not-call list. That caller never asked not to be
   called. Can the built-in do-not-call be narrowed per agent, and could contact.opted_out carry
   the words that triggered it, so our clients can see why a number was added?

**8. Models you host**

1. Do Prana and Prana [Voice] reason before replying, and have you measured them on Telugu?
2. Is GPT-5.4 Nano allowed with our own voice? Your console lists it and your docs do not.
3. With our own voice, does an agent set to a model that is not allowed run its calls on Prana or
   on GPT-OSS 120B? Your pages say both.

**9. Test chat**

1. What exactly is tools[].output for one of our custom actions: our response body as parsed
   JSON, as a string, or shortened?
2. With the language set to Match the customer, does test chat detect the language the way a call
   does? A Telugu message got an English reply.

**10. Automated-call notice (TRAI TCCCPR regulation 4)**

Regulation 4, as substituted on 12 Feb 2025, says every sender "shall notify the Originating
Access Provider, in advance, about the use of Auto Dialer or Robo-Calls as well as the intended
objective of such calls in writing". Our clients' numbers are rented through your API, in each
client's own customer workspace and business name.
1. Which licensed operator issues and originates those numbers?
2. Is that operator, or you on its behalf, the Originating Access Provider for our clients' calls?
3. How should a client give the notice: to you, through an endpoint or form we can call per
   workspace, or to the operator directly?
4. What acknowledgement comes back that we can keep as evidence?
5. Do you already declare automated calls, and the numbers, to the operator, per workspace or for
   your whole account?
6. Once the Third Amendment's A2P provisions take effect, who records the declaration on the DLT
   platform?

**11. Paperwork**

1. The signed DPA and your current sub-processor list, as you mentioned.
2. Written confirmation that model training on our data is off for our developer workspace and
   every customer workspace, including on pay-as-you-go, and that any copies already made are
   deleted.

Items 1 and 2 matter most to us. Happy to get on a call if that is quicker for any of these.

Thanks,
Umesh Chandra J
Calevate
