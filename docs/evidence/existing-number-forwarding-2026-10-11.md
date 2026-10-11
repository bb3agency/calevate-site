# Keeping a client's existing phone number (forwarding, hand-off, outbound caller ID)

Research of 11 Oct 2026, written for the founder's question: a clinic has a widely published
mobile or landline number (+911234567890) and wants Calevate to answer it. Applies to every
business type, not only clinics.

Evidence classes follow hard rule 11. "Web, secondary" means a carrier guide, news report or
law-firm summary found by web search on 11 Oct 2026, not the carrier's or regulator's own text.

## 1. The answer in one table

| Number | Role |
|---|---|
| Existing number (published) | Unchanged for patients. Incoming calls forward to the client's Calevate number (all calls, or overflow only). Staff still call out, send SMS and use WhatsApp from it. |
| Client's Calevate number (rented in the client's business name after KYC) | Receives the forwarded calls. The AI's outbound calls (reminders, follow-ups) go out from it. A patient ringing it back reaches the same agent. |
| A staff phone the client already owns (receptionist's or owner's mobile) | Where the agent hands a caller to a person. Must not forward to Calevate. |

## 2. Linking the existing number: call forwarding

Porting is not available, so forwarding is the only route.

- **Mobile number portability** moves a number only between licensed mobile operators (Jio,
  Airtel, Vi, BSNL), never to a calling platform. Web, secondary.
- **Fixed-line portability does not exist in India yet.** TRAI recommended a numbering scheme
  that would enable it (PR 09/2025, Feb 2025); no source found says DoT has implemented it.
  Web, secondary.
- **ThinnestAI "bring your number"** imports only numbers held on our own Plivo, Vobiz,
  Twilio or Telnyx account (`docs/evidence/thinnest-ai-evaluation.md`, phone-numbers row).
  A SIM or a landline cannot be imported. VERIFIED-VENDOR-DOCS.

Forwarding is the clinic's carrier feature, set on the clinic's own phone. It needs no code
on our side.

| Mode | Airtel / Vi style code (web, secondary) | Effect |
|---|---|---|
| All calls | `**21*<number>#`, off `##21#` | Every incoming call goes to the AI; the phone never rings |
| No answer | `**61*<number>**<seconds>#`, off `##61#` | Staff get first chance; the AI takes what they miss (seconds in multiples of 5) |
| Busy | `**67*<number>#`, off `##67#` | The AI takes calls while the line is engaged |
| Unreachable | `**62*<number>#`, off `##62#` | The AI takes calls when the phone is off or has no signal |

Carrier differences:
- **Jio:** sources disagree. Some say the same codes as above; others give `*401*` (all),
  `*403*` (no answer), `*405*` (busy) and `*409*` (unreachable), with `*413` to stop all.
  Confirm in the MyJio app.
- **Vi:** "stop all" is reported as `##002#`.
- **BSNL and other landlines:** call divert exists, but the exact code was not confirmed.
  The client asks its provider to "enable call divert".
- **Office phone systems (EPABX, PRI) and virtual numbers** (Exotel, Knowlarity, MyOperator):
  the forward is set in that system.

**No default is imposed (founder, 11 Oct 2026, superseding the recommendation this line made):**
the client chooses. The guide leads with "set it once": the three conditional forwards (no answer
after the chosen 5-30 s, busy, unreachable) registered one time, so the phone rings first and
the agent takes missed, busy and switched-off calls; "all calls" is the other choice. No client is
told to dial codes daily (section 9 on why the conditional forwards survive an all-calls toggle).

**Cost to the client:** the forwarded leg is billed by the client's carrier as an outgoing call
from the client's plan. UNKNOWN whether Indian unlimited plans cover it; no source states the
charge. On our side, the forwarded call is billed by ThinnestAI as a normal inbound minute on
the Calevate number.

## 3. What still works on the existing number

Forwarding changes only incoming phone-network calls. These keep working:
- outgoing calls (the patient sees the existing number);
- SMS in and out;
- WhatsApp, including WhatsApp calls, which run over data, not the forwarded voice line;
- turning the forward off or changing its mode at any time.

With "all calls" on, a patient returning a staff call reaches the AI, which can help or hand
the caller to staff. The number never becomes unusable.

## 4. Many calls at once

