# A campaign call blocked as "Suspected Spam": what happened and what we do about it

Research of 4 Nov 2026, after Rytu Khata's campaign of 4 Nov 2026. Every outside fact below names
its source and the date it was read (all read 4 Nov 2026 unless stated). Evidence classes follow
hard rule 11: **PRIMARY** (regulator's own text or the vendor's own page), **VENDOR-PUBLISHED**
(vendor marketing/blog), **SECONDARY** (a partner's or a newspaper's account), **INFERENCE** (our
reasoning from the above), **UNKNOWN**.

**Scope rule.** Everything here is about being *recognised* as a legitimate caller. Number rotation
to shed a label, caller-ID spoofing and disguised call patterns are detection evasion and are
refused. TRAI's own amendment of 18 Sep 2026 now targets exactly that: when five or more CLIs of
one sender are flagged within ten days, the operator opens graded action up to disconnection
(TRAI PR of 18 Sep 2026, item 4(i)(c)). So evasion is wrong and also loses the account.

---

## (a) What blocked the call

| Finding | Evidence |
| - | - |
| The recipient's Samsung phone screened the call through **Smart Call**, whose features "are provided by Hiya". | PRIMARY: https://www.samsung.com/in/apps/smart-call/ (India page). |
| Galaxy phones have **Phone > Settings > Caller ID and spam protection > Block spam and scam calls**, with two choices: **Block all spam and scam calls** or **Only block high-risk scam calls**. | PRIMARY: https://www.samsung.com/us/support/answer/ANS00088083/ and https://www.samsung.com/ca/support/mobile-devices/manage-call-settings-on-your-galaxy-phone. Samsung India's own help page with this wording was not found; the India page says features "may vary by country and device". |
| Her log shows our number as "Suspected Spam" (Hiya logo) and two "Blocked by Phone" entries (5:54 PM, 8:26 PM). So the setting was most likely **Block all spam and scam calls**: "Suspected spam" is a lower tier than a high-risk scam label, and it was still blocked. | INFERENCE from the two Samsung pages plus the founder's screenshot. Not confirmed on her handset. |
| Hiya's stated reasons a number is labelled: several people reported it; a calling pattern like spam (high volume, short calls); a previous owner was flagged; or the carrier or a business on the number's range was flagged. | PRIMARY: https://spamblocker-support.hiya.com/en/articles/28-my-phone-number-is-labeled-as-spam-%E2%80%94-how-to-fix-it |
| Which of those applies to +91 80 6558 0032 | **UNKNOWN.** We have placed few calls from it (§46 of the replies log: 35 production calls in October, all tests), so volume is an unlikely cause, but a previous owner or the number range cannot be ruled out without Hiya's reputation report. |
| ThinnestAI reported the call as `hangup: busy`. Its enum is `answered, no_answer, busy, rejected, unreachable, cancelled, voicemail, before_agent, failed, not_placed` — **no value for "blocked by the handset's spam filter"**. | PRIMARY: `thinnest-findings/mirror/snapshots/2026-10-29/pages/api-reference/calls/get-call.md:947-962`. |
| The 5:54 PM block is the same call §47 of `docs/vendor/thinnest-replies-2026-10-12.md` attributes to two simultaneous calls on one number (`out_f99845ed…`, 17:54 IST, "busy" after 24 s, "phone was free and never rang"). The phone's own log now explains "never rang". The 8:26 PM entry is our retry ladder (`apps/workers/campaign_dispatch.py`: `busy` goes back on the retry ladder), which dialled a phone that blocks us again. | INFERENCE (times match to the minute). **§47 should be rewritten before it is sent** — see (d). |

---

## (b) What the founder can do today, in order

1. **Ask the person to add the number to her contacts, or mark it "not spam".** Samsung documents
   only blocking and reporting, plus removing a number from **Phone > Settings > Block numbers**
   (US page above); the pages read do not document a "not spam" button or say a saved contact
   bypasses the filter. So: ask her to check **Block numbers** and remove +91 80 6558 0032 if it
   is there, save it as a contact, and if the next call is still blocked, switch **Block spam and
   scam calls** to **Only block high-risk scam calls**. Whether saving a contact overrides
   Smart Call is **NOT VERIFIED** — treat the first test call as the check. This fixes one phone
   only.

