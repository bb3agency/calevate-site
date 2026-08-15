# The Cartesia question that gates D-94 — send this, don't research it

**Status:** UNANSWERED. Searched Aug 2026 and found nothing public either way;
`docs.cartesia.ai` and `www.cartesia.ai` are unreachable from our build environment, and
the Line SDK at `github.com/cartesia-ai/line` @ `3062c978` carries no SIP or carrier
configuration surface. **This is not researchable from here. It has to be asked.**

**Why it gates everything:** TRD §10.4a shows Cartesia Line's Scale tier beating our Bolna
economics between roughly 12,300 and 26,400 minutes/month — about ₹23,000/month at 20,000
minutes. TRD §10.5 pre-commits three triggers before we would move, and this is the one
that is not about price. Our entire compliance spine (PE/TM registration, DLT headers and
templates, 140/160 series classification, DNC before every dispatch tick) presumes an
Indian carrier relationship. Cartesia's own number paths — Cartesia-provisioned, imported
Twilio, or Voximplant — do not yield a DLT-registered Indian number.

If the answer is **yes**, an Exotel/Vobiz-class Indian carrier can front Line and the
migration path in TRD §10.6 is live. If the answer is **no**, the cost window is
unreachable regardless of price and D-94's re-evaluation never fires. **One email decides
which of those two worlds we are in.**

Send to Cartesia sales or support. Keep it short — a long email gets a vague answer.

---

Subject: **Line + SIP: can we bring our own Indian carrier?**

Hello,

We run an AI voice-agent platform for small businesses in India (Telugu-first inbound
receptionists and outbound campaigns) and are evaluating Cartesia Line as our
orchestration layer. Four questions, and the first is the one that decides it for us:

1. **Does Line accept BYOC SIP trunking from an arbitrary carrier?** Indian telecom
   regulation (TRAI/TCCCPR) requires commercial calls to originate from DLT-registered
   numbers on specific series, which in practice means an Indian carrier such as Exotel,
   Plivo or Vobiz. We would need to connect our own SIP trunk rather than use
   Cartesia-provisioned numbers or an imported Twilio account. Is inbound and outbound SIP
   from our own carrier supported, and on which plan tiers?

2. **Webhook signing.** How does Line sign its webhooks — which header, which algorithm,
   and over exactly what bytes (raw body or a canonicalised form)? We verify before
   parsing and need to implement this correctly rather than infer it.

3. **Scale tier concurrency.** Your published tiers list 1/3/5/10 agent slots. At the
   Scale tier, is the cap 10 concurrent agents, and what is the behaviour at the limit —
   queue or reject, and with what error shape? If we exceed it, what does the next step up
   cost and is there an annual commitment?

4. **India data residency.** We use an all-India model stack today for regulatory reasons
   (DPDP). Is there a self-serve India region for Line, or is India-resident processing
   only available through the Blue Machines enterprise arrangement?

Happy to jump on a call if that is easier.

Thanks,
[name] — Calevate

---

## Recording the answer

Whatever comes back goes in this file, dated, with the sender, and then into
`docs/OPERATIONS.md` as gate 13. Per `docs/RESEARCH-DISCIPLINE.md` R7, a vendor's answer in
writing is verification; a salesperson's verbal "yes, we support that" is corroboration and
gets marked as such until it is in an email. D-31 and D-32 exist because we made that
mistake once already.

**Suggested OPERATIONS gate 13 wording, to add when the answer lands:**

> **Gate 13 — Cartesia BYOC SIP.** Before any Cartesia work beyond the adapter, obtain in
> writing whether Line accepts SIP trunking from an arbitrary Indian DLT-registered
> carrier. If no, TRD §10.4a's cost window is unreachable and the exit does not exist at
> price. Cheap to ask; it gates everything downstream.