- **Mobile with "all calls" forwarding:** each call is forwarded separately and the handset is
  never busy, so several callers can reach the AI together. No source states a carrier limit on
  simultaneous forwards; a 3GPP document limits chained forwards (1 to 5), not parallel ones.
  UNKNOWN per carrier. Test by ringing the existing number from three phones at once.
- **A plain single landline** normally carries one call at a time. Whether the exchange
  forwards several callers at once is UNKNOWN. A multi-line system (EPABX or PRI) forwards
  each line.
- **On our side, one agent handles parallel calls.** The ceiling is ThinnestAI's concurrency
  limit: 10 on Pro, raised free on request (VENDOR-STATED, Ashutosh's email of 11 Oct 2026).

## 5. Handing a caller to a person: never back to the same number

If the existing number forwards to Calevate, a hand-off to that same number is forwarded
straight back to the AI: a loop. ThinnestAI refuses loops it can see inside its own system
(`forward_loop`); a loop created by the client's carrier is outside its view.
"No answer" and "busy" forwarding loop the same way, because the staff line is busy or
unanswered at the moment of the hand-off.

The working pattern is the one competitors use:
1. Existing number → forward → Calevate number → agent answers.
2. The agent books, answers from knowledge and takes messages.
3. When it needs a person, it hands off to a **separate staff phone** with no forwarding.
   ThinnestAI's `handOver {mode: call}` works on numbers rented from ThinnestAI
   (THINNEST-INTEGRATION §2, D-690). The destination is fixed at publish.
4. If staff do not answer, the agent records the request for a call-back (already built).

### What competitors do (web, secondary)

| Who | How |
|---|---|
| MyOperator (India) | The AI agent runs inside MyOperator's own cloud phone system and transfers to a staff extension on the same system. This is the only fully "on par with a receptionist" setup, and it needs the number hosted on MyOperator. |
| Exotel + ElevenLabs | The AI runs on Exotel numbers (ExoPhones), with a connect step to a human. |
| Retell (US) | The customer forwards its existing number. Cold transfer (SIP REFER, caller ID depends on the carrier) or warm transfer (the AI briefs staff first). |
| Vapi (US) | Transfer to a number or SIP address. Users report blind transfers where the staff phone never rang; Vapi's advice is attended (warm) transfer. |
| Bland (US) | Live transfer to a fixed `transfer_phone_number`. |
| US AI-receptionist products generally | Forward the existing number, transfer to a different staff line, fall back to a message. |

No source found addresses the loop case directly.

## 6. Outbound calls cannot show the existing number

- **Law.** Showing a number other than the line actually calling is tampering with a telecom
  identifier, an offence under the Telecommunications Act 2023 s.42(3)(c), with up to three
  years' imprisonment and a fine up to ₹50 lakh. DoT issued an advisory against CLI spoofing on
  18 Feb 2025. Web, secondary (law-firm summaries); the Act's text was not read here.
- **SIM gateways.** Routing AI calls through the clinic's SIM in a gateway ("SIM box") is
  treated as illegal and is regularly prosecuted. Web, secondary (news of police raids); the
  exact licence clause was not found.
- **ThinnestAI.** An outbound call's `from` must be one of the agent's own numbers, rented or
  lent (OPERATIONS T-row on the trial number, `calls/place-call`). VERIFIED-VENDOR-DOCS.

So the AI calls from the client's Calevate number. Ways to make it read as the clinic:
1. Call-backs to the Calevate number reach the same agent (already true).
2. The agent's first sentence names the business. Hard rule 5's AI and recording answers are
   unchanged.
3. **CNAP** (the regulator's calling-name display) shows the name the number is registered
   to, which is the client's business name for a number rented in its name. Status: trials;
   the March 2026 nationwide target slipped, and telcos have asked DoT how business names
   should show. Web, secondary.
4. **Truecaller for Business** shows a verified name and logo today. It is paid, on the
   client's side.
5. **Airtel Business Name Display** works only on Airtel enterprise numbers, so it does not
   apply to ThinnestAI numbers.
6. The clinic tells patients to save the reminder number, for example in a message sent at
   booking.

Staff calling by hand keep using the existing number. Nothing new needs to be bought for that.

## 7. Open checks before the first client forwards a number

1. **Which caller number the agent sees on a forwarded call:** the patient's, or the clinic's
   own. If it is the clinic's, every lead gets the clinic's number as the patient's, and every
   call-back rings the clinic. UNKNOWN. It is item 21 of the 10 Oct ThinnestAI email; ThinnestAI
   offered test calls on Airtel, Jio, Vi and BSNL. A quick self-test: forward a SIM to a
   Calevate number, ring it from another phone, read the call record.
2. **Which number the staff phone shows on a hand-off.** UNKNOWN.
3. **How many simultaneous forwards each carrier allows** (section 4). UNKNOWN.
4. **The forwarded-leg charge on the client's plan** (section 2). UNKNOWN.

## 8. What was built (D-746, 11 Oct 2026)

1. **Records and choices.** `forwarded_lines` (FORCE-RLS): the published number, line kind,
   carrier, the client's mode (`conditional` or `all_calls`) and ring time (5-30 s; 0 is all
   calls), the Calevate number it forwards to, who confirmed it is the business's own, and the
   findings of the latest test. Client screens: the onboarding guide
   `/c/[slug]/setup/existing-number` (offered once a Calevate number exists, skippable), and
   Settings > Phone numbers; admin: a card on the client's Numbers page.
2. **Codes as data** (`apps/api/forwarding/codes.py`, `GET /v1/forwarding/codes`), each with its
   evidence class and source; Jio shown as "use the MyJio app or phone settings" with the
   disputed sets marked; landlines and office systems as "ask your provider to enable call
   divert". Copy buttons; no `tel:` links (section 9e).
3. **Loop guard** on every writer: a business contact, a hand-off rung and the healer fallback
   phone may not equal a published number, and the reverse. Message: "Use a phone that does not
   forward to your Calevate number."
4. **Verification call** (`apps/api/forwarding/testing.py`): one or two legs from platform
   numbers in our developer workspace to the recorded number only, owner-only with a code typed
   for it, 09:00-21:00 IST, three a day, audited; it records whether the call arrived, which
   number arrived (open check 1, now measured per client), and whether two at once arrived
   (open check 3). Every minute is absorbed (`forwarding_test_min`); the arrival files no lead.
5. **Hidden caller ID:** a forwarded call showing the business's own number is detected at the
   caller lookup; the agent asks for a call-back number and reads it back; the call is marked and
   the lead takes that number.
6. **Quiet line:** a working line whose client normally gets calls (6 inbound calls on 3 IST days
   in the 14 days before) and has none for 3 days raises one client notice and one
   `forwarded_line_quiet` alarm per episode.
7. **"Save our number"** (founder, added 11 Oct 2026): built behind a per-client switch, off by
   default; one WhatsApp per caller per client from Calevate's own account, gated on the dial
   gate's do-not-call check and the caller's messaging opt-in, in te/hi/en. Blocked on the WhatsApp
   account and template approval (OPERATIONS gate F-8).
8. **Not built** (founder): a hand-off message to staff.

Open checks 1-4 above are OPERATIONS §2 gates F-1, F-4, F-2 and F-7; the code forms are F-3.

## 9. Verification of 11 Oct 2026 (second pass)

Classes: carrier-own, standards body, web-secondary. Read 11 Oct 2026.

- **Conditional forwards survive an all-calls toggle.** 3GPP TS 22.082 §1.6.82.2-4: while
  unconditional forwarding is active the conditional forwards are quiescent and become operative
  again when it is deactivated; erasure deactivates (§1.3.6). Standards body, read through an
  unofficial rendering (https://whatthespec.net/friendlyspec/spec/22.082/19.0.0); the ETSI PDF
  ts_122082v180001p.pdf was not readable here.
- **No-reply timer** 5-30 s in 5-s steps; without one, the operator's default (no number given),
  TS 22.082 §3.3.3; VoLTE: "a service provider option", TS 24.604 §4.8.1. Standards body. Whether
  Airtel, Jio, Vi and BSNL honour a user-set timer: not found.
- **`##002#` all forwards, `##004#` all conditional forwards:** TS 22.030 Annex B, read in a 2000
  SA1 draft (https://3gpp.org/FTP/tsg_sa/WG1_Serv/TSGS1_08_Beijing/Docs/S1-000154.doc). Standards
  body, draft.
- **A declined call goes to the busy forward** (user-determined user busy): TS 22.082 §2.3.8 and
  TS 24.628 §4.1. Standards body; no Indian carrier source.
- **Switched off, flight mode, Wi-Fi calling:** not found on any carrier page (only blogs and user
  forums), so the guide puts them in the self-test, not as fact.
- **Vi** codes `*21*N#`, `*67*N#`, `*61*N#`, `*62*N#`, off `##21#` etc., cancel all `##002#`:
  https://www.myvi.in/blog/how-to-activate-and-deactivate-call-forwarding-code-on-vi (3 Dec 2025),
  carrier-own. Secondary sites print Vi with `**`.
- **Airtel** publishes the all-calls divert and the Airtel Thanks app only
  (https://www.airtel.in/blog/airtel-app/divert-calls-in-airtel/, carrier-own); its conditional
  codes are web-secondary.
- **Jio** publishes no codes: MyJio > Profile > Mobile Settings > Service Settings > Call
  Forwarding, or the phone's settings; forwarding is "free of cost" and not to BSNL numbers
  (https://www.jio.com/help/faq/mobile/services/hd-voice/how-can-i-activate-call-forwarding-service,
  carrier-own). `*401`/`*403`/`*405`/`*409`/`*413`: web-secondary, disputed.
- **BSNL mobile** codes: web-secondary only. **BSNL and Airtel landline** divert: not found.
- **TCCCPR:** "commercial communication" is one whose primary purpose is to inform about,
  advertise or solicit business (TCCCPR 2018, third-party copy at casemine.com, web-secondary);
  the 12 Feb 2025 amendment's reg. 4 autodialer notice is known from law-firm summaries only
  (Khaitan & Co., S.S. Rana). No source addresses a test call; that is gate F-6.
- **tel: links:** "if a URL contains the * or # characters, the Phone app does not attempt to
  dial" (Apple, PhoneLinks reference, vendor-own); Chromium's Click to Call ignores numbers with
  `#`, `*` or `%` (Chromium commit for bug 1180510).

## Sources (read 11 Oct 2026)

- TelecomTalk, call forwarding on Airtel, BSNL, Jio and Vi:
  https://telecomtalk.info/how-to-start-and-stop-call-forwarding/493353/
- Smartprix (Hindi), the same:
  https://www.smartprix.com/bytes/hi/how-to-activate-or-deactivate-call-forwarding-hindi/
- CallerDesk, call forwarding for Indian businesses: https://callerdesk.io/blog/?p=2030
- BSNL Chennai circular, free call forwarding (2021):
  https://www.chennai.bsnl.co.in/latestnews/2021/FEB/
- TRAI PR 09/2025: https://trai.gov.in/sites/default/files/2025-02/PR_No.09of2025.pdf
- 3GPP S1-000328 (forwarding limits):
  https://3gpp.org/ftp/TSG_SA/WG1_Serv/TSGS1_08_Beijing/Docs/S1-000328.doc
- Retell transfer call: https://docs.retellai.com/build/transfer-call
- Vapi transfer call: https://docs.vapi.ai/tools/transfer-call
- Vapi support thread, transfer never rings:
  https://support.vapi.ai/t/33157798/transfer-initiated-but-destination-phone-never-rings-two-cal
- Bland live transfer: https://docs.bland.ai/tutorials/live-transfer
- MyOperator AI agent:
  https://support.myoperator.co/portal/en/kb/articles/what-is-myoperator-ai-agent-voice-1-7-2026
- MyOperator, AI hand-off in India: https://myoperator.com/blog/ai-voice-agent-human-handoff-india
- ElevenLabs and Exotel: https://elevenlabs.io/agents/integrations/exotel
- Conventus Law, DoT advisory on identifier tampering:
  https://conventuslaw.com/report/india-dot-advisory-on-telecom-identifier-tampering-a-strong-regulatory-push-to-safeguard-communication-networks/
- ETV Bharat, SIM box bust, Delhi (Apr 2026):
  https://www.etvbharat.com/en/state/international-cyber-fraud-syndicate-using-sim-box-busted-in-delhi-many-held-enn26041004057
- Business Standard, CNAP rollout target:
  https://www.business-standard.com/industry/news/cnap-service-nationwide-rollout-by-march-2026-dot-trai-telecom-125102901190_1.html
- Outlook Business, whose name CNAP shows:
  https://www.outlookbusiness.com/corporate/whose-name-should-show-up-on-caller-id-telcos-ask-govt-for-guidance
- Storyboard18, Airtel Business Name Display:
  https://www.storyboard18.com/how-it-works/airtel-business-launches-business-name-display-for-enterprises-pilots-with-250-firms-64714.htm