2. **Register the number with Hiya (free).** Sign up at
   https://business.hiya.com/registration/number-registration/account/details?preselected=true
   (linked from https://www.hiya.com/products/connect/number-registration).
   - Who signs up: **Rytu Khata's business** (whoever holds the number in its name), not
     Calevate. Hiya's FAQ, as summarised by search, says a company providing registration for
     other businesses cannot use the free portal and the business should register directly. The
     FAQ page itself returned 403 here: **NOT VERIFIED from the page**.
   - What to submit: legal business name and address, a **DUNS** number (free to get; reported by
     Hiya's support pages via search, page itself 403, NOT VERIFIED), and the number
     +91 80 6558 0032.
   - Cost: free (PRIMARY, product page). Turnaround: business verification up to 24 h, number
     vetting under a day, then "a few more days" to propagate (PRIMARY, product page).
   - What it does: tells carriers and Hiya the number belongs to a verified business and gives a
     **Caller Reputation** view of whether the number is flagged. The product page says
     registration *reduces* the risk of a label but does not prevent one if people report or
     block the calls.
   - India: Hiya says the service covers "40+ countries" and names only the US, UK and Canada
     (PRIMARY: https://www.hiya.com/newsroom/press-releases/hiya-registration-now-available-to-businesses-around-the-globe,
     31 Jul 2024). **Whether India is one of them is NOT VERIFIED.** The sign-up form will
     either accept a +91 number or not; that is the check.

3. **If the label stays, file Hiya's one-time review.** Same spam-blocker article: for business
   numbers, register first, then submit the number on
   https://hiyahelp.zendesk.com/hc/en-us/requests/new?ticket_form_id=32894877171859. The form
   returned 403 to us, so its fields are unknown; submit the number, the registered business name,
   what the calls are (a service follow-up to people who signed up for the Rytu Khata app, with
   consent), and that the number is newly rented for that business. Turnaround: not stated
   anywhere we read.

4. **Pause calling from this number until step 2 shows it is clean.** Every call that a phone
   blocks is another negative signal (Hiya: low answer rates and repeated calls look like spam,
   PRIMARY-vendor blog https://blog.hiya.com/high-volume-caller, Apr 2021). Retries into a
   blocking phone make it worse.

5. **Send the ThinnestAI email in (d)** (rewritten §47).

Not today, and why:

- **Truecaller Verified Business Caller ID** shows a name/badge to *Truecaller users only*;
  people without Truecaller see the bare number (SECONDARY: Exotel's guide,
  https://developer.exotel.com/docs/call-support/advanced-features/truecaller-verified-caller-id).
  It does nothing for Samsung/Hiya. Truecaller's own site is blocked to our fetcher, so its terms,
  price and whether it clears an existing spam tag are **NOT VERIFIED**. Worth doing later for
  reach (many Indian users run Truecaller), but it is not the fix for this block.
- **Google Verified Calls** launched in India in Sep 2020 in the Google Phone app (SECONDARY: 2020
  press coverage). The Google help page we tried returned 404; current availability is **NOT
  VERIFIED**, and it would not apply to a Samsung phone using Samsung's own dialer.
- **Hiya Branded Call** (name, logo, reason on supported devices) is a paid upgrade (PRIMARY,
  Hiya blog of 13 Feb 2025). India coverage and price **NOT VERIFIED**.

---

## (c) What Calevate should build so every client's number stays reputable

Ordered by what protects clients soonest. None of this is built; nothing here changes code.

1. **Stop the retry ladder hammering a phone that blocks us.** Today `busy` re-enters the ladder.
   Because the engine cannot tell "busy" from "blocked by the handset" (enum above), we should
   not *guess*; but we can cap it: after one `busy` on a contact, the next attempt waits longer
   (the next day, not the same evening), and after two `busy` results with no answer ever, stop
   and show the owner "We couldn't get through on this number twice. Their phone may be blocking
   unknown numbers; ask them to save your number." That wording states what we know and no more.
   **Do not** relabel the call "blocked as spam" — no signal supports it (see 4).

2. **Register every client's number with Hiya at purchase, in the client's name.** Hiya's free
   portal is for the business itself; a platform registering for clients needs Hiya's **Number
   Reputation API**, "a premium service", requiring each client's contact details and
   documentation authorising us to represent them; fees per registered business and per
   reputation call, terms by agreement (PRIMARY:
   https://developer.hiya.com/docs/guides/voice-protection/number-reputation/get-started). Two
   paths: (i) now — a checklist step at number purchase that sends the owner to Hiya's free
   portal and records "registered on <date>"; (ii) once Hiya quotes and confirms India — the API,
   which also gives us the reputation status for (3). External blocker for (ii): Hiya's answer on
   India coverage and price.

3. **A per-number reputation status on the client's Numbers screen**: *Not registered /
   Registered / Flagged / Review filed (date)*. Source of truth: Hiya's reputation endpoint if we
   take the API; until then, what the owner records. Show it beside the number, one button per
   state (buttons-not-paragraphs).

4. **Show "blocked as spam" only with a real signal.** ThinnestAI's `hangup` enum has none today.
   This goes in the email; if they add one (or expose the SIP cause / carrier reason), we map it.
   Until then the owner sees "Busy" and, after the cap in (1), the advice line.

5. **Pace campaigns per number and keep one number per person.** ThinnestAI already enforces part
   of this: 200 calls per number per day, and "one person always sees the same number"; it warns
   that a burst marks a number and "everything it does afterwards suffers" (PRIMARY:
   `thinnest-findings/mirror/snapshots/2026-10-29/pages/channels/phone-numbers.md:777-811`,
   `voice-campaigns.md:346-353`). Spare numbers there spread *volume* under a daily cap with a
   fixed number per person; they are not label-dodging, and we must never use them to move
   calls off a flagged number. Our side: honour the account's call lines (done, 3811f617f), ramp
   a new number's first days, keep calls inside the client's hours, and show answer rate per
   number so the owner sees a falling number before it is labelled (Hiya: answer rate, repeat
   calls and short ring time are the signals; it recommends at least 4 rings or 15 s before
   hanging up, PRIMARY-vendor blog above, 2021).

6. **TRAI A2P declaration and the designated series** (already D-941; restated because it is the
   durable fix):
   - From about mid-Nov 2026, a call "initiated by an application, software system, or automated
     platform … including … artificial voice technologies" made without prior declaration of the
     CLIs to the originating access provider "shall be treated as Unsolicited commercial
     communication" (PRIMARY: TCCCPR Third Amendment, 18 Sep 2026, reg. 2(ea) and new reg. 4,
     https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf; reg. 4 in force
     60 days after Gazette publication — the exact Gazette date is NOT VERIFIED). ThinnestAI said
     on 30 Oct the process "is not yet live" at the telcos (§41).
   - Calls from the **140xx, 1600xx and 1601xx** series may not be flagged as suspected spam by
     operators (new reg. 21A proviso), and call-management apps may not tag, block or filter
     them, though a user may still block on their own phone (reg. 34A as substituted; PRIMARY,
     same PDF). This is the one structural protection against a Hiya/Truecaller label.
   - **1601** is for service and transactional calls by non-BFSI, non-Government entities, but
     Phase I covers only utilities, courier and logistics, and numbers go "directly to eligible
     entities, and not to intermediaries or aggregators" (PRIMARY: TRAI PR 113/2026 of 10 Aug
     2026, https://trai.gov.in/sites/default/files/2026-08/PR_No113of2026_1.pdf). So most of our
     clients cannot get one today. **1600** is BFSI and Government (PRIMARY: TRAI PR 151/2025).
     **140** is for promotional calls, issued after DLT registration (ThinnestAI
     `phone-numbers.md:243-284`). Whether a *service* campaign may run from a 140 number is
     **NOT VERIFIED**; the 2025 amendment says service calls belong on the series "assigned for
     the purpose of making service and transactional calls" and keeps promotional content out of
     them (PRIMARY: TCCCPR Second Amendment, 12 Feb 2025, reg. 3 and the agreement clause,
     https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf).
   - Build: when a client is in a 1601 Phase-I sector, offer the 1601 path at number purchase;
     track phase expansion.

7. **CNAP (caller name).** Reported: the DoT circular of 13 Oct 2026 starts CNAP from 1 Nov 2026
   on 4G/5G; **landlines are excluded** for now; business/bulk connections may show a verified
   "preferred name" (registered trade mark or GST trade name) (SECONDARY: ThePrint,
   https://theprint.in/india/no-more-unknown-callers-govt-makes-caller-name-display-mandatory-from-1-november/3072774/;
   the DoT circular itself was not found on dot.gov.in, NOT VERIFIED). Our numbers are 080
   landline-style numbers, so whether any name shows is **UNKNOWN** — already asked in §40 item 3,
   unanswered.

---

## (d) Drafted email to ThinnestAI (replaces the unsent §47; add as §48 when the founder approves)

Context for the log entry: the recipient's Samsung phone shows the 17:54 call as "Blocked call —
Blocked by Phone" with our number labelled "Suspected Spam" (Hiya), so §47's question about two
simultaneous calls on one number is no longer the explanation for `out_f99845ed`. §47 Q1 (how
many simultaneous calls one number carries) is still worth asking and is kept as item 5.

> Subject: A call reported "busy" was blocked as spam by the person's phone
>
> Hi Ashutosh,
>
> On 4 Nov at 17:54 IST and again at 20:26 IST our agent called a customer from +91 80 6558 0032,
> a number we rent from you. Both calls came back `hangup: busy` (the first is out_f99845ed).
> The customer's Samsung phone shows our number as "Suspected Spam" (Samsung's caller ID,
> powered by Hiya) and both calls as "Blocked by Phone". The phone never rang.
>
> 1. **Reason codes.** When a handset rejects a call this way, what does the carrier send you,
>    and could the call report a distinct `hangup` (or the SIP cause) rather than `busy`? We
>    want to tell the business "their phone blocked the call" only when that is true.
> 2. **The number's history.** Was +91 80 6558 0032 used by anyone before us, and do you know of
>    any spam label on it or on its number range?
> 3. **Registration with caller-ID apps.** Do you register your Indian numbers with Hiya,
>    Truecaller or the operators' spam systems, or offer verified business caller ID (name and
>    logo) on them? If not, may our clients register the numbers they rent from you directly
>    with Hiya and Truecaller in their own business name?
> 4. **Operator spam flags.** TRAI's amendment of 18 Sep 2026 has operators flag suspected spam
>    numbers and gives the sender a way to object and be unflagged. If one of our numbers is
>    flagged, will you or your carrier tell us, and who files the objection?
> 5. **Simultaneous calls on one number.** How many outgoing calls can one of your rented Indian
>    numbers carry at the same moment, and is an extra call refused or reported as busy?
> 6. Still open from 30 Oct: the A2P declaration route before it takes effect, which name CNAP
>    shows for our numbers, and 1601-series numbers for clients in eligible sectors.
>
> Thanks,
> Umesh

---

## (e) Open questions and what was not verified

- Whether Hiya Number Registration (free portal or API) accepts **Indian numbers**: NOT VERIFIED
  (Hiya pages name only US, UK, Canada).
- Hiya's third-party eligibility rule and DUNS requirement: reported via search; the Hiya FAQ
  page (`connect-support.hiya.com`, `hiyabusiness.zendesk.com`) returned 403. NOT VERIFIED from
  the page.
- Fields and turnaround of the Hiya review form: 403. NOT VERIFIED.
- Samsung India's exact menu wording, whether a saved contact bypasses Smart Call blocking, and
  whether a "not spam" report exists: NOT VERIFIED (US/Canada pages only).
- Truecaller for Business terms, price, and effect on existing spam tags: NOT VERIFIED
  (truecaller.com is blocked to our fetcher; only Exotel's partner guide read).
- Google Verified Calls in India today: NOT VERIFIED (help page 404; 2020 press only).
- TCCCPR Third Amendment Gazette publication date, hence the exact day reg. 4 (A2P declaration)
  takes effect: NOT VERIFIED. The 18 Sep 2026 notification + 60 days gives ~17 Nov 2026 only if
  published that day.
- Whether a service campaign may lawfully run from a 140 number: NOT VERIFIED.
- CNAP: the DoT circular itself not read; landline exclusion is from press reports.
- Why this specific number is labelled (previous owner, range, reports): UNKNOWN until Hiya's
  reputation report or ThinnestAI answers (d) item 2.
- First Orion and TNS reputation guidance: not read this session; section (c)5 rests on Hiya's
  own blog and ThinnestAI's docs.
