# TCCCPR Third Amendment Regulations, 2026 — what it changes for this product

**EVIDENCE CLASS: REPORTED.** The source is an access provider's summary, not the
regulation. Vobiz (the carrier) emailed its customers a note on the Telecom Commercial
Communication Customer Preference (Third Amendment) Regulations, 2026, notified by TRAI on
18 September 2026, and the founder relayed it on 26 September 2026. Vobiz says its note is
based on TRAI press release No. 119/2026 and on its own operating experience, and that it
is not legal advice. Nobody here has read the Gazette text or the press release:
`trai.gov.in` is egress-blocked from this container. Every provision below is therefore
Vobiz's reading of TRAI's announcement, and none of it may reach a client-facing claim
that a client is compliant.

What IS primary is the rule this amendment sits on top of: TRAI direction
RG-25/(18)/2023-QoS of 18 June 2024 — *"Senders shall not use any other 10-digit fixed
line/ mobile number for making Promotional/ Service/ Transactional voice calls"*
(`primary-legal-findings-2026-09-20.md` §1, PRIMARY-REGULATORY, FOUNDER-RELAYED).

**Effective date: UNKNOWN.** The press release gives none. The March draft provided for
commencement 30 days after Gazette publication; whether the final text keeps that is not
known.

## 1. Provisions, as reported

| # | Provision | What it means here |
|---|---|---|
| 1 | **A2P calls are defined**: calls initiated by an application, software or automated platform without direct human dialling, explicitly including autodialling, robo-calls and pre-recorded or **artificial voice**. | Every outbound call our agents place is A2P. Inbound is not: nothing dials. |
| 2 | **A2P pre-declaration is mandatory**: every entity making A2P calls declares that use, **and the CLIs it will use**, to its access provider in advance. Undeclared A2P calls are treated as unsolicited commercial communication (UCC). | This is Regulation 4's autodialer notice (`compliance/autodialer.py`) with the caller numbers added. |
| 3 | **A2P termination charge** of up to ₹0.05/min, levied between operators. Calls on the designated commercial series (140xx, 1600xx/1601xx) and Authority-authorised calls are **exempt**. | Our outbound is refused off 140/160 (`campaigns/service.SERIES_FOR_CLASSIFICATION`), so compliant traffic is exempt. No change to the cost model. |
| 4 | **140xx and 1600xx/1601xx are protected**: operators will not flag them as suspected spam, and call-management apps may not blanket-block or spam-tag them. | Rewards the series rule this repository already enforces. Vobiz names **1601xx for eligible service and transactional calls**, consistent with our record that 1601 opened to non-BFSI entities (`primary-legal-findings-2026-09-20.md` §1) and inconsistent with the carrier table that calls 160 BFSI-only (`orchestrator-commercial-and-carrier-2026-09-13.md` §5.3). Eligibility is not settled by this note. |
| 5 | **Operator AI/ML flags aggregate per sender**: five or more flagged CLIs linked to one sender within 10 days triggers graded action — KYC re-verification, physical verification, outgoing barring, and for repeat cases disconnection. | Rotating numbers no longer resets risk. The unit of exposure is the sender (the client). |
| 6 | **Complaint trigger lowered**: three unique complaints within 10 days, **combined with an AI flag on the CLI**, can trigger action. The previous threshold was five. | `campaigns/complaint_spike.py` paused on five opt-outs in 24 hours per campaign — looser than the new trigger. |
| 7 | **Inquiry-based calling is time-limited**: commercial calls based on a customer's inquiry are permitted for **7 days** from the inquiry, which must be written or digital and kept in verifiable form. | A lead form is a written, digital inquiry. Nothing enforced a window on it. |
| 8 | **Legacy consents need registering**: consents already held are recognised only if obtained through verifiable means **and registered on the operators' digital consent platform**. | Our `consent_ledger` is not that platform. See §3. |
| 9 | **Consumer appeal** of a UCC complaint outcome within 15 days. | Call, consent and campaign records must survive long enough to answer it. |

## 2. Open, per the same note

* The effective date and any transition.
* How a declaration is made: format, route, acknowledgement. Vobiz expects declarations
  for traffic on its network to go through Vobiz.
* How the termination charge is applied: the actual rate, billing increment, and the
  treatment of unanswered or failed calls.
* **Where the A2P boundary sits** for agent-assisted or predictive dialling. Not settled.
  For **customer-requested callbacks** the founder has decided (§3.1).
* Mandatory access-provider/sender contract terms and a sender classification, to be
  prescribed separately.

## 3. What this repository does about each, and what it deliberately does not

1. **The 7-day inquiry window** is enforced on consent that a lead form records
   (`web_form_optin`): the row carries `expires_at` seven days after capture, and the dial
   gate's existing `consent_expired` rule refuses every later dial path — campaign,
   callback, recall, "call now" — because they all pass through `check_dispatch`. It does
   NOT extend to a caller's in-call request (`inbound_call_verbal`) or a staff-recorded
   request: those are not written or digital inquiries in the sense the note uses, and
   customer-requested callbacks were the open question in §2.
   **The founder answered it on 26 Sep 2026: a caller who asks, in a call, to be rung back
   has consented to that call.** Booking writes a `callback` grant, `inbound_call_verbal`,
   citing the call, and lapsing two hours after the promised time
   (`compliance.consent.record_callback_request_consent`, D-640). It is written only where
   what is on file would not already let that call through, so it never narrows a wider
   permission: the gate reads a person's newest row alone.
2. **The complaint-spike pause** is tightened to the new trigger's shape: three opt-outs
   within ten days. Opt-outs are our early signal, not the operator's complaint count and
   not its AI flag, which we cannot see; the point is to pause before the operator acts.
3. **The declared CLIs** are recorded on the autodialer notice, and the dial gate refuses
   a call from a number the notice does not declare. The declaration itself is the
   client's, made to their own access provider; Calevate records it and never declares on
   a client's behalf, for the reason `compliance/autodialer.py` gives.
4. **Legacy-consent registration is NOT built.** Whether a consent held in our ledger is
   recognised without registration on the operators' platform, what that platform accepts,
   and whether a platform like ours can register on a client's behalf are all unknown, and
   building around a guess about them would be inventing the shape of the obligation. It is
   OPERATIONS §2 gate 60.
5. **Retention is NOT floored, deliberately.** Only recordings carry a retention minimum,
   because TRAI mandates 90 days of audio. For transcripts, leads and the consent log no
   rule we hold sets one, and a floor would override a client who keeps personal data for
   less, the choice DPDP data minimisation favours, with a number of our own invention. Two
   facts make it safe to leave: no route or screen lets anyone shorten a period today, and
   the seeded defaults (transcripts 365 days, leads 1,095, consent log 2,555) sit far above
   any appeal horizon. The requirement is recorded for the future instead: a retention
   settings surface, when one is built, takes its lower bound from the real appeal horizon
   (the complaint window, the resolution time and the 15-day appeal), which needs the
   operative text.
